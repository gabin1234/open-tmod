import json
from datetime import date

import pytest

from tmod.product.db import init
from tmod.product.routing import adjusted_duration, fill_distance_cache
from tmod.product.solve import run_scenario


class Grid:
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


def _db(pg):
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    _OPEN.append(con)
    con.execute("SET search_path TO tmod")
    con.execute("UPDATE scenario SET distance_provider='MANUAL', time_limit_s=2, plan_date='2026-09-14'")   # Monday
    con.execute("UPDATE scenario_constraint SET enabled_flag=false WHERE constraint_code='TIME_WINDOW'")
    con.execute("UPDATE vehicle_type SET max_stops=NULL")
    con.execute("UPDATE location SET latitude=33.50, longitude=-84.30 WHERE location_code='HUB-LPHB-30260'")
    con.execute("DELETE FROM scenario_vehicle WHERE vehicle_id NOT IN (SELECT vehicle_id FROM vehicle ORDER BY vehicle_code LIMIT 1)")
    ss = con.execute("SELECT source_system_id FROM source_system WHERE system_code='XLSX'").fetchone()[0]
    hub = con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]
    locs = [con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", 33.50 + 0.2 * (i + 1), -84.30)).fetchone()[0] for i in range(3)]
    con.commit()
    fill_distance_cache(con, Grid(), [hub] + locs)
    return con, ss, hub, locs


def test_profile_factor_by_departure(pg):
    con, ss, hub, locs = _db(pg)
    mon = date(2026, 9, 14)
    base = con.execute("SELECT duration_s FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s", (hub, locs[0])).fetchone()[0]
    assert adjusted_duration(con, hub, locs[0], "MANUAL", "test", mon, 8 * 3600) == round(base * 1.35)
    assert adjusted_duration(con, hub, locs[0], "MANUAL", "test", mon, 10 * 3600) == base
    assert adjusted_duration(con, hub, locs[0], "MANUAL", "test", date(2026, 9, 13), 8 * 3600) == base   # Sunday
    con.close()


def test_dynamic_traffic_iterates_and_retimes_legs(pg):
    con, ss, hub, locs = _db(pg)
    for i, l in enumerate(locs):
        con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,%s,%s,'2026-09-14',1800,10)", (ss, f"S{i}", l))
    con.execute("INSERT INTO scenario_shipment (scenario_id, shipment_id) SELECT (SELECT scenario_id FROM scenario), shipment_id FROM shipment")
    con.execute("INSERT INTO scenario_constraint (scenario_id, constraint_code, enabled_flag, params) SELECT scenario_id, 'DYNAMIC_TRAFFIC', true, '{\"iterations\": 3}' FROM scenario")
    con.commit()
    res = run_scenario(con, "SC-2026-09-14-BASE" if False else "SC-2026-09-15-BASE")
    assert res.status in ("OPTIMAL", "FEASIBLE") and res.unassigned == 0
    it = con.execute("SELECT engine_params->>'iterations_used' FROM optimization_run WHERE optimization_run_id=%s", (res.run_id,)).fetchone()[0]
    assert int(it) >= 2
    rows = con.execute("SELECT route_sequence, stop_location_id, travel_time_from_previous_s, departure_time AT TIME ZONE 'America/New_York' FROM optimization_route WHERE optimization_run_id=%s ORDER BY 1", (res.run_id,)).fetchall()
    # first leg departs 08:00 (peak) -> factor 1.35 on base 20 km = 2000 s
    first = rows[1]
    base = con.execute("SELECT duration_s FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s", (hub, first[1])).fetchone()[0]
    assert first[2] == round(base * 1.35)
    # a later leg departing after 09:00 uses the un-factored duration
    later = [r for r in rows[2:] if r[3].hour >= 9]
    assert later and all(r[2] in (con.execute("SELECT duration_s FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s", (rows[k][1], r[1])).fetchone()[0],) for k, r in [(rows.index(r) - 1, r) for r in later])
    con.close()


def test_priority_keeps_high_priority_optional(pg):
    con, ss, hub, locs = _db(pg)
    con.execute("UPDATE vehicle_type SET capacity_kg=100")
    con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg, optional_flag, drop_penalty, priority) VALUES (%s,'LOW',%s,'2026-09-14',60,100,true,1000,5)", (ss, locs[0]))
    con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg, optional_flag, drop_penalty, priority) VALUES (%s,'HIGH',%s,'2026-09-14',60,100,true,1000,1)", (ss, locs[2]))
    con.execute("INSERT INTO scenario_shipment (scenario_id, shipment_id) SELECT (SELECT scenario_id FROM scenario), shipment_id FROM shipment")
    con.execute("UPDATE scenario_constraint SET enabled_flag=true WHERE constraint_code='OPTIONAL_DROP'")
    con.commit()
    res = run_scenario(con, "SC-2026-09-15-BASE")
    un = con.execute("SELECT s.source_ref FROM optimization_unassigned u JOIN shipment s USING (shipment_id) WHERE optimization_run_id=%s", (res.run_id,)).fetchall()
    assert un == [("LOW",)]   # HIGH is farther (costlier) but its drop penalty is x3
    con.close()
