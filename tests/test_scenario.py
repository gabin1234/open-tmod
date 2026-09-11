import json
from datetime import date
from decimal import Decimal as D

import pytest

from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.scenario import ApplyReport, CarrierSwitch, ConsolidationWindow, Scenario, apply, load_scenario

A, B, C = Location(zip="60601"), Location(zip="10001"), Location(zip="30301")


def ship(i, carrier, o, d, mode="TL"):
    return Shipment(i, date(2024, 1, 1), carrier, D(1000), D(100), o, d, mode, None, None, None, None, 2)


DS = Dataset((ship("S1", "C1", A, B), ship("S2", "C1", A, C), ship("S3", "C2", A, B, "LTL")),
             (RateCard("C1", "per_mile", D(2), None, None, "TL", 2), RateCard("C2", "per_cwt", D(18), None, None, "LTL", 3)),
             (A, B, C), {})


def test_switch_all_lanes_with_mode():
    out, rep = apply(DS, Scenario("s", (CarrierSwitch("C1", "C2", to_mode="LTL"),)))
    assert [(s.carrier_id, s.mode) for s in out.shipments] == [("C2", "LTL"), ("C2", "LTL"), ("C2", "LTL")]
    assert rep == ApplyReport((("S1", "C1->C2"), ("S2", "C1->C2")), ())
    assert out.rates is DS.rates and out.locations is DS.locations
    assert DS.shipments[0].carrier_id == "C1"  # original untouched


def test_switch_lane_filter_keeps_mode():
    out, rep = apply(DS, Scenario("s", (CarrierSwitch("C1", "C2", lanes=frozenset({("60601", "30301")})),)))
    assert [s.carrier_id for s in out.shipments] == ["C1", "C2", "C2"]
    assert out.shipments[1].mode == "TL"
    assert rep.changed == (("S2", "C1->C2"),)


def test_consolidation_pending_and_errors():
    cw = ConsolidationWindow(3, D(44000))
    out, rep = apply(DS, Scenario("s", (cw,)))
    assert out.shipments == DS.shipments and rep.pending == (cw,)
    with pytest.raises(ValueError):
        apply(DS, Scenario("s", (CarrierSwitch("C1", "C9"),)))
    with pytest.raises(ValueError):
        apply(DS, Scenario("s", (ConsolidationWindow(0, D(1)),)))


def test_load_scenario(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"name": "sw", "rules": [
        {"type": "carrier_switch", "from_carrier": "C1", "to_carrier": "C2", "to_mode": "LTL", "lanes": [["60601", "10001"]]},
        {"type": "consolidation_window", "days": 3, "max_weight_lb": 44000}]}))
    sc = load_scenario(p)
    assert sc == Scenario("sw", (CarrierSwitch("C1", "C2", "LTL", frozenset({("60601", "10001")})),
                                 ConsolidationWindow(3, D("44000"))))
    p.write_text(json.dumps({"name": "x", "rules": [{"type": "nope"}]}))
    with pytest.raises(ValueError):
        load_scenario(p)
