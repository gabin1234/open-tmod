from datetime import datetime, timezone

import pytest

from tmod.product.db import init
from tmod.product.model import load_scenario, populate_scenario
from tmod.product.routing import fill_distance_cache
from tmod.product.solve import run_scenario


class Grid:
    """Manhattan-ish provider on (lat, lon) in 0.01deg units: 1 unit = 1000 m = 100 s."""
    code, profile = "MANUAL", "test"

    def matrix(self, coords):
        d = [[abs(a[0] - b[0]) * 100000 + abs(a[1] - b[1]) * 100000 for b in coords] for a in coords]
        return d, [[x / 10 for x in row] for row in d]

    def route(self, a, b):
        return None


_OPEN: list = []


@pytest.fixture(autouse=True)
def _close_all():
    yield
    for c in _OPEN:
        try:
            c.rollback(); c.close()
        except Exception:  # noqa: BLE001
            pass
    _OPEN.clear()


def _db(pg, n_vehicles=2, cap_kg=1000, window=True):
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    _OPEN.append(con)
    con.execute("SET search_path TO tmod")
    con.execute("UPDATE scenario SET distance_provider='MANUAL', time_limit_s=2, plan_date='2026-09-15'")
    con.execute("UPDATE vehicle_type SET capacity_lb=%s, max_stops=NULL", (cap_kg,))
    con.execute("DELETE FROM scenario_vehicle WHERE vehicle_id NOT IN (SELECT vehicle_id FROM vehicle ORDER BY vehicle_code LIMIT %s)", (n_vehicles,))
    con.execute("UPDATE location SET latitude=33.50, longitude=-84.30 WHERE location_code='HUB-LPHB-30260'")
    ss = con.execute("SELECT source_system_id FROM source_system WHERE system_code='XLSX'").fetchone()[0]
    locs = {}
    for i, (la, lo) in enumerate([(33.51, -84.30), (33.52, -84.30), (33.50, -84.29)]):
        locs[i] = con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", la, lo)).fetchone()[0]
    ws, we = (datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc), datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)) if window else (None, None)  # 08:00-12:00 New York
    for i in range(6):
        con.execute("""INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, window_start, window_end, service_s, weight_lb, pieces)
                       VALUES (%s,%s,%s,'2026-09-15',%s,%s,%s,%s,1)""", (ss, f"S{i}", locs[i % 3], ws, we, 600, 300))
    con.commit()
    sid = con.execute("SELECT scenario_id FROM scenario").fetchone()[0]
    assert populate_scenario(con, sid) == 6
    loc_ids = [con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]] + list(locs.values())
    fill_distance_cache(con, Grid(), loc_ids)
    return con, sid, locs


def _routes(con, run_id):
    return con.execute("SELECT vehicle_id, route_sequence, shipment_id, arrival_time, service_s, distance_from_previous_mi, late_s FROM optimization_route WHERE optimization_run_id=%s ORDER BY vehicle_id, route_sequence", (run_id,)).fetchall()


def test_solve_basic_capacity_window(pg):
    con, sid, locs = _db(pg, n_vehicles=3, cap_kg=1000)   # 6 x 300kg = 1800 -> >= 2 vehicles
    data = load_scenario(con, "SC-2026-09-15-BASE")
    assert len(data.stops) == 3 and all(s.service_s == 20 * 60 + 2 * 600 for s in data.stops) and data.stops[0].window_start_s == 8 * 3600
    res = run_scenario(con, "SC-2026-09-15-BASE")
    assert res.status in ("OPTIMAL", "FEASIBLE") and res.unassigned == 0 and res.vehicles >= 2
    rows = _routes(con, res.run_id)
    shipped = [r[2] for r in rows if r[2] is not None]
    assert len(shipped) == 6 and len(set(shipped)) == 6
    per_vehicle = {}
    for r in rows:
        if r[2]:
            per_vehicle[r[0]] = per_vehicle.get(r[0], 0) + 300
    assert all(v <= 1000 for v in per_vehicle.values())
    assert all(r[6] == 0 for r in rows) and all(r[3].astimezone(data.tz).hour >= 8 for r in rows)
    run = con.execute("SELECT solver_status, vehicle_count, total_distance_mi, total_route_s, total_cost, total_service_s FROM optimization_run WHERE optimization_run_id=%s", (res.run_id,)).fetchone()
    assert run[1] == res.vehicles and abs(float(run[2]) - float(sum(r[5] for r in rows))) < 0.05 and run[5] == 6 * 600 + 3 * 1200 and run[4] > 0
    assert con.execute("SELECT status FROM scenario").fetchone()[0] == "DONE"
    con.close()


def test_optional_drop_and_compat(pg):
    con, sid, locs = _db(pg, n_vehicles=1, cap_kg=1300)   # one truck: max 4 x 300kg
    con.execute("UPDATE shipment SET optional_flag=true, drop_penalty=10 WHERE source_ref IN ('S2','S5')")   # both shipments at L2 -> optional stop
    con.execute("UPDATE scenario_constraint SET enabled_flag=true WHERE constraint_code IN ('OPTIONAL_DROP','VEHICLE_COMPAT')")
    con.commit()
    res = run_scenario(con, "SC-2026-09-15-BASE")
    assert res.status in ("OPTIMAL", "FEASIBLE") and res.unassigned == 2
    un = con.execute("SELECT s.source_ref, u.reason FROM optimization_unassigned u JOIN shipment s USING (shipment_id) WHERE optimization_run_id=%s ORDER BY 1", (res.run_id,)).fetchall()
    assert un == [("S2", "DROPPED_OPTIONAL"), ("S5", "DROPPED_OPTIONAL")]
    # compat: forbid T01 (the only vehicle) at location L2 -> its shipments cannot be served -> dropped as infeasible; add T02 allowed
    con.execute("INSERT INTO scenario_vehicle (scenario_id, vehicle_id) SELECT %s, vehicle_id FROM vehicle WHERE vehicle_code='T02'", (sid,))
    v1 = con.execute("SELECT vehicle_id FROM vehicle WHERE vehicle_code='T01'").fetchone()[0]
    con.execute("INSERT INTO vehicle_restriction (vehicle_id, location_id, allow_flag, reason) VALUES (%s,%s,false,'no 26ft')", (v1, locs[2]))
    con.execute("UPDATE shipment SET optional_flag=false")
    con.commit()
    res2 = run_scenario(con, "SC-2026-09-15-BASE")
    rows = _routes(con, res2.run_id)
    at_l2 = {r[0] for r in rows if r[2] in {x[0] for x in con.execute("SELECT shipment_id FROM shipment WHERE delivery_location_id=%s", (locs[2],)).fetchall()}}
    assert at_l2 and v1 not in at_l2 and res2.unassigned == 0
    con.close()


def test_objective_weights_change_vehicle_count(pg):
    con, sid, locs = _db(pg, n_vehicles=3, cap_kg=5000, window=False)
    con.execute("UPDATE scenario_objective_weight SET weight_pct = CASE objective_code WHEN 'VEHICLE_COUNT' THEN 100 ELSE 0 END")
    con.commit()
    few = run_scenario(con, "SC-2026-09-15-BASE").vehicles
    con.execute("DELETE FROM scenario_objective_weight"); con.execute("INSERT INTO scenario_objective_weight VALUES (%s,'DISTANCE',100)", (sid,))
    con.execute("UPDATE vehicle_type SET fixed_cost=0"); con.commit()
    many = run_scenario(con, "SC-2026-09-15-BASE").vehicles
    assert few == 1 and many >= few
    con.close()
