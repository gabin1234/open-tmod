from datetime import date
from decimal import Decimal as D

import pytest

from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.rating import rate_all, rate_shipment, select_rate
from tmod.routing import Route

A, B = Location(zip="1", lat=1.0, lon=1.0), Location(zip="2", lat=2.0, lon=2.0)


def ship(i="S1", carrier="C1", weight="1250", mode=None, o=A, d=B):
    return Shipment(i, date(2024, 1, 1), carrier, D(weight), D(100), o, d, mode, None, None, None, None, 2)


def card(carrier="C1", rt="per_mile", rate="2.5", min_charge=None, fuel=None, mode=None, row=2):
    return RateCard(carrier, rt, D(rate), D(min_charge) if min_charge else None, D(fuel) if fuel else None, mode, row)


R100 = Route(100.0, 120.0, "test")


def test_per_mile_with_fuel():
    r = rate_shipment(ship(), R100, card(fuel="20"))
    assert (r.linehaul, r.fuel, r.total, r.miles, r.min_applied) == (D("250.00"), D("50.00"), D("300.00"), 100.0, False)


def test_per_cwt():
    assert rate_shipment(ship(), None, card(rt="per_cwt", rate="12.5")).linehaul == D("156.25")
    assert rate_shipment(ship(), None, card(rt="per_cwt", rate="12.5"), cwt_round_up=True).linehaul == D("162.50")


def test_flat_and_min():
    r = rate_shipment(ship(), None, card(rt="flat", rate="300", min_charge="150"))
    assert r.linehaul == D("300.00") and not r.min_applied
    r = rate_shipment(ship(), None, card(rt="flat", rate="80", min_charge="150"))
    assert r.linehaul == D("150.00") and r.min_applied


def test_rounding_half_up():
    assert rate_shipment(ship(), Route(0.402, 0, "t"), card(rate="2.5")).linehaul == D("1.01")  # 1.005


def test_select_rate():
    cards = [card(mode=None, row=3), card(mode="LTL", row=4), card(carrier="C2", row=5), card(mode=None, row=2)]
    assert select_rate(cards, "C1", "ltl").source_row == 4
    assert select_rate(cards, "C1", "TL").source_row == 2
    assert select_rate(cards, "C1", None).source_row == 2
    assert select_rate(cards, "C9", None) is None
    assert select_rate([card(mode="LTL")], "C1", None) is None


def test_rate_all():
    ds = Dataset((ship("S1"), ship("S2", d=Location(zip="3")), ship("S3", carrier="C9"), ship("S4", carrier="C2")),
                 (card(), card(carrier="C2", rt="flat", rate="99.5")), (), {})
    matrix = {(A.key, B.key): R100}
    rated, rep = rate_all(ds, matrix)
    assert [r.shipment_id for r in rated] == ["S1", "S4"]
    assert rep.unrated == (("S2", "NO_ROUTE"), ("S3", "NO_RATE"))
    assert rep.rated == 2 and rep.total == D("349.50")


def test_per_mile_without_route_raises():
    with pytest.raises(ValueError):
        rate_shipment(ship(), None, card())
