import json

import pytest

from tmod.product.db import init
from tmod.product.routing import fill_distance_cache
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


def _db(pg, multi: bool):
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    _OPEN.append(con)
    con.execute("SET search_path TO tmod")
    con.execute("UPDATE scenario SET distance_provider='MANUAL', time_limit_s=2, plan_date='2026-09-15', settings=%s", (json.dumps({"multi_depot": multi}),))
    con.execute("UPDATE scenario_constraint SET enabled_flag=false WHERE constraint_code='TIME_WINDOW'")
    con.execute("UPDATE vehicle_type SET capacity_kg=NULL, max_stops=NULL")
    con.execute("UPDATE location SET latitude=33.50, longitude=-84.30 WHERE location_code='HUB-LPHB-30260'")
    l2 = con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES ('HUB-NORTH', 34.50, -84.30) RETURNING location_id").fetchone()[0]
    d2 = con.execute("INSERT INTO depot (depot_code, name, location_id) VALUES ('NORTH', 'North depot', %s) RETURNING depot_id", (l2,)).fetchone()[0]
    con.execute("UPDATE vehicle SET depot_id=%s WHERE vehicle_code='T02'", (d2,))
    con.execute("DELETE FROM scenario_vehicle WHERE vehicle_id NOT IN (SELECT vehicle_id FROM vehicle WHERE vehicle_code IN ('T01','T02'))")
    ss = con.execute("SELECT source_system_id FROM source_system WHERE system_code='XLSX'").fetchone()[0]
    locs = []
    for i, (la, lo) in enumerate([(33.51, -84.30), (33.52, -84.31), (33.50, -84.29), (34.51, -84.30), (34.52, -84.31), (34.50, -84.29)]):
        lid = con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", la, lo)).fetchone()[0]
        locs.append(lid)
        con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,%s,%s,'2026-09-15',600,100)", (ss, f"S{i}", lid))
    con.execute("INSERT INTO scenario_shipment (scenario_id, shipment_id) SELECT (SELECT scenario_id FROM scenario), shipment_id FROM shipment")
    con.commit()
    hub = con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]
    fill_distance_cache(con, Grid(), [hub, l2] + locs)
    return con, hub, l2


def _routes(con, run_id):
    return con.execute("""SELECT v.vehicle_code, x.route_sequence, x.stop_kind, x.stop_location_id, s.source_ref FROM optimization_route x JOIN vehicle v USING (vehicle_id)
                          LEFT JOIN shipment s USING (shipment_id) WHERE optimization_run_id=%s ORDER BY 1,2""", (run_id,)).fetchall()


def test_multi_depot_vehicles_serve_own_area(pg):
    con, hub, north = _db(pg, multi=True)
    res = run_scenario(con, "SC-2026-09-15-BASE")
    assert res.status in ("OPTIMAL", "FEASIBLE") and res.unassigned == 0 and res.vehicles == 2
    rows = _routes(con, res.run_id)
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    assert by["T01"][0][3] == hub and by["T01"][-1][3] == hub and by["T02"][0][3] == north and by["T02"][-1][3] == north
    assert {r[4] for r in by["T01"] if r[4]} == {"S0", "S1", "S2"} and {r[4] for r in by["T02"] if r[4]} == {"S3", "S4", "S5"}
    assert res.total_distance_m < 50000   # no cross-region trips (each trip would be > 100 km)
    con.close()


def test_single_depot_default(pg):
    con, hub, north = _db(pg, multi=False)
    res = run_scenario(con, "SC-2026-09-15-BASE")
    rows = _routes(con, res.run_id)
    assert all(r[3] == hub for r in rows if r[2] == "DEPOT") and res.unassigned == 0
    assert res.total_distance_m > 200000   # someone drives to the north cluster from the hub
    con.close()
