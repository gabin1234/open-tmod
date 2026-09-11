from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tmod.canonical import Location
from tmod.lmd import LmdDataset, Stop, Truck
from tmod.lmd_baseline import baseline, evaluate_loads, prepare_lmd, sequence_nearest
from tmod.routing import Route

HUB = Location(zip="30260", lat=0.0, lon=0.0)


def stop(i, lat, lon, service=30, load="L1", truck="T01", day=date(2026, 9, 1)):
    return Stop(f"S{i}", f"S{i}", day, Location(zip="3", lat=lat, lon=lon), None, service, service, (f"sh{i}",), load, truck, None, "OPTIMIZED", D(1), D(1), 1)


class Manhattan:
    name = "manh"

    def route(self, o, d):
        mi = abs(o.lat - d.lat) + abs(o.lon - d.lon)
        return Route(mi, mi * 2, self.name)


def _lmd(stops, trucks=(Truck("T01", 100, 130, None, None),), params=None):
    return LmdDataset("LPHB-30260", HUB, tuple(stops), tuple(trucks), params or {"TRUCK_WORK_MIN": "50", "TRUCK_DUTY_MIN": "60"}, ())


def test_nearest_and_kpi():
    s1, s2, s3 = stop(1, 10, 0), stop(2, 1, 0), stop(3, 1, 5)   # hub(0,0) -> s2(1) -> s3(5) -> s1(14) -> hub(10)
    lmd = _lmd([s1, s2, s3])
    res = baseline(lmd, [Manhattan()])
    p = res.plans[0]
    assert [s.id for s in p.stops] == ["S2", "S3", "S1"] and len(p.legs) == 4
    assert p.miles == 30 and p.hub_miles == 11 and p.drive_min == 60 and p.service_min == 90 and p.duty_min == 150
    assert p.over_work is False and p.over_duty is True and p.pool is False
    k = res.kpi
    assert (k.loads, k.stops, k.shipments, k.miles, k.inter_stop_miles, k.over_duty, k.days) == (1, 3, 3, 30, 19, 1, 1)
    assert k.by_provider_miles == {"manh": 30} and k.avg_stops_per_load == 3 and k.max_trucks_per_day == 1
    assert "loads 1" in k.summary()


def test_skip_no_coords_and_pool():
    bad = Stop("X", "X", date(2026, 9, 1), Location(zip="30001"), None, 10, 10, ("x",), "L2", "1", None, "OPTIMIZED", D(1), D(1), 1)
    good = stop(9, 2, 0, service=55, load="L2", truck="1")
    res = evaluate_loads(_lmd([bad, good]), {"L2": (bad, good), "L3": (bad,)}, [Manhattan()])
    assert res.skipped == (("X", "NO_COORDS"), ("X", "NO_COORDS")) and len(res.plans) == 1
    p = res.plans[0]
    assert p.pool and p.over_work and p.over_duty  # params limits 50/60: service 55 > 50, duty 55+8 > 60
    assert res.kpi.pool_loads == 1


def test_sequence_ties_deterministic():
    a, b = stop(1, 1, 0), stop(2, 1, 0)
    from tmod.lmd_baseline import _Dist
    order, legs = sequence_nearest(HUB, [b, a], _Dist([Manhattan()]))
    assert [s.id for s in order] == ["S1", "S2"] and legs[1].provider == "same"


REAL = Path("data/private/lmd_lphb30260_demo")


@pytest.mark.skipif(not (REAL / "distance_truth.csv").exists(), reason="private extract not present")
def test_real_baseline():
    lmd, providers, cal = prepare_lmd(REAL)
    assert cal.within_tolerance
    res = baseline(lmd, providers)
    assert res.kpi.loads == 68 and res.skipped == ()
    assert res.kpi.hub_miles <= res.kpi.miles and "truth" in res.kpi.by_provider_miles
    print("\n" + res.kpi.summary())
