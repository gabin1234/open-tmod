from datetime import date
from decimal import Decimal as D

from tmod.baseline import Knobs, evaluate
from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.comparison import compare, kpi
from tmod.optimization import consolidate
from tmod.rerating import rerate
from tmod.routing import Route
from tmod.scenario import ConsolidationWindow

A, B = Location(zip="60601", lat=41.88, lon=-87.63), Location(zip="10001", lat=40.71, lon=-74.0)


def ship(i, day, weight, carrier="C1", deliver=None):
    return Shipment(i, date(2024, 3, day), carrier, D(weight), D(500), A, B, "TL", None, deliver, None, None, 2)


DS = Dataset((ship("S1", 1, 11000, deliver=date(2024, 3, 3)), ship("S2", 2, 22000, deliver=date(2024, 3, 6)),
              ship("S3", 9, 11000), ship("S4", 1, 1000, "C9")),
             (RateCard("C1", "flat", D("400"), None, None, None, 2),), (A, B), {})
K = Knobs(circuity=1.25)


def test_kpi():
    base = evaluate(DS, K)  # S4 unrated (C9)
    k = kpi(DS, base.rated, base.matrix, capacity_lb=D(44000))
    assert k.shipments == 3 and k.total_cost == D("1200.00")
    assert abs(k.total_miles - 3 * base.matrix[(A.key, B.key)].miles) < 1e-6
    assert k.avg_weight_lb == D(44000) / 3
    assert abs(k.avg_utilization_pct - 100 / 3) < 1e-9
    assert k.avg_transit_days == 3.0  # (2 + 4) / 2
    assert k.by_carrier == {"C1": D("1200.00")}
    assert kpi(DS, [], {}, None).shipments == 0


def test_compare_identity_and_gate():
    base = evaluate(DS, K)
    rr = rerate(DS, K)
    c = compare("same", DS, base, DS, rr, gate_passed=False)
    assert c.delta_cost == 0 and c.delta_pct == 0.0
    assert all(d.delta == D(0) for d in c.per_shipment)
    s = c.summary()
    assert "GATED" in s and "1,200.00" not in s and "gate not passed" in s
    s2 = compare("same", DS, base, DS, rr, gate_passed=True).summary()
    assert "1,200.00" in s2 and "GATED" not in s2 and "+0.00%" in s2


def test_compare_consolidation():
    base = evaluate(DS, K)
    sc, rep = consolidate(DS, ConsolidationWindow(3, D(44000)))
    rr = rerate(sc, K, bins=rep.bins)
    c = compare("cons", DS, base, sc, rr, gate_passed=True, capacity_lb=D(44000))
    cons = next(d for d in c.per_shipment if d.scenario_id == "CONS-0001")
    assert cons.members == ("S1", "S2") and cons.baseline_cost == D("800.00") and cons.scenario_cost == D("400.00")
    assert cons.delta == D("-400.00") and c.delta_cost == D("-400.00")
    assert abs(c.delta_pct + 33.33) < 0.01
    assert c.scenario.shipments == 2 and c.scenario.avg_utilization_pct > c.baseline.avg_utilization_pct


def test_unrated_member_gives_none():
    base = evaluate(DS, K)
    ds2 = Dataset(DS.shipments, DS.rates + (RateCard("C9", "flat", D("1"), None, None, None, 3),), DS.locations, {})
    rr = rerate(ds2, K)
    c = compare("x", DS, base, ds2, rr, gate_passed=True)
    s4 = next(d for d in c.per_shipment if d.scenario_id == "S4")
    assert s4.baseline_cost is None and s4.delta is None and s4.scenario_cost == D("1.00")
