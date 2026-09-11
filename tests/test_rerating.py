from datetime import date
from decimal import Decimal as D

import pytest

from tmod.baseline import Knobs, evaluate
from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.optimization import consolidate
from tmod.rerating import rerate
from tmod.scenario import CarrierSwitch, ConsolidationWindow, Scenario, apply

A, B = Location(zip="60601", lat=41.88, lon=-87.63), Location(zip="10001", lat=40.71, lon=-74.0)


def ship(i, day, weight, carrier="C1", mode="TL"):
    return Shipment(i, date(2024, 3, day), carrier, D(weight), D(500), A, B, mode, None, None, None, None, 2)


DS = Dataset((ship("S1", 1, 1000), ship("S2", 2, 1500), ship("S3", 9, 1000), ship("S4", 1, 1250, "C2", "LTL")),
             (RateCard("C1", "per_mile", D("2"), None, None, "TL", 2), RateCard("C2", "per_cwt", D("10"), None, None, "LTL", 3)),
             (A, B), {})
K = Knobs(circuity=1.25)


def test_identity_matches_baseline():
    base = evaluate(DS, K)
    rr = rerate(DS, K, baseline_ids=[s.id for s in DS.shipments])
    assert rr.total == base.total_model and rr.knobs == K
    assert rr.members == {"S1": ("S1",), "S2": ("S2",), "S3": ("S3",), "S4": ("S4",)}


def test_carrier_switch_and_cwt_knob():
    sc, _ = apply(DS, Scenario("s", (CarrierSwitch("C1", "C2", to_mode="LTL"),)))
    rr = rerate(sc, K)
    assert all(r.carrier_id == "C2" and r.rate_type == "per_cwt" for r in rr.rated)
    assert rr.total == D("10") * D("47.5")  # (1000+1500+1000+1250)/100 * 10
    assert rerate(sc, Knobs(circuity=1.25, cwt_round_up=True)).total == D("10") * D("48")  # 10+15+10+13


def test_consolidation_members_and_coverage():
    sc, rep = consolidate(DS, ConsolidationWindow(3, D(44000)))
    rr = rerate(sc, K, bins=rep.bins, baseline_ids=["S1", "S2", "S3", "S4"])
    assert rr.members["CONS-0001"] == ("S1", "S2") and rr.members["S3"] == ("S3",)
    assert len(rr.rated) == 3
    with pytest.raises(ValueError, match="missing=\\['S9'\\]"):
        rerate(sc, K, bins=rep.bins, baseline_ids=["S1", "S2", "S3", "S4", "S9"])
    with pytest.raises(ValueError, match="duplicate"):
        rerate(sc, K, bins=[("CONS-0001", ("S1", "S3"))], baseline_ids=["S1", "S2", "S3", "S4"])
