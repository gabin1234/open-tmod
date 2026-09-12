"""P04: load scenario from DB and build the data the solver needs. Contract: docs/nodes/p04_model.md"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Sequence
from zoneinfo import ZoneInfo

import psycopg

from tmod.product.routing import RoadProvider, adjusted_duration, fill_distance_cache

PROFILE = {"OSRM": "driving", "VALHALLA": "truck", "MANUAL": "test", "HAVERSINE": "car", "PCMILER": "truck"}


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: int
    code: str
    capacity_kg: float | None
    capacity_m3: float | None
    max_stops: int | None
    max_route_s: int | None
    max_distance_m: int | None
    work_limit_s: int | None
    duty_limit_s: int | None
    shift_start_s: int
    shift_end_s: int
    fixed_cost: float
    cost_per_km: float
    cost_per_hour: float
    vehicle_type_id: int
    depot_location_id: int | None = None


@dataclass(frozen=True)
class Stop:
    location_id: int
    shipment_ids: tuple[int, ...]
    weight_kg: float
    volume_m3: float
    service_s: int
    window_start_s: int | None
    window_end_s: int | None
    optional: bool
    drop_penalty: float | None
    priority: int
    customer_ids: tuple[int, ...]
    forbidden_vehicles: frozenset[int] = frozenset()
    kind: str = "DELIVERY"          # DELIVERY | PICKUP | PICKUP_DELIVERY_P | PICKUP_DELIVERY_D
    pair: int | None = None         # shipment_id linking the P and D nodes of one PICKUP_DELIVERY shipment
    demand_sign: int = 1            # +1 loads the vehicle at this stop, -1 unloads


@dataclass
class ScenarioData:
    scenario_id: int
    code: str
    plan_date: date
    tz: ZoneInfo
    depot_location_id: int
    provider_code: str
    profile: str
    time_limit_s: int
    vehicles: list[Vehicle]
    stops: list[Stop]
    constraints: dict[str, dict]          # enabled code -> params
    weights: dict[str, float]             # objective_code -> fraction
    unsupported: list[tuple[int, str]] = field(default_factory=list)   # (shipment_id, reason)
    settings: dict = field(default_factory=dict)

    @property
    def multi_depot(self) -> bool:
        return bool(self.settings.get("multi_depot"))

    @property
    def depot_locations(self) -> list[int]:
        """Depot nodes: scenario depot, plus each vehicle's own depot when multi_depot."""
        if not self.multi_depot:
            return [self.depot_location_id]
        return list(dict.fromkeys([self.depot_location_id] + [v.depot_location_id or self.depot_location_id for v in self.vehicles]))

    def vehicle_depot_node(self, v: Vehicle) -> int:
        return self.depot_locations.index(v.depot_location_id or self.depot_location_id) if self.multi_depot else 0

    @property
    def locations(self) -> list[int]:
        return self.depot_locations + [s.location_id for s in self.stops]


def _secs(t: time | None, default: int) -> int:
    return default if t is None else t.hour * 3600 + t.minute * 60 + t.second


def populate_scenario(con: psycopg.Connection, scenario_id: int) -> int:
    n = con.execute("""INSERT INTO scenario_shipment (scenario_id, shipment_id)
                       SELECT s.scenario_id, sh.shipment_id FROM scenario s JOIN shipment sh ON sh.requested_date = s.plan_date AND sh.active_flag
                       WHERE s.scenario_id=%s ON CONFLICT DO NOTHING""", (scenario_id,)).rowcount
    con.commit()
    return n


