from datetime import date
from decimal import Decimal

import pytest

from tmod.canonical import Location, build
from tmod.ingestion import ingest_csv
from tmod.validation import validate

RATES = "carrier_id,rate_type,rate,min_charge\nC1,per_mile,2.5,150\nC2,Flat,300,\n"


def load(tmp_path, ship_csv, rates=RATES, locations=None):
    (tmp_path / "s.csv").write_text(ship_csv)
    (tmp_path / "r.csv").write_text(rates)
    t = {"shipments": ingest_csv(tmp_path / "s.csv"), "rates": ingest_csv(tmp_path / "r.csv")}
    if locations:
        (tmp_path / "l.csv").write_text(locations)
        t["locations"] = ingest_csv(tmp_path / "l.csv")
    return t, validate(t)


def test_types_and_dedupe(tmp_path):
    csv = ("shipment_id,ship_date,scac,weight_lb,actual_cost,origin_zip,dest_zip,dest_lat,dest_lon,pieces,mode\n"
           "S1,01/15/2024,C1,\"1,200\",$250.00,60601,10001,40.75,-73.99,3,LTL\n"
           "S2,2024-01-16,C2,50,300,60601,10001,,,,\n")
    ds = build(*load(tmp_path, csv))
    s1, s2 = ds.shipments
    assert s1.ship_date == date(2024, 1, 15) and s1.weight_lb == Decimal("1200") and s1.actual_cost == Decimal("250.00")
    assert s1.carrier_id == "C1" and s1.pieces == 3 and s1.mode == "LTL" and s2.pieces is None
    assert s1.dest.lat == 40.75 and s1.dest.key.startswith("ll:")
    assert s2.dest.key == "zip:10001" and s1.origin.key == "zip:60601"
    assert len(ds.locations) == 3  # origin zip shared, two distinct dests (ll vs zip)
    assert ds.total_actual_cost == Decimal("550.00")
    assert [r.rate_type for r in ds.rates] == ["per_mile", "flat"]
    assert ds.rates[0].min_charge == Decimal("150") and ds.rates[1].min_charge is None
    assert ds.rates[0].source_row == 2


def test_rejected_rows_dropped_source_row_kept(tmp_path):
    csv = ("shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_zip,dest_zip\n"
           "S1,2024-01-15,C1,abc,250,60601,10001\n"
           "S2,2024-01-15,C1,10,250,60601,10001\n")
    tables, rep = load(tmp_path, csv)
    assert not rep.ok
    ds = build(tables, rep)
    assert [s.id for s in ds.shipments] == ["S2"]
    assert ds.shipments[0].source_row == 3


def test_address_key_and_named_locations(tmp_path):
    csv = ("shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_address,dest_zip\n"
           "S1,2024-01-15,C1,10,250, 1 Main St ,10001\n")
    loc = "location_id,address,lat,lon\nDC1,1 Main St,41.8,-87.6\n"
    ds = build(*load(tmp_path, csv, locations=loc))
    assert ds.shipments[0].origin.key == "addr:1 main st"
    assert ds.named_locations["DC1"].lat == 41.8


def test_missing_column_raises(tmp_path):
    csv = "shipment_id,ship_date,carrier_id,weight_lb,origin_zip,dest_zip\nS1,2024-01-15,C1,10,60601,10001\n"
    with pytest.raises(ValueError, match="MISSING_COLUMN"):
        build(*load(tmp_path, csv))


def test_all_rejected_raises(tmp_path):
    csv = "shipment_id,ship_date,carrier_id,weight_lb,actual_cost,origin_zip,dest_zip\nS1,2024-01-15,C9,10,1,60601,10001\n"
    with pytest.raises(ValueError, match="no accepted"):
        build(*load(tmp_path, csv))


def test_location_key_precedence():
    assert Location(zip="1", lat=1.0, lon=2.0).key == "ll:1.00000,2.00000"
    assert Location(zip="1", address="x").key == "zip:1"
    assert Location(address="X y").key == "addr:x y"
