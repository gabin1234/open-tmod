from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tmod.baseline import Knobs, calibrate, evaluate, load_knobs, prepare, save_knobs
from tmod.canonical import Dataset, Location, RateCard, Shipment

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


@pytest.fixture(scope="module")
def sample_ds():
    ds, reports = prepare({"shipments": SAMPLE / "shipments.csv", "rates": SAMPLE / "rates.csv"})
    return ds, reports


def test_prepare_sample(sample_ds):
    ds, reports = sample_ds
    assert len(ds.shipments) == 200
    assert "200/202 rows accepted" in reports["validation"]
    assert "ungeocoded 0" in reports["geocode"]
    assert all(s.origin.lat is not None and s.dest.lat is not None for s in ds.shipments)


def test_calibrate_recovers_truth(sample_ds):
    ds, _ = sample_ds
    res = calibrate(ds)
    assert (res.knobs.circuity, res.knobs.cwt_round_up) == (1.25, False), res.summary()
    assert res.within_tolerance and abs(res.gap_pct) < 2.0
    assert res.unrated == () and res.unrated_pct == 0.0
    assert set(res.by_carrier) == {"C1", "C2", "C3"}
    assert all(abs(g) < 5 for _, _, g in res.by_carrier.values())


def test_gap_direction(sample_ds):
    ds, _ = sample_ds
    assert evaluate(ds, Knobs(circuity=1.10)).gap_pct < 0
    assert evaluate(ds, Knobs(circuity=1.40)).gap_pct > 0


def test_knobs_roundtrip(tmp_path):
    k = Knobs(1.25, 55.0, True)
    save_knobs(tmp_path / "k.json", k)
    assert load_knobs(tmp_path / "k.json") == k


def test_evaluate_exact():
    a = Location(zip="1", lat=0.0, lon=0.0)
    b = Location(zip="2", lat=0.0, lon=1.0)  # 1 deg lon at equator = 69.09 mi great-circle
    ships = (Shipment("S1", date(2024, 1, 1), "C1", D(1000), D("100.00"), a, b, None, None, None, None, None, 2),
             Shipment("S2", date(2024, 1, 1), "C2", D(1000), D("100.00"), a, b, None, None, None, None, None, 3),
             Shipment("S3", date(2024, 1, 1), "C9", D(1000), D("100.00"), a, b, None, None, None, None, None, 4))
    rates = (RateCard("C1", "flat", D("110"), None, None, None, 2), RateCard("C2", "flat", D("90"), None, None, None, 3))
    res = evaluate(Dataset(ships, rates, (), {}), Knobs(), tolerance=2.0)
    assert res.total_model == D("200.00") and res.total_actual == D("200.00") and res.gap_pct == 0.0
    assert res.by_carrier["C1"] == (D("110.00"), D("100.00"), 10.0)
    assert res.by_carrier["C2"][2] == -10.0
    assert res.unrated == (("S3", "NO_RATE"),) and abs(res.unrated_pct - 33.33) < 0.01
    assert res.within_tolerance
    assert abs(res.matrix[(a.key, b.key)].miles - 69.09 * 1.2) < 0.5
