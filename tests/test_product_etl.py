from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tmod.product.db import SEED, init
from tmod.product.etl import apply_rule, load_rows_csv, load_rows_xlsx, map_row, run_etl

LMD_ROWS = [
    {"SHIPMENT_ID": "G1", "ORDER_NO": "O1", "APPT_DT": "2026-09-15 00:00:00", "APPT_WINDOW": "08:00-12:00", "CHARGE_MIN": "45", "TOT_WGT": "100",
     "TOT_CUFT": "10", "ITEM_CNT": "2", "LOAD_ID": "L1", "APPT_TRUCK_ID": "T01", "SHIP_TO_ID": "AD1", "ADDR_LINE": "1 Main", "ZIP_CD": "30309", "LAT": "", "LON": "", "CUST_CD": "C1", "SHIP_TO_NM": "Acme"},
    {"SHIPMENT_ID": "G2", "ORDER_NO": "O1", "APPT_DT": "2026-09-15", "APPT_WINDOW": "", "CHARGE_MIN": "0", "TOT_WGT": "50",
     "TOT_CUFT": "", "ITEM_CNT": "1", "LOAD_ID": "", "APPT_TRUCK_ID": "", "SHIP_TO_ID": "AD1", "ADDR_LINE": "1 Main", "ZIP_CD": "30309", "LAT": "33.8", "LON": "-84.4", "CUST_CD": "C1", "SHIP_TO_NM": "Acme"},
    {"SHIPMENT_ID": "G3", "ORDER_NO": "O2", "APPT_DT": "", "APPT_WINDOW": "", "CHARGE_MIN": "0", "TOT_WGT": "1", "TOT_CUFT": "1", "ITEM_CNT": "1",
     "LOAD_ID": "", "APPT_TRUCK_ID": "", "SHIP_TO_ID": "AD2", "ADDR_LINE": "2 Oak", "ZIP_CD": "30032", "LAT": "", "LON": "", "CUST_CD": "", "SHIP_TO_NM": ""},
]


def test_rules():
    assert apply_rule("zip5", "2101", {}) == "02101"
    assert abs(apply_rule("lb_to_kg", "100", {}) - Decimal("45.359237")) < Decimal("0.0001")
    assert apply_rule("min_to_s", "45", {}) == 2700 and apply_rule("int", "2.0", {}) == 2
    assert apply_rule("window_start_of:APPT_DT", "08:00-12:00", {"appt_dt": "2026-09-15"}) == datetime(2026, 9, 15, 8, 0)
    assert apply_rule("window_end_of:APPT_DT", "08:00-12:00", {"appt_dt": "2026-09-15 00:00:00"}) == datetime(2026, 9, 15, 12, 0)
    assert apply_rule("prefix:BY-", "AD1", {}) == "BY-AD1" and apply_rule("const:X", None, {}) == "X"
    assert apply_rule("slug", "Pulte Homes - Bldg 7", {}) == "PULTE-HOMES-BLDG-7"
    assert apply_rule("locid:zip", "7178 Highland Blvd", {"zip": "30134"}) == apply_rule("locid:zip", "7178 highland blvd ", {"zip": "30134"})
    with pytest.raises(ValueError):
        apply_rule("nope", "x", {})


def test_etl_lmd_rows(pg):
    import psycopg
    init(pg, seed=True, drop=True)
    with psycopg.connect(pg) as con:
        con.execute("SET search_path TO tmod")
        rep = run_etl(con, "BLUE_YONDER", LMD_ROWS)
        assert rep.rows == 3 and rep.shipments == 2 and rep.locations == 1 and rep.customers == 1 and rep.geocoded == 1
        assert rep.skipped == {"no_requested_date": 1}
        r = con.execute("SELECT weight_kg, service_s, window_start, window_end, pieces, source_load_ref FROM shipment WHERE source_ref='G1'").fetchone()
        assert abs(r[0] - Decimal("45.359")) < Decimal("0.001") and r[1] == 2700 and r[2].hour == 8 and r[3].hour == 12 and r[4] == 2 and r[5] == "L1"
        loc = con.execute("SELECT location_code, postal_code, latitude, geocode_source FROM location WHERE location_code='BY-AD1'").fetchone()
        assert loc[1] == "30309" and 33 < loc[2] < 34 and loc[3].startswith("ZCTA")
        # idempotent + update
        rows2 = [dict(LMD_ROWS[0], TOT_WGT="200"), LMD_ROWS[1], LMD_ROWS[2]]
        rep2 = run_etl(con, "BLUE_YONDER", rows2)
        assert rep2.shipments == 2 and con.execute("SELECT count(*) FROM shipment").fetchone()[0] == 2
        assert abs(con.execute("SELECT weight_kg FROM shipment WHERE source_ref='G1'").fetchone()[0] - Decimal("90.718")) < Decimal("0.001")


def test_etl_xlsx(pg, tmp_path):
    import openpyxl
    import psycopg
    init(pg, seed=True, drop=True)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Shipments"
    ws.append(["shipment_id", "purchase_order", "delivery_date", "order_type", "customer_name", "phone", "address", "city", "state", "zip", "latitude", "longitude", "model_code", "pieces", "weight_lb", "volume_cuft", "service_minutes", "notes", "window"])
    ws.append(["SH1", "PO1", datetime(2026, 9, 11), "BUILDER", "Pulte Homes", "555", "7178 Highland Blvd", "Douglasville", "ga", "30134", 33.76, -84.74, "M", 1, 300, 80, 20, None, "08:00-12:00"])
    ws.append(["SH2", "PO1", datetime(2026, 9, 11), "BUILDER", "Pulte Homes", "555", "7178 Highland Blvd", "Douglasville", "ga", "30134", 33.76, -84.74, "M", 2, 100, 10, 45, "x", None])
    p = tmp_path / "s.xlsx"; wb.save(p)
    with psycopg.connect(pg) as con:
        con.execute("SET search_path TO tmod")
        con.execute(SEED.parent.joinpath("003_mapping_xlsx.sql").read_text())
        rep = run_etl(con, "XLSX", load_rows_xlsx(p))
        assert rep.shipments == 2 and rep.locations == 1 and rep.customers == 1 and rep.skipped == {}
        assert con.execute("SELECT state_code FROM location").fetchone()[0] == "GA"
        assert con.execute("SELECT customer_code, name FROM customer").fetchone() == ("PULTE-HOMES", "Pulte Homes")
        assert con.execute("SELECT window_start FROM shipment WHERE source_ref='SH1'").fetchone()[0].hour == 8
        assert con.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='tmod' AND column_name='phone'").fetchone()[0] == 0


REAL = Path("data/private/lmd_lphb30260_demo/shipments.csv")


@pytest.mark.skipif(not REAL.exists(), reason="private extract not present")
def test_etl_real_csv(pg):
    import psycopg
    init(pg, seed=True, drop=True)
    with psycopg.connect(pg) as con:
        con.execute("SET search_path TO tmod")
        rep = run_etl(con, "BLUE_YONDER", load_rows_csv(REAL))
        print("\n" + rep.summary())
        assert rep.rows == 548 and rep.shipments + sum(rep.skipped.values()) == 548 and rep.shipments >= 540