def load_scenario(con: psycopg.Connection, scenario_code: str) -> ScenarioData:
    sc = con.execute("""SELECT s.scenario_id, s.plan_date, d.location_id, s.distance_provider, s.time_limit_s, s.settings, d.open_time, d.close_time
                        FROM scenario s JOIN depot d ON d.depot_id=s.depot_id WHERE s.scenario_code=%s""", (scenario_code,)).fetchone()
    if not sc:
        raise ValueError(f"scenario not found: {scenario_code}")
    sid, plan_date, depot_loc, prov, tl, settings, d_open, d_close = sc
    tz = ZoneInfo((settings or {}).get("timezone", "America/New_York"))
    dow = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[plan_date.weekday()]

    vehicles = []
    for r in con.execute("""SELECT v.vehicle_id, v.vehicle_code, COALESCE(sv.override_capacity_kg, t.capacity_kg), t.capacity_m3, t.max_stops, t.max_route_s, t.max_distance_m,
                                   v.work_limit_s, v.duty_limit_s, COALESCE(sv.override_shift_start, a.shift_start), COALESCE(sv.override_shift_end, a.shift_end),
                                   t.fixed_cost, t.cost_per_km, t.cost_per_hour, t.vehicle_type_id, vd.location_id
                            FROM scenario_vehicle sv JOIN vehicle v ON v.vehicle_id=sv.vehicle_id JOIN vehicle_type t ON t.vehicle_type_id=v.vehicle_type_id
                            JOIN depot vd ON vd.depot_id=v.depot_id
                            LEFT JOIN LATERAL (SELECT shift_start, shift_end FROM vehicle_availability a WHERE a.vehicle_id=v.vehicle_id AND a.active_flag
                                               AND (a.day_of_week IS NULL OR a.day_of_week=%s::day_of_week) ORDER BY a.day_of_week NULLS LAST LIMIT 1) a ON true
                            WHERE sv.scenario_id=%s AND v.active_flag ORDER BY v.vehicle_code""", (dow, sid)).fetchall():
        vehicles.append(Vehicle(r[0], r[1], float(r[2]) if r[2] is not None else None, float(r[3]) if r[3] is not None else None, r[4], r[5], r[6], r[7], r[8],
                                _secs(r[9], _secs(d_open, 8 * 3600)), _secs(r[10], _secs(d_close, 18 * 3600)), float(r[11]), float(r[12]), float(r[13]), r[14], r[15]))

    constraints = {c: (p or {}) for c, p in con.execute("SELECT constraint_code, params FROM scenario_constraint WHERE scenario_id=%s AND enabled_flag", (sid,)).fetchall()}
    weights = {c: float(w) / 100 for c, w in con.execute("SELECT objective_code, weight_pct FROM scenario_objective_weight WHERE scenario_id=%s", (sid,)).fetchall()}
    base_rule = con.execute("SELECT stop_base_s, per_unit_s FROM service_time_rule WHERE active_flag AND customer_type IS NULL AND product_category IS NULL ORDER BY priority LIMIT 1").fetchone() or (0, 0)

    # restrictions: forbidden (vehicle or vehicle_type) per customer/location
    forbid = con.execute("""SELECT r.vehicle_id, r.vehicle_type_id, r.customer_id, r.location_id FROM vehicle_restriction r
                            WHERE r.active_flag AND NOT r.allow_flag AND r.effective_from <= %s AND (r.effective_to IS NULL OR r.effective_to >= %s)""", (plan_date, plan_date)).fetchall()
    type_vehicles: dict[int, set[int]] = {}
    for v in vehicles:
        type_vehicles.setdefault(v.vehicle_type_id, set()).add(v.vehicle_id)

    groups: dict[tuple, dict] = {}
    unsupported: list[tuple[int, str]] = []
    midnight = datetime.combine(plan_date, time(0), tzinfo=tz)
    pnd: list[Stop] = []
    for r in con.execute("""SELECT sh.shipment_id, sh.kind, sh.delivery_location_id, sh.customer_id, sh.weight_kg, sh.volume_m3, sh.pieces,
                                   COALESCE(ss.override_service_s, sh.service_s), COALESCE(ss.override_window_start, sh.window_start), COALESCE(ss.override_window_end, sh.window_end),
                                   sh.optional_flag, sh.drop_penalty, COALESCE(ss.override_priority, sh.priority, 5), l.latitude, sh.pickup_location_id, pl.latitude
                            FROM scenario_shipment ss JOIN shipment sh ON sh.shipment_id=ss.shipment_id JOIN location l ON l.location_id=sh.delivery_location_id
                            LEFT JOIN location pl ON pl.location_id=sh.pickup_location_id
                            WHERE ss.scenario_id=%s AND sh.active_flag ORDER BY sh.shipment_id""", (sid,)).fetchall():
        shid, kind, loc, cust, wkg, vm3, pieces, svc, ws, we, opt, pen, prio, lat, ploc, plat = r
        if lat is None:
            unsupported.append((shid, "NO_COORDINATES"))
            continue
        ws_s = int((ws.astimezone(tz) - midnight).total_seconds()) if ws else None
        we_s = int((we.astimezone(tz) - midnight).total_seconds()) if we else None
        if kind in ("PICKUP", "PICKUP_DELIVERY"):
            service = int(base_rule[0]) + (int(svc) if svc is not None else int(base_rule[1]) * int(pieces or 1))
            common = dict(shipment_ids=(shid,), weight_kg=float(wkg or 0), volume_m3=float(vm3 or 0), service_s=service, optional=bool(opt),
                          drop_penalty=float(pen) if pen else None, priority=int(prio), customer_ids=(cust,) if cust else ())
            if kind == "PICKUP":
                pnd.append(Stop(location_id=loc, window_start_s=ws_s, window_end_s=we_s, kind="PICKUP", demand_sign=1, **common))
            else:
                if ploc is None or plat is None:
                    unsupported.append((shid, "NO_PICKUP_LOCATION"))
                    continue
                pnd.append(Stop(location_id=ploc, window_start_s=None, window_end_s=None, kind="PICKUP_DELIVERY_P", pair=shid, demand_sign=1, **common))
                pnd.append(Stop(location_id=loc, window_start_s=ws_s, window_end_s=we_s, kind="PICKUP_DELIVERY_D", pair=shid, demand_sign=-1, **common))
            continue
        g = groups.setdefault((loc, ws_s, we_s), {"ids": [], "w": 0.0, "v": 0.0, "svc": 0, "opt": True, "pen": 0.0, "prio": 99, "cust": set(), "pieces": 0, "explicit": 0})
        g["ids"].append(shid)
        g["w"] += float(wkg or 0)
        g["v"] += float(vm3 or 0)
        g["pieces"] += int(pieces or 1)
        if svc is not None:
            g["svc"] += int(svc)
            g["explicit"] += 1
        g["opt"] = g["opt"] and bool(opt)
        g["pen"] += float(pen or 0)
        g["prio"] = min(g["prio"], int(prio))
        if cust:
            g["cust"].add(cust)

    stops = []
    for (loc, ws_s, we_s), g in groups.items():
        service = int(base_rule[0]) + g["svc"] + (0 if g["explicit"] else int(base_rule[1]) * g["pieces"])
        fv: set[int] = set()
        for vid, vtid, cid, lid in forbid:
            if (cid and cid in g["cust"]) or (lid and lid == loc):
                if vid:
                    fv.add(vid)
                if vtid:
                    fv |= type_vehicles.get(vtid, set())
        stops.append(Stop(loc, tuple(g["ids"]), g["w"], g["v"], service, ws_s, we_s, g["opt"], g["pen"] or None, g["prio"], tuple(g["cust"]), frozenset(fv)))
    for s in pnd:   # restrictions for P&D nodes (same rule as grouped stops)
        fv = set()
        for vid, vtid, cid, lid in forbid:
            if (cid and cid in s.customer_ids) or (lid and lid == s.location_id):
                if vid:
                    fv.add(vid)
                if vtid:
                    fv |= type_vehicles.get(vtid, set())
        stops.append(Stop(**{**s.__dict__, "forbidden_vehicles": frozenset(fv)}))
    return ScenarioData(sid, scenario_code, plan_date, tz, depot_loc, prov, PROFILE.get(prov, "driving"), tl, vehicles, stops, constraints, weights, unsupported, settings or {})


