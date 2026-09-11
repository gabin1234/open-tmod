from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tmod.canonical import Location
from tmod.lmd import LmdDataset, Stop, Truck
from tmod.lmd_baseline import evaluate_loads
from tmod.lmd_compare import compare_routes
from tmod.lmd_map import render_lmd_html
from tmod.lmd_poc import run
from tmod.routing import Route

HUB = Location(zip="30260", lat=33.58, lon=-84.34)


def stop(i, lat, lon, load):
    return Stop(f"S{i}", f"S{i}", date(2026, 9, 1), Location(zip="3", lat=lat, lon=lon), None, 30, 30, (f"sh{i}",), load, "T01", None, "OPTIMIZED", D(1), D(1), 1)


class Manhattan:
    name = "manh"

    def route(self, o, d):
        mi = abs(o.lat - d.lat) + abs(o.lon - d.lon)
        return Route(mi, mi, self.name)


def _pair():
    s = [stop(1, 34.0, -84.34, "A"), stop(2, 34.1, -84.34, "B"), stop(3, 34.2, -84.34, "B")]
    lmd = LmdDataset("H", HUB, tuple(s), (Truck("T01", 500, 600, None, None),), {}, ())
    base = evaluate_loads(lmd, {"A": (s[0],), "B": (s[1], s[2])}, [Manhattan()])
    scen = evaluate_loads(lmd, {"OPT-1": (s[0], s[1], s[2])}, [Manhattan()], keep_order=True)
    return base, scen


def test_compare_and_gate():
    base, scen = _pair()
    c = compare_routes("merge", base, scen, (), gate_passed=True)
    assert c.delta["loads"] == -1 and c.delta_pct["loads"] == -50.0 and c.delta["stops"] == 0
    assert c.delta["miles"] < 0 and "+" in c.summary() or "-" in c.summary()
    assert "GATED" not in c.summary()
    g = compare_routes("merge", base, scen, ("S9",), gate_passed=False)
    assert "GATED" in g.summary() and "unrouted in scenario: 1" in g.summary()


def test_render():
    base, scen = _pair()
    c = compare_routes("merge", base, scen, (), True)
    h = render_lmd_html(c, base, scen, HUB)
    assert "leaflet@1.9.4" in h and "33.58" in h and '<option value="2026-09-01">' in h and "OPT-1" in h and "GATED" not in h
    assert "GATED" in render_lmd_html(compare_routes("m", base, scen, (), False), base, scen, HUB)


REAL = Path("data/private/lmd_lphb30260_demo")


@pytest.mark.skipif(not (REAL / "distance_truth.csv").exists(), reason="private extract not present")
def test_real_end_to_end(tmp_path):
    from tmod.lmd_optimize import LmdScenario
    cmp, out = run(REAL, LmdScenario("e2e", time_limit_s=2), tmp_path / "lmd.html")
    assert out.exists() and out.stat().st_size > 5000 and cmp.gate_passed
    assert cmp.scenario.loads < cmp.baseline.loads and cmp.unrouted == ()
