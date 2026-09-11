from datetime import date
from decimal import Decimal

import pytest

from tmod.ingestion import ingest_csv
from tmod.validation import parse_date, parse_decimal, parse_int, validate

SHIP = "shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_zip,dest_zip\n"
RATES = "carrier_id,rate_type,rate\nC1,per_mile,2.5\nC2,flat,300\n"


def tables(tmp_path, ship_rows, rates=RATES, ship_header=SHIP, with_rates=True):
    s = tmp_path / "shipments.csv"
    s.write_text(ship_header + ship_rows)
    out = {"shipments": ingest_csv(s)}
    if with_rates:
        r = tmp_path / "rates.csv"
        r.write_text(rates)
        out["rates"] = ingest_csv(r)
    return out


def codes(rep, sev=None):
    return [f.code for f in rep.findings if sev is None or f.severity == sev]


def test_clean(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,100,250.00,60601,10001\nS2,01/16/2024,C2,50,300,60601,10001\n"))
    assert rep.ok, rep.summary()
    assert rep.rejected["shipments"] == frozenset()
    assert rep.row_counts["shipments"] == (2, 2)
    assert "OK" in rep.summary()


def test_missing_table(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,100,250,60601,10001\n", with_rates=False))
    assert not rep.ok
    assert "MISSING_TABLE" in codes(rep, "ERROR")


def test_missing_column_rejects_all(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,100,60601,10001\n",
                          ship_header="shipment_id,ship_date,carrier_id,weight_lb,origin_zip,dest_zip\n"))
    assert "MISSING_COLUMN" in codes(rep)
    assert rep.rejected["shipments"] == frozenset({2})


def test_alias(tmp_path):
    hdr = "shipment_id,ship_date,scac,weight,cost,origin_postal_code,dest_zip\n"
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,100,250,60601,10001\n", ship_header=hdr))
    assert rep.ok, rep.summary()
    assert rep.mapping["shipments"]["origin_zip"] == "origin_postal_code"
    assert rep.mapping["shipments"]["carrier_id"] == "scac"


def test_bad_type_only_that_row(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,abc,250,60601,10001\nS2,2024-01-15,C1,10,20,60601,10001\n"))
    assert codes(rep, "ERROR") == ["BAD_TYPE"]
    assert rep.rejected["shipments"] == frozenset({2})
    assert rep.row_counts["shipments"] == (2, 1)


def test_out_of_range_and_enum(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,-5,250,60601,10001\n",
                          rates="carrier_id,rate_type,rate\nC1,per_ton,2.5\n"))
    assert set(codes(rep, "ERROR")) == {"OUT_OF_RANGE", "BAD_ENUM"}
    assert rep.rejected["rates"] == frozenset({2})


def test_missing_location(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,10,250,,10001\n"))
    assert codes(rep, "ERROR") == ["MISSING_LOCATION"]
    assert "origin" in rep.findings[[f.code for f in rep.findings].index("MISSING_LOCATION")].detail


def test_latlon_satisfies_location(tmp_path):
    hdr = "shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_lat,origin_lon,dest_zip\n"
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,10,250,41.88,-87.63,10001\nS2,2024-01-15,C1,10,250,95,-87.63,10001\n", ship_header=hdr))
    assert codes(rep, "ERROR") == ["BAD_TYPE", "MISSING_LOCATION"]  # row 3: lat 95 invalid -> no location
    assert rep.rejected["shipments"] == frozenset({3})


def test_duplicate_key(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,10,250,60601,10001\nS1,2024-01-15,C1,10,250,60601,10001\n"))
    assert codes(rep, "ERROR") == ["DUPLICATE_KEY"]
    assert rep.rejected["shipments"] == frozenset({3})


def test_unknown_ref(tmp_path):
    rep = validate(tables(tmp_path, "S1,2024-01-15,C9,10,250,60601,10001\n"))
    assert codes(rep, "ERROR") == ["UNKNOWN_REF"]


def test_ingest_issue_and_unknown_column_are_warn(tmp_path):
    hdr = "shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_zip,dest_zip,foo\n"
    rep = validate(tables(tmp_path, "S1,2024-01-15,C1,10,250,60601,10001\n", ship_header=hdr))  # ragged: 7 < 8
    assert rep.ok
    assert set(codes(rep, "WARN")) == {"UNKNOWN_COLUMN", "INGEST_ISSUE"}


def test_parsers():
    assert parse_decimal("$1,234.50") == Decimal("1234.50")
    assert parse_decimal("  ") is None
    assert parse_int("12") == 12
    assert parse_date("01/15/2024") == date(2024, 1, 15)
    assert parse_date("2024-01-15 08:30") == date(2024, 1, 15)
    assert parse_date("2024-01-15T08:30:00Z") == date(2024, 1, 15)
    assert parse_date("20240115") == date(2024, 1, 15)
    assert parse_date("") is None
    with pytest.raises(ValueError):
        parse_int("1.5")
    with pytest.raises(ValueError):
        parse_date("15/01/2024")