def matrices(con: psycopg.Connection, data: ScenarioData, provider: RoadProvider | None = None) -> tuple[list[list[int]], list[list[int]]]:
    """(distance_m, duration_s) over data.locations from distance_cache; fills missing pairs via provider; applies road adjustments."""
    locs = data.locations
    rows = con.execute("SELECT from_location_id, to_location_id, distance_m, duration_s FROM distance_cache WHERE provider=%s AND profile=%s AND from_location_id = ANY(%s) AND to_location_id = ANY(%s)",
                       (data.provider_code, data.profile, locs, locs)).fetchall()
    have = {(a, b): (d, t) for a, b, d, t in rows}
    missing = {(a, b) for a in locs for b in locs if a != b and (a, b) not in have}
    if missing:
        if provider is None:
            raise ValueError(f"{len(missing)} location pairs missing in distance_cache for {data.provider_code}/{data.profile}; pass a provider to fill")
        fill_distance_cache(con, provider, locs)
        rows = con.execute("SELECT from_location_id, to_location_id, distance_m, duration_s FROM distance_cache WHERE provider=%s AND profile=%s AND from_location_id = ANY(%s) AND to_location_id = ANY(%s)",
                           (data.provider_code, data.profile, locs, locs)).fetchall()
        have = {(a, b): (d, t) for a, b, d, t in rows}
    adjust = "ROAD_ADJUSTMENT" in data.constraints
    depart = min((v.shift_start_s for v in data.vehicles), default=8 * 3600)
    n = len(locs)
    dist = [[0] * n for _ in range(n)]
    dur = [[0] * n for _ in range(n)]
    for i, a in enumerate(locs):
        for j, b in enumerate(locs):
            if i == j or a == b:      # same node, or two stops at one location (different windows)
                continue
            d, t = have.get((a, b), (None, None))
            if d is None:
                raise ValueError(f"no distance for {a}->{b}")
            if adjust:
                t = adjusted_duration(con, a, b, data.provider_code, data.profile, data.plan_date, depart, data.scenario_id) or t
            dist[i][j], dur[i][j] = int(d), int(t)
    return dist, dur
