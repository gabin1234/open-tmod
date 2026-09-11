from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tmod.canonical import Location
from tmod.lmd import LmdDataset, Stop, Truck
from tmod.lmd_baseline import evaluate_loads, prepare_lmd
from tmod.lmd_optimize import LmdScenario, load_lmd_scenario, optimize, optimize_day
from tmod.routing import Route

HUB = Location(zip="30260", lat=0.0, lon=0.0)
DAY = date(2026, 9, 1)


def stop(i, lat, lon, service=60, zone=None, load="L1"):
    return Stop(f"S{i}", f"S{i}", DAY, Location(zip="3", lat=lat, lon=lon), zone, service, service, (f"sh{i}",), load, "T01", None, "OPTIMIZED", D(1), D(1), 1)


class Manhattan:
    name = "manh"

    def route(self, o, d):
        mi = abs(o.lat - d.lat) + abs(o.lon - d.lon)
        return Route(mi, mi * 1.0, self.name)   # 1 min per mile


def _lmd(stops, n_trucks=2, work=500, duty=600):
    return LmdDataset("H", HUB, tuple(stops), tuple(Truck(f"T{k:02d}", work, duty, None, None) for k in range(1, n_trucks + 1)), {}, ())


GRID = [stop(1, 1, 0), stop(2, 2, 0), stop(3, 3, 0), stop(4, 0, 1), stop(5, 0, 2), stop(6, 0, 3)]  # 6 x 60 min service = 360


def test_two_trucks_when_duty_tight():
    lmd = _lmd(GRID, n_trucks=3, duty=250)           # one truck: 360 service alone > 250
    loads, unrouted = optimize_day(lmd, GRID, [Manhattan()], LmdScenario("t", time_limit_s=1), DAY)
    assert unrouted == () and len(loads) == 2
    res = evaluate_loads(lmd, loads, [Manhattan()], keep_order=True)
    assert res.kpi.over_duty == 0 and res.kpi.stops == 6 and all(p.truck_id in ("T01", "T02", "T03") for p in res.plans)
    assert set(loads) == {"OPT-2026-09-01-1", "OPT-2026-09-01-2"}


def test_one_truck_enough():
    lmd = _lmd(GRID, n_trucks=3, duty=600)
    loads, unrouted = optimize_day(lmd, GRID, [Manhattan()], LmdScenario("t", time_limit_s=1), DAY)
    assert len(loads) == 1 and unrouted == ()
    assert evaluate_loads(lmd, loads, [Manhattan()]).plans[0].miles <= 12  # tour 0->1->2->3 back ... optimal-ish


def test_oversize_stop_dropped():
    big = stop(9, 1, 1, service=700)
    lmd = _lmd(GRID + [big], n_trucks=2, duty=600, work=500)
    loads, unrouted = optimize_day(lmd, GRID + [big], [Manhattan()], LmdScenario("t", time_limit_s=1), DAY)
    assert unrouted == ("S9",) and sum(len(v) for v in loads.values()) == 6


def test_zone_penalty_groups_zones():
    st = [stop(1, 1, 0, zone="A"), stop(2, 1.1, 0, zone="B"), stop(3, 1.2, 0, zone="A"), stop(4, 1.3, 0, zone="B")]
    lmd = _lmd(st, n_trucks=2, duty=200)  # 4x60 = 240 > 200 -> 2 trucks needed
    loads, _ = optimize_day(lmd, st, [Manhattan()], LmdScenario("t", zone_penalty_min=50, time_limit_s=1), DAY)
    assert len(loads) == 2 and all(len({s.zone for s in v}) == 1 for v in loads.values())


def test_optimize_days_and_scenario_json(tmp_path):
    other = [Stop(**{**s.__dict__, "id": s.id + "b", "appt_dt": date(2026, 9, 2), "load_id": None}) for s in GRID[:2]]
    lmd = _lmd(GRID + other, n_trucks=2)
    loads, rep = optimize(lmd, [Manhattan()], LmdScenario("base", time_limit_s=1))
    assert rep.days == 1 and rep.stops == 6 and rep.routed == 6            # baseline pool only
    loads, rep = optimize(lmd, [Manhattan()], LmdScenario("all", stop_pool="all", time_limit_s=1))
    assert rep.days == 2 and rep.stops == 8 and rep.routed == 8 and rep.solver_status == {"solved": 2, "no_solution": 0}
    p = tmp_path / "s.json"
    p.write_text('{"name": "x", "trucks": 4, "zone_penalty_min": 30}')
    assert load_lmd_scenario(p) == LmdScenario("x", trucks=4, zone_penalty_min=30)


REAL = Path("data/private/lmd_lphb30260_demo")


@pytest.mark.skipif(not (REAL / "distance_truth.csv").exists(), reason="private extract not present")
def test_real_optimize():
    lmd, providers, _ = prepare_lmd(REAL)
    loads, rep = optimize(lmd, providers, LmdScenario("real", time_limit_s=3))
    assert rep.solver_status["no_solution"] == 0 and rep.unrouted == () and rep.routed == 175
    res = evaluate_loads(lmd, loads, providers, keep_order=True)
    assert res.kpi.over_duty == 0 and res.kpi.over_work == 0
    print(f"\nreal optimized: {res.kpi.summary()}")
