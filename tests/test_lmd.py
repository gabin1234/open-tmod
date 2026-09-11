from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tmod.address import normalize
from tmod.geocoding import ZipCentroidGeocoder, geocode
from tmod.ingestion import ingest
from tmod.lmd import LMD_SCHEMAS, apply_geocoded, build_lmd, to_dataset
from tmod.validation import validate

SHIP_HDR = "shipment_id,hub_cd,ship_to_id,req_capa_min,status_cd,appt_dt,zip_cd,lat,lon,zone_cd,charge_min,stop_base_min,tot_wgt,item_cnt,load_id,truck_id,appt_window\n"
SHIPS = (
    "S1,LPHB-30260,A1,20,OPTIMIZED,2026-09-01 00:00:00,30309,,,Z2,0,20,50,1,L1,T01,08:00-12:00\n"
    "S2,LPHB-30260,A1,65,OPTIMIZED,2026-09-01,30309,,,Z2,45,20,30,2,L1,T01,08:00-12:00\n"
    "S3,LPHB-30260,A1,20,SOFT_ALLOC,2026-09-03,30309,,,Z2,0,20,10,1,,,\n"
    "S4,LPHB-30260,B7,80,HARD_CONSUME,2026-09-01,,33.75,-84.39,Z1,60,20,100,1,L1,T01,08:00-12:00\n"
    "S5,LPHB-30260,C9,abc,SOFT_ALLOC,2026-09-02,30310,,,Z1,0,20,10,1,,,\n"
)
TRUCKS = "truck_id,daily_work_min,daily_duty_min,shift_start_hh,shift_end_hh\nT01,500,600,08:00,18:00\nT02,500,600,08:00,18:00\n"
ZONES = "zip_from,zip_to,zone_cd,match_priority\n30301,30318,Z1,10\n30319,30342,Z2,10\n30318,30318,Z2,20\n"
PARAMS = "param_cd,param_val\nSTOP_BASE_MIN,20\nTRAVEL_MIN_PER_STOP,15\n"


def load(tmp_path, ships=SHIPS):
    files = {"shipments": SHIP_HDR + ships, "trucks": TRUCKS, "zone_zip": ZONES, "params": PARAMS}
    for k, v in files.items():
        (tmp_path / f"{k}.csv").write_text(v)
    tables = ingest({k: tmp_path / f"{k}.csv" for k in files})
    return tables, validate(tables, LMD_SCHEMAS)


def test_build_stops(tmp_path):
    tables, rep = load(tmp_path)
    assert [f.code for f in rep.findings if f.severity == "ERROR"] == ["BAD_TYPE"]  # S5 req_capa_min
    lmd = build_lmd(tables, rep)
    assert lmd.hub_cd == "LPHB-30260" and lmd.hub.zip == "30260"
    ids = {s.id: s for s in lmd.stops}
    assert set(ids) == {"A1@2026-09-01#L1", "A1@2026-09-03", "B7@2026-09-01#L1"}
    a = ids["A1@2026-09-01#L1"]
    assert a.shipments == ("S1", "S2") and a.service_min == 20 + 45 and a.capa_min_sum == 85
    assert a.weight_lb == D(80) and a.pieces == 3 and a.load_id == "L1" and a.truck_id == "T01" and a.status == "OPTIMIZED"
    b = ids["B7@2026-09-01#L1"]
    assert b.location.lat == 33.75 and b.location.zip is None and b.status == "HARD_CONSUME"
    assert lmd.trucks[0].work_min == 500 and len(lmd.trucks) == 2 and lmd.params["TRAVEL_MIN_PER_STOP"] == "15"
    assert lmd.zone_of("30310") == "Z1" and lmd.zone_of("30330") == "Z2" and lmd.zone_of("30001") is None
    assert lmd.zone_of("30318") == "Z2"  # narrower override wins
    assert set(lmd.baseline_loads()) == {"L1"} and len(lmd.baseline_loads()["L1"]) == 2
    assert set(lmd.by_day()) == {date(2026, 9, 1), date(2026, 9, 3)}
    assert build_lmd(tables, rep, stop_base_min=0).stops[0].service_min == 45


def test_pool_truck_passes_and_missing_table(tmp_path):
    tables, rep = load(tmp_path, SHIPS.replace(",T01,", ",1,", 1))
    assert "UNKNOWN_REF" not in [f.code for f in rep.findings]
    assert build_lmd(tables, rep).baseline_loads()["L1"][0].truck_id in ("1", "T01")
    del tables["trucks"]
    rep2 = validate(tables, LMD_SCHEMAS)
    with pytest.raises(ValueError, match="MISSING_TABLE"):
        build_lmd(tables, rep2)


def test_geocode_roundtrip(tmp_path):
    tables, rep = load(tmp_path)
    lmd = build_lmd(tables, rep)
    ds = to_dataset(lmd)
    assert len(ds.shipments) == 3 and all(sh.origin.zip == "30260" for sh in ds.shipments)
    ds, _ = normalize(ds)
    ds, grep = geocode(ds, [ZipCentroidGeocoder()])
    assert grep.ungeocoded == ()
    out = apply_geocoded(lmd, ds)
    assert out.hub.lat is not None and 33 < out.hub.lat < 34
    assert all(s.location.lat is not None for s in out.stops)
    assert next(s for s in out.stops if s.ship_to_id == "B7").location.lat == 33.75


REAL = Path("data/private/lmd_lphb30260_demo")


@pytest.mark.skipif(not REAL.exists(), reason="private extract not present")
def test_real_extract():
    tables = ingest({k: REAL / f"{k}.csv" for k in ("shipments", "trucks", "zone_zip", "params")})
    rep = validate(tables, LMD_SCHEMAS)
    assert rep.ok, rep.summary()
    lmd = build_lmd(tables, rep)
    assert len(lmd.trucks) == 10 and len(lmd.baseline_loads()) == 68
    assert sum(len(s.shipments) for s in lmd.stops) == 548
    assert len(lmd.zone_ranges) == 42 and lmd.zone_of("30309") is not None
    assert all(s.zone is None or lmd.zone_of(s.location.zip or "") == s.zone for s in lmd.stops if s.location.zip)
    pool = {s.truck_id for s in lmd.stops if s.truck_id} - {t.id for t in lmd.trucks}
    print(f"\nreal: stops {len(lmd.stops)}, days {len(lmd.by_day())}, pool trucks {pool}")
