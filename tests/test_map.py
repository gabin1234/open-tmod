from datetime import date
from decimal import Decimal as D
from pathlib import Path

from tmod.baseline import Knobs, evaluate
from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.comparison import compare
from tmod.map import render_html
from tmod.poc import run
from tmod.rerating import rerate

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"
A, B, C = Location(zip="60601", lat=41.88, lon=-87.63), Location(zip="10001", lat=40.71, lon=-74.0), Location(zip="00099")


def _ds():
    ships = (Shipment("S1", date(2024, 3, 1), "C1", D(1000), D(500), A, B, None, None, None, None, None, 2),
             Shipment("S2", date(2024, 3, 1), "C1", D(1000), D(500), A, C, None, None, None, None, None, 3))
    return Dataset(ships, (RateCard("C1", "flat", D("400"), None, None, None, 2),), (A, B, C), {})


def test_render_gate_toggle():
    ds = _ds()
    base = evaluate(ds, Knobs())
    rr = rerate(ds, Knobs())
    h = render_html(compare("t", ds, base, ds, rr, False), ds, ds, base.matrix, rr.matrix, rr)
    assert "leaflet@1.9.4" in h and "GATED" in h and "baseline_cost" not in h and "41.88" in h
    h2 = render_html(compare("t", ds, base, ds, rr, True), ds, ds, base.matrix, rr.matrix, rr)
    assert "GATED" not in h2 and "<th>delta</th>" in h2 and "400.00" in h2


def test_poc_end_to_end(tmp_path):
    cmp, out = run(SAMPLE, SAMPLE / "scenario_consolidation.json", tmp_path / "poc.html")
    assert out.exists() and out.stat().st_size > 5000
    assert cmp.gate_passed is False and "GATED" in cmp.summary()
    assert cmp.scenario.shipments < cmp.baseline.shipments == 200
    assert cmp.baseline.avg_transit_days is not None
