"""P05: product API router (/api/v2). Contract: docs/nodes/p05_api.md"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from psycopg.rows import dict_row
from pydantic import BaseModel

from tmod.product.db import SEED, dsn
from tmod.product.etl import load_rows_xlsx, run_etl
from tmod.product.model import populate_scenario
from tmod.product.routing import OSRMProvider, ValhallaRoadProvider, route_detail
from tmod.product.solve import run_scenario

MASTERS: dict[str, tuple[str, list[str]]] = {   # table -> (natural key, writable columns)
    "vehicle_type": ("type_code", ["name", "capacity_kg", "capacity_m3", "max_stops", "max_route_s", "max_distance_m", "fixed_cost", "cost_per_km", "cost_per_hour", "osrm_profile", "active_flag"]),
    "vehicle": ("vehicle_code", ["name", "vehicle_type_id", "depot_id", "crew_size", "work_limit_s", "duty_limit_s", "active_flag", "effective_from", "effective_to"]),
    "depot": ("depot_code", ["name", "location_id", "open_time", "close_time", "active_flag"]),
    "customer": ("customer_code", ["name", "customer_type", "default_location_id", "priority", "active_flag"]),
    "location": ("location_code", ["name", "address_line", "city", "state_code", "postal_code", "country_code", "latitude", "longitude", "active_flag"]),
    "product": ("product_code", ["name", "category", "unit_weight_kg", "unit_volume_m3", "install_s", "active_flag"]),
    "service_time_rule": ("rule_code", ["description", "customer_type", "product_category", "stop_base_s", "per_unit_s", "priority", "active_flag"]),
}
PROVIDERS = {"OSRM": OSRMProvider, "VALHALLA": ValhallaRoadProvider}


def _conn(plain: bool = False) -> psycopg.Connection:
    """dict rows for API responses; plain tuples (plain=True) for engine modules that unpack rows positionally."""
    try:
        con = psycopg.connect(dsn(), row_factory=None if plain else dict_row, connect_timeout=3)
    except psycopg.OperationalError as e:
        raise HTTPException(503, f"database unavailable: {str(e).splitlines()[0][:120]}")
    con.execute("SET search_path TO tmod, public")
    return con


def _json(v):
    return json.loads(json.dumps(v, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)))


class Jobs:
    def __init__(self) -> None:
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, fn, *a) -> str:
        jid = uuid.uuid4().hex[:8]
        self.jobs[jid] = {"job_id": jid, "status": "queued"}

        def run():
            self.jobs[jid]["status"] = "running"
            try:
                self.jobs[jid].update(status="done", result=_json(fn(*a)))
            except Exception as e:  # noqa: BLE001
                self.jobs[jid].update(status="error", error=f"{type(e).__name__}: {e}"[:500])
        self.pool.submit(run)
        return jid


class ScenarioIn(BaseModel):
    code: str
    name: str
    plan_date: date
    depot_code: str
    provider: str = "VALHALLA"
    time_limit_s: int = 30
    description: str | None = None


class ScenarioUpdate(BaseModel):
    name: str | None = None
    time_limit_s: int | None = None
    provider: str | None = None
    settings: dict | None = None
    constraints: dict[str, dict] | None = None      # code -> {"enabled": bool, "params": {...}}
    weights: dict[str, float] | None = None         # objective_code -> pct
    vehicles: list[str] | None = None               # vehicle codes


class AdjustmentIn(BaseModel):
    day_of_week: str | None = None
    time_from: str = "00:00"
    time_to: str = "24:00"
    factor: float
    reason: str | None = None


def build_router(jobs: Jobs | None = None) -> APIRouter:
    r = APIRouter(prefix="/api/v2")
    jobs = jobs or Jobs()

    # ---------- masters ----------
    @r.get("/master/{table}")
    def master_list(table: str, active: bool = True):
        if table not in MASTERS:
            raise HTTPException(404, "unknown master")
        with _conn() as c:
            return _json(c.execute(f"SELECT * FROM {table}" + (" WHERE active_flag" if active else "") + f" ORDER BY {MASTERS[table][0]}").fetchall())

    @r.post("/master/{table}", status_code=201)
    def master_upsert(table: str, body: dict[str, Any]):
        if table not in MASTERS:
            raise HTTPException(404, "unknown master")
        key, cols = MASTERS[table]
        bad = [k for k in body if k not in cols + [key]]
        if bad or key not in body:
            raise HTTPException(422, f"allowed columns: {[key] + cols}; bad: {bad or 'missing ' + key}")
        with _conn() as c:
            ks = [k for k in body if k != key]
            exists = c.execute(f"SELECT 1 FROM {table} WHERE {key}=%s", (body[key],)).fetchone()
            try:
                if exists and ks:   # partial update: NOT NULL columns may be omitted
                    row = c.execute(f"UPDATE {table} SET {', '.join(f'{k}=%s' for k in ks)} WHERE {key}=%s RETURNING *", [body[k] for k in ks] + [body[key]]).fetchone()
                elif exists:
                    row = c.execute(f"SELECT * FROM {table} WHERE {key}=%s", (body[key],)).fetchone()
                else:
                    cols = [key] + ks
                    row = c.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING *", [body[k] for k in cols]).fetchone()
            except (psycopg.errors.NotNullViolation, psycopg.errors.ForeignKeyViolation, psycopg.errors.CheckViolation) as e:
                raise HTTPException(422, str(e).splitlines()[0])
            c.commit()
            return _json(row)

    @r.delete("/master/{table}/{code}", status_code=204)
    def master_delete(table: str, code: str):
        if table not in MASTERS:
            raise HTTPException(404, "unknown master")
        with _conn() as c:
            if c.execute(f"UPDATE {table} SET active_flag=false WHERE {MASTERS[table][0]}=%s", (code,)).rowcount == 0:
                raise HTTPException(404, "not found")
            c.commit()

    # ---------- shipments ----------
    @r.get("/shipments")
    def shipments(date_: date | None = Query(None, alias="date"), limit: int = 500):
        with _conn() as c:
            q = """SELECT sh.shipment_id, sh.source_ref, sh.order_ref, sh.kind, pl.location_code AS pickup_location_code, pl.postal_code AS pickup_postal_code, sh.requested_date, sh.window_start, sh.window_end, sh.service_s, sh.weight_kg, sh.volume_m3,
                          sh.pieces, sh.priority, sh.optional_flag, l.location_code, l.address_line, l.city, l.postal_code, l.latitude, l.longitude, cu.customer_code, cu.name AS customer_name
                   FROM shipment sh JOIN location l ON l.location_id=sh.delivery_location_id LEFT JOIN customer cu ON cu.customer_id=sh.customer_id
                   LEFT JOIN location pl ON pl.location_id=sh.pickup_location_id WHERE sh.active_flag"""
            args: list = []
            if date_:
                q += " AND sh.requested_date=%s"
                args.append(date_)
            return _json(c.execute(q + " ORDER BY sh.requested_date, sh.shipment_id LIMIT %s", args + [limit]).fetchall())

    @r.get("/shipments/dates")
    def shipment_dates():
        with _conn() as c:
            return _json(c.execute("SELECT requested_date, count(*) AS n FROM shipment WHERE active_flag GROUP BY 1 ORDER BY 1").fetchall())

    @r.post("/shipments/upload", status_code=201)
    async def shipments_upload(file: UploadFile = File(...), system: str = Form("XLSX")):
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(400, "xlsx required")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(await file.read())
        try:
            with _conn(plain=True) as c:   # ETL unpacks rows positionally
                c.execute(SEED.parent.joinpath("003_mapping_xlsx.sql").read_text())
                rep = run_etl(c, system, load_rows_xlsx(tmp.name))
                return {"rows": rep.rows, "shipments": rep.shipments, "locations": rep.locations, "customers": rep.customers, "skipped": dict(rep.skipped)}
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    @r.post("/shipments/refresh", status_code=202)
    def shipments_refresh(hub: str = "LPHB-30260", crt_by: str | None = "demo"):
        from tmod.product.etl import load_rows_by

        def job():
            with _conn(plain=True) as c:
                rep = run_etl(c, "BLUE_YONDER", load_rows_by(hub, None if crt_by in (None, "all") else crt_by))
                return {"rows": rep.rows, "shipments": rep.shipments, "skipped": dict(rep.skipped)}
        return {"job_id": jobs.submit(job)}

    # ---------- scenarios ----------
    def _scenario(c, code: str) -> dict:
        s = c.execute("SELECT s.*, d.depot_code FROM scenario s JOIN depot d USING (depot_id) WHERE s.scenario_code=%s", (code,)).fetchone()
        if not s:
            raise HTTPException(404, "scenario not found")
        sid = s["scenario_id"]
        s["constraints"] = c.execute("""SELECT c.constraint_code, c.name, c.ctype, c.phase, c.param_schema, COALESCE(sc.enabled_flag,false) AS enabled, COALESCE(sc.params, c.default_params) AS params
                                        FROM constraint_def c LEFT JOIN scenario_constraint sc ON sc.constraint_code=c.constraint_code AND sc.scenario_id=%s WHERE c.active_flag ORDER BY c.phase, c.constraint_code""", (sid,)).fetchall()
        s["weights"] = c.execute("SELECT o.objective_code, o.name, o.unit, COALESCE(w.weight_pct,0) AS weight_pct FROM objective_def o LEFT JOIN scenario_objective_weight w ON w.objective_code=o.objective_code AND w.scenario_id=%s ORDER BY o.phase, o.objective_code", (sid,)).fetchall()
        s["vehicles"] = [v["vehicle_code"] for v in c.execute("SELECT v.vehicle_code FROM scenario_vehicle sv JOIN vehicle v USING (vehicle_id) WHERE sv.scenario_id=%s ORDER BY 1", (sid,)).fetchall()]
        s["shipment_count"] = c.execute("SELECT count(*) AS n FROM scenario_shipment WHERE scenario_id=%s", (sid,)).fetchone()["n"]
        s["adjustments"] = c.execute("""SELECT a.adjustment_id, g.segment_code, g.road_name, a.day_of_week, a.time_from, a.time_to, a.factor, a.reason, COALESCE(sa.enabled_flag,false) AS enabled
                                        FROM road_adjustment a JOIN road_segment g USING (segment_id) LEFT JOIN scenario_road_adjustment sa ON sa.adjustment_id=a.adjustment_id AND sa.scenario_id=%s
                                        WHERE a.active_flag ORDER BY g.road_name, a.day_of_week""", (sid,)).fetchall()
        s["runs"] = c.execute("SELECT optimization_run_id, solver_status, vehicle_count, total_distance_m, total_route_s, total_cost, created_at FROM optimization_run WHERE scenario_id=%s ORDER BY 1 DESC", (sid,)).fetchall()
        return _json(s)

    @r.get("/scenarios")
    def scenarios():
        with _conn() as c:
            return _json(c.execute("""SELECT s.scenario_id, s.scenario_code, s.name, s.plan_date, s.status, s.distance_provider, d.depot_code, s.created_at,
                                             (SELECT count(*) FROM scenario_shipment x WHERE x.scenario_id=s.scenario_id) AS shipments,
                                             (SELECT count(*) FROM optimization_run x WHERE x.scenario_id=s.scenario_id) AS runs
                                      FROM scenario s JOIN depot d USING (depot_id) WHERE s.active_flag ORDER BY s.plan_date DESC, s.scenario_code""").fetchall())

    @r.post("/scenarios", status_code=201)
    def scenario_create(body: ScenarioIn):
        with _conn() as c:
            d = c.execute("SELECT depot_id FROM depot WHERE depot_code=%s", (body.depot_code,)).fetchone()
            if not d:
                raise HTTPException(404, "depot not found")
            try:
                sid = c.execute("INSERT INTO scenario (scenario_code, name, description, plan_date, depot_id, distance_provider, time_limit_s) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING scenario_id",
                                (body.code, body.name, body.description, body.plan_date, d["depot_id"], body.provider, body.time_limit_s)).fetchone()["scenario_id"]
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409, "scenario code exists")
            c.execute("INSERT INTO scenario_vehicle (scenario_id, vehicle_id) SELECT %s, vehicle_id FROM vehicle WHERE active_flag AND depot_id=%s", (sid, d["depot_id"]))
            c.execute("INSERT INTO scenario_constraint (scenario_id, constraint_code, enabled_flag, params) SELECT %s, constraint_code, phase=1, default_params FROM constraint_def WHERE active_flag", (sid,))
            c.execute("INSERT INTO scenario_objective_weight VALUES (%s,'COST',50),(%s,'TRAVEL_TIME',30),(%s,'VEHICLE_COUNT',20)", (sid, sid, sid))
            n = populate_scenario(c, sid)
            c.commit()
            out = _scenario(c, body.code)
            out["populated"] = n
            return out

    @r.get("/scenarios/{code}")
    def scenario_get(code: str):
        with _conn() as c:
            return _scenario(c, code)

    @r.put("/scenarios/{code}")
    def scenario_update(code: str, body: ScenarioUpdate):
        with _conn() as c:
            s = c.execute("SELECT scenario_id FROM scenario WHERE scenario_code=%s", (code,)).fetchone()
            if not s:
                raise HTTPException(404, "scenario not found")
            sid = s["scenario_id"]
            for col, val in (("name", body.name), ("time_limit_s", body.time_limit_s), ("distance_provider", body.provider)):
                if val is not None:
                    c.execute(f"UPDATE scenario SET {col}=%s WHERE scenario_id=%s", (val, sid))
            if body.settings is not None:
                c.execute("UPDATE scenario SET settings=%s WHERE scenario_id=%s", (json.dumps(body.settings), sid))
            if body.constraints is not None:
                for cc, spec in body.constraints.items():
                    c.execute("""INSERT INTO scenario_constraint (scenario_id, constraint_code, enabled_flag, params) VALUES (%s,%s,%s,%s)
                                 ON CONFLICT (scenario_id, constraint_code) DO UPDATE SET enabled_flag=EXCLUDED.enabled_flag, params=EXCLUDED.params""",
                              (sid, cc, bool(spec.get("enabled", True)), json.dumps(spec.get("params", {}))))
            if body.weights is not None:
                if abs(sum(body.weights.values()) - 100) > 0.01:
                    raise HTTPException(422, "objective weights must sum to 100")
                c.execute("DELETE FROM scenario_objective_weight WHERE scenario_id=%s", (sid,))
                for oc, w in body.weights.items():
                    c.execute("INSERT INTO scenario_objective_weight VALUES (%s,%s,%s)", (sid, oc, w))
            if body.vehicles is not None:
                c.execute("DELETE FROM scenario_vehicle WHERE scenario_id=%s", (sid,))
                c.execute("INSERT INTO scenario_vehicle (scenario_id, vehicle_id) SELECT %s, vehicle_id FROM vehicle WHERE vehicle_code = ANY(%s)", (sid, body.vehicles))
            c.execute("UPDATE scenario SET status='READY' WHERE scenario_id=%s AND status='DRAFT'", (sid,))
            c.commit()
            return _scenario(c, code)

    @r.post("/scenarios/{code}/copy", status_code=201)
    def scenario_copy(code: str, new_code: str, name: str | None = None):
        with _conn() as c:
            s = c.execute("SELECT * FROM scenario WHERE scenario_code=%s", (code,)).fetchone()
            if not s:
                raise HTTPException(404, "scenario not found")
            try:
                nid = c.execute("""INSERT INTO scenario (scenario_code, name, description, plan_date, depot_id, distance_provider, time_limit_s, copied_from_id, settings)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING scenario_id""",
                                (new_code, name or f"{s['name']} (copy)", s["description"], s["plan_date"], s["depot_id"], s["distance_provider"], s["time_limit_s"], s["scenario_id"], json.dumps(s["settings"]))).fetchone()["scenario_id"]
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409, "scenario code exists")
            sid = s["scenario_id"]
            c.execute("INSERT INTO scenario_shipment SELECT %s, shipment_id, override_window_start, override_window_end, override_service_s, override_priority FROM scenario_shipment WHERE scenario_id=%s", (nid, sid))
            c.execute("INSERT INTO scenario_vehicle SELECT %s, vehicle_id, override_shift_start, override_shift_end, override_capacity_kg FROM scenario_vehicle WHERE scenario_id=%s", (nid, sid))
            c.execute("INSERT INTO scenario_constraint SELECT %s, constraint_code, enabled_flag, params FROM scenario_constraint WHERE scenario_id=%s", (nid, sid))
            c.execute("INSERT INTO scenario_objective_weight SELECT %s, objective_code, weight_pct FROM scenario_objective_weight WHERE scenario_id=%s", (nid, sid))
            c.execute("INSERT INTO scenario_road_adjustment SELECT %s, adjustment_id, enabled_flag FROM scenario_road_adjustment WHERE scenario_id=%s", (nid, sid))
            c.commit()
            return _scenario(c, new_code)

    @r.delete("/scenarios/{code}", status_code=204)
    def scenario_delete(code: str):
        with _conn() as c:
            if c.execute("UPDATE scenario SET active_flag=false, status='ARCHIVED' WHERE scenario_code=%s", (code,)).rowcount == 0:
                raise HTTPException(404, "scenario not found")
            c.commit()

    @r.post("/scenarios/{code}/populate")
    def scenario_populate(code: str):
        with _conn() as c:
            s = c.execute("SELECT scenario_id FROM scenario WHERE scenario_code=%s", (code,)).fetchone()
            if not s:
                raise HTTPException(404, "scenario not found")
            return {"added": populate_scenario(c, s["scenario_id"])}

    @r.post("/scenarios/{code}/run", status_code=202)
    def scenario_run(code: str, wait: bool = False):
        def job():
            with _conn(plain=True) as c:
                prov = c.execute("SELECT distance_provider FROM scenario WHERE scenario_code=%s", (code,)).fetchone()
                if not prov:
                    raise ValueError("scenario not found")
                res = run_scenario(c, code, PROVIDERS.get(prov[0], lambda: None)())
                return res.__dict__
        if wait:
            return {"status": "done", "result": _json(job())}
        return {"job_id": jobs.submit(job), "status": "queued"}

    @r.post("/scenarios/{code}/adjustments/{adjustment_id}")
    def scenario_adjustment(code: str, adjustment_id: int, enabled: bool = True):
        with _conn() as c:
            s = c.execute("SELECT scenario_id FROM scenario WHERE scenario_code=%s", (code,)).fetchone()
            if not s:
                raise HTTPException(404, "scenario not found")
            c.execute("INSERT INTO scenario_road_adjustment (scenario_id, adjustment_id, enabled_flag) VALUES (%s,%s,%s) ON CONFLICT (scenario_id, adjustment_id) DO UPDATE SET enabled_flag=EXCLUDED.enabled_flag", (s["scenario_id"], adjustment_id, enabled))
            c.commit()
            return {"adjustment_id": adjustment_id, "enabled": enabled}

    # ---------- results ----------
    def _run(c, run_id: int, detail: bool = False) -> dict:
        run = c.execute("SELECT r.*, s.scenario_code, s.plan_date, s.distance_provider FROM optimization_run r JOIN scenario s USING (scenario_id) WHERE optimization_run_id=%s", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "run not found")
        rows = c.execute("""SELECT x.vehicle_id, v.vehicle_code, x.route_sequence, x.stop_location_id, l.location_code, l.address_line, l.postal_code, l.latitude, l.longitude, x.shipment_id, sh.source_ref,
                                   x.arrival_time, x.departure_time, x.wait_s, x.service_s, x.distance_from_previous_m, x.travel_time_from_previous_s, x.late_s, x.stop_kind, x.load_after_kg
                            FROM optimization_route x JOIN vehicle v USING (vehicle_id) JOIN location l ON l.location_id=x.stop_location_id LEFT JOIN shipment sh ON sh.shipment_id=x.shipment_id
                            WHERE x.optimization_run_id=%s ORDER BY v.vehicle_code, x.route_sequence""", (run_id,)).fetchall()
        prof = {"OSRM": "driving", "VALHALLA": "truck", "MANUAL": "test"}.get(run["distance_provider"], "driving")
        routes: dict[str, dict] = {}
        for x in rows:
            v = routes.setdefault(x["vehicle_code"], {"vehicle_code": x["vehicle_code"], "stops": [], "distance_m": 0, "shipments": 0})
            v["stops"].append(x)
            v["distance_m"] += x["distance_from_previous_m"]
            v["shipments"] += x["shipment_id"] is not None
        prov = PROVIDERS.get(run["distance_provider"], lambda: None)() if detail else None
        plain = _conn(plain=True) if prov else None
        try:
            for v in routes.values():
                legs = []
                for a, b in zip(v["stops"], v["stops"][1:]):
                    fa, tb = a["stop_location_id"], b["stop_location_id"]
                    if fa == tb:
                        continue
                    g = c.execute("SELECT geometry FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s AND provider=%s AND profile=%s AND geometry IS NOT NULL",
                                  (fa, tb, run["distance_provider"], prof)).fetchone()
                    geom = g["geometry"] if g else None
                    if geom is None and prov is not None:
                        try:
                            rd = route_detail(plain, prov, fa, tb)   # cached for next time; registers road segments
                            geom = [list(pt) for pt in rd.geometry] if rd else None
                        except Exception:  # noqa: BLE001 — provider down: straight line on the map
                            geom = None
                    legs.append({"from": fa, "to": tb, "geometry": geom})
                v["legs"] = legs
        finally:
            if plain:
                plain.close()
        run["routes"] = list(routes.values())
        run["unassigned"] = c.execute("SELECT u.shipment_id, sh.source_ref, u.reason, u.penalty_applied FROM optimization_unassigned u JOIN shipment sh USING (shipment_id) WHERE optimization_run_id=%s", (run_id,)).fetchall()
        return _json(run)

    @r.get("/runs/{run_id}")
    def run_get(run_id: int, detail: bool = False):
        with _conn() as c:
            return _run(c, run_id, detail)

    @r.get("/compare")
    def compare(a: int, b: int):
        with _conn() as c:
            ra, rb = _run(c, a), _run(c, b)
        keys = ("vehicle_count", "total_distance_m", "total_drive_s", "total_service_s", "total_route_s", "total_cost")
        delta = {k: (None if ra.get(k) is None or rb.get(k) is None else float(rb[k]) - float(ra[k])) for k in keys}
        delta["unassigned"] = len(rb["unassigned"]) - len(ra["unassigned"])
        return {"a": {k: ra.get(k) for k in keys + ("scenario_code", "solver_status")} | {"unassigned": len(ra["unassigned"])},
                "b": {k: rb.get(k) for k in keys + ("scenario_code", "solver_status")} | {"unassigned": len(rb["unassigned"])}, "delta": delta}

    # ---------- road segments ----------
    @r.get("/segments")
    def segments(q: str = "", limit: int = 50):
        with _conn() as c:
            return _json(c.execute("SELECT segment_id, segment_code, road_name, osm_way_id, length_m, geometry FROM road_segment WHERE road_name ILIKE %s ORDER BY road_name LIMIT %s", (f"%{q}%", limit)).fetchall())

    @r.get("/segments/near")
    def segments_near(lat: float, lon: float, limit: int = 5):
        with _conn() as c:
            rows = c.execute("SELECT segment_id, segment_code, road_name, osm_way_id, length_m, geometry FROM road_segment WHERE geometry IS NOT NULL").fetchall()
        def d2(g):
            return min((p[0] - lat) ** 2 + (p[1] - lon) ** 2 for p in g) if g else 9e9
        rows.sort(key=lambda s: d2(s["geometry"]))
        return _json(rows[:limit])

    @r.post("/segments/{code}/adjustments", status_code=201)
    def adjustment_create(code: str, body: AdjustmentIn):
        with _conn() as c:
            s = c.execute("SELECT segment_id FROM road_segment WHERE segment_code=%s", (code,)).fetchone()
            if not s:
                raise HTTPException(404, "segment not found")
            row = c.execute("INSERT INTO road_adjustment (segment_id, day_of_week, time_from, time_to, factor, reason) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                            (s["segment_id"], body.day_of_week, body.time_from, body.time_to, body.factor, body.reason)).fetchone()
            c.commit()
            return _json(row)

    @r.get("/adjustments")
    def adjustments():
        with _conn() as c:
            return _json(c.execute("SELECT a.*, g.segment_code, g.road_name FROM road_adjustment a JOIN road_segment g USING (segment_id) WHERE a.active_flag ORDER BY g.road_name, a.day_of_week, a.time_from").fetchall())

    @r.delete("/adjustments/{adjustment_id}", status_code=204)
    def adjustment_delete(adjustment_id: int):
        with _conn() as c:
            if c.execute("UPDATE road_adjustment SET active_flag=false WHERE adjustment_id=%s", (adjustment_id,)).rowcount == 0:
                raise HTTPException(404, "not found")
            c.commit()

    @r.get("/jobs/{job_id}")
    def job(job_id: str):
        j = jobs.jobs.get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    return r
