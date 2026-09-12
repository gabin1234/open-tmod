from datetime import datetime

import pytest

from tmod.product.db import SEED, init
from tmod.product.etl import load_rows_xlsx, run_etl
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


def _db(pg, cap_kg=600, n_vehicles=2):
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    _OPEN.append(con)
    con.execute("SET search_path TO tmod")
    con.execute("UPDATE scenario SET distance_provider='MANUAL', time_limit_s=2, plan_date='2026-09-15'")
    con.execute("UPDATE scenario_constraint SET enabled_flag=false WHERE constraint_code='TIME_WINDOW'")
    con.execute("UPDATE vehicle_type SET capacity_kg=%s, max_stops=NULL", (cap_kg,))
    con.execute("DELETE FROM scenario_vehicle WHERE vehicle_id NOT IN (SELECT vehicle_id FROM vehicle ORDER BY vehicle_code LIMIT %s)", (n_vehicles,))
    con.execute("UPDATE location SET latitude=33.50, longitude=-84.30 WHERE location_code='HUB-LPHB-30260'")
    ss = con.execute("SELECT source_system_id FROM source_system WHERE system_code='XLSX'").fetchone()[0]
    L = {}
    for i, (la, lo) in enumerate([(33.51, -84.30), (33.52, -84.30), (33.50, -84.29), (33.53, -84.31)]):
        L[i] = con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", la, lo)).fetchone()[0]
    con.commit()
    return con, ss, L


def _rows(con, run_id):
    return con.execute("""SELECT v.vehicle_code, x.route_sequence, s.source_ref, x.stop_kind, x.load_after_kg, x.stop_location_id
                          FROM optimization_route x JOIN vehicle v USING (vehicle_id) LEFT JOIN shipment s USING (shipment_id)
                          WHERE optimization_run_id=%s ORDER BY v.vehicle_code, x.route_sequence""", (run_id,)).fetchall()


def test_pickup_delivery_pair(pg):
    con, ss, L = _db(pg, cap_kg=600, n_vehicles=2)
    for i in range(4):
        con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,%s,%s,'2026-09-15',300,100)", (ss, f"D{i}", L[i % 3]))
    con.execute("INSERT INTO shipment (source_system_id, source_ref, kind, pickup_location_id, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,'PD1','PICKUP_DELIVERY',%s,%s,'2026-09-15',300,500)", (ss, L[0], L[3]))
    con.execute("INSERT INTO scenario_shipment (scenario_id, shipment_id) SELECT (SELECT scenario_id FROM scenario), shipment_id FROM shipment")
    con.commit()
    fill_distance_cache(con, Grid(), [con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]] + list(L.values()))
    res = run_scenario(con, "SC-2026-09-15-BASE")
    assert res.status in ("OPTIMAL", "FEASIBLE") and res.unassigned == 0, res
    rows = _rows(con, res.run_id)
    pd = [r for r in rows if r[2] == "PD1"]
    assert len(pd) == 2 and pd[0][3] == "PICKUP" and pd[1][3] == "DELIVERY" and pd[0][0] == pd[1][0] and pd[0][1] < pd[1][1]
    assert pd[0][5] == L[0] and pd[1][5] == L[3]
    assert all(r[4] is None or float(r[4]) <= 600 for r in rows)
    assert float(pd[0][4]) == 500 and float(pd[1][4]) == 0
    # capacity: no plain delivery rides between P and D beyond capacity on that vehicle
    veh = pd[0][0]
    between = [r for r in rows if r[0] == veh and pd[0][1] < r[1] < pd[1][1] and r[3] == "DELIVERY"]
    assert len(between) <= 1   # 500 + 100 = 600 fits; two would not
    con.close()


def test_pickup_returns_to_depot_and_pair_drop(pg):
    con, ss, L = _db(pg, cap_kg=400, n_vehicles=1)
    con.execute("INSERT INTO shipment (source_system_id, source_ref, kind, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,'PK1','PICKUP',%s,'2026-09-15',300,150)", (ss, L[1]))
    con.execute("INSERT INTO shipment (source_system_id, source_ref, kind, pickup_location_id, delivery_location_id, requested_date, service_s, weight_kg, optional_flag, drop_penalty) VALUES (%s,'PD9','PICKUP_DELIVERY',%s,%s,'2026-09-15',300,900,true,5)", (ss, L[0], L[3]))
    con.execute("UPDATE scenario_constraint SET enabled_flag=true WHERE constraint_code='OPTIONAL_DROP'")
    con.execute("INSERT INTO scenario_shipment (scenario_id, shipment_id) SELECT (SELECT scenario_id FROM scenario), shipment_id FROM shipment")
    con.commit()
    fill_distance_cache(con, Grid(), [con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]] + list(L.values()))
    res = run_scenario(con, "SC-2026-09-15-BASE")
    rows = _rows(con, res.run_id)
    pk = [r for r in rows if r[2] == "PK1"]
    assert len(pk) == 1 and pk[0][3] == "PICKUP" and float(pk[0][4]) == 150 and rows[-1][3] == "DEPOT" and float(rows[-1][4]) == 150
    un = con.execute("SELECT s.source_ref, u.reason FROM optimization_unassigned u JOIN shipment s USING (shipment_id) WHERE optimization_run_id=%s", (res.run_id,)).fetchall()
    assert un == [("PD9", "DROPPED_OPTIONAL")] and not [r for r in rows if r[2] == "PD9"]
    con.close()


def test_etl_xlsx_pickup_delivery(pg, tmp_path):
    import openpyxl
    import psycopg
    init(pg, seed=True, drop=True)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Shipments"
    ws.append(["shipment_id", "delivery_date", "kind", "address", "zip", "latitude", "longitude", "pickup_address", "pickup_zip", "pickup_latitude", "pickup_longitude", "weight_lb", "service_minutes"])
    ws.append(["X1", datetime(2026, 9, 21), "pickup_delivery", "9 End St", "30309", 33.79, -84.39, "1 Start Ave", "30032", 33.7, -84.3, 200, 15])
    ws.append(["X2", datetime(2026, 9, 21), "", "9 End St", "30309", 33.79, -84.39, None, None, None, None, 50, 10])
    p = tmp_path / "pd.xlsx"; wb.save(p)
    with psycopg.connect(pg) as con:
        con.execute("SET search_path TO tmod")
        con.execute(SEED.parent.joinpath("003_mapping_xlsx.sql").read_text())
        rep = run_etl(con, "XLSX", load_rows_xlsx(p))
        assert rep.shipments == 2 and rep.locations == 2
        r = con.execute("SELECT s.kind, pl.postal_code, dl.postal_code FROM shipment s JOIN location dl ON dl.location_id=s.delivery_location_id LEFT JOIN location pl ON pl.location_id=s.pickup_location_id WHERE s.source_ref='X1'").fetchone()
        assert r == ("PICKUP_DELIVERY", "30032", "30309")
        assert con.execute("SELECT kind, pickup_location_id FROM shipment WHERE source_ref='X2'").fetchone() == ("DELIVERY", None)
