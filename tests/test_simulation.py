from datetime import date
from decimal import Decimal as D

from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.routing import Route
from tmod.simulation import SimConfig, simulate, transit_days

A, B, C = Location(zip="1", lat=0.0, lon=0.0), Location(zip="2", lat=1.0, lon=1.0), Location(zip="3")


def ship(i, d, deliver=None):
    return Shipment(i, date(2024, 3, 1), "C1", D(1), D(1), A, d, None, None, deliver, None, None, 2)


def test_transit_days():
    assert transit_days(1320, 11) == 2
    assert transit_days(0, 11) == 1
    assert transit_days(661, 11) == 2


def test_simulate_stub():
    ds = Dataset((ship("S1", B), ship("S2", B, date(2024, 3, 9)), ship("S3", C)),
                 (RateCard("C1", "flat", D(1), None, None, None, 2),), (A, B, C), {})
    matrix = {(A.key, B.key): Route(1000.0, 1320.0, "t")}
    out, rep = simulate(ds, matrix, SimConfig(drive_hours_per_day=11))
    assert out.shipments[0].deliver_date == date(2024, 3, 3)
    assert out.shipments[1].deliver_date == date(2024, 3, 9)
    assert out.shipments[2].deliver_date is None
    assert (rep.shipments, rep.transit_days_filled, rep.avg_transit_days, rep.engine) == (3, 1, 2.0, "deterministic-stub")
    assert out.rates is ds.rates and out.locations is ds.locations
