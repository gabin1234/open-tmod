from datetime import date
from decimal import Decimal as D

from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.optimization import consolidate, optimize, pack_bins
from tmod.scenario import ConsolidationWindow

A, B, C = Location(zip="60601", lat=41.88, lon=-87.63), Location(zip="10001", lat=40.71, lon=-74.0), Location(zip="30301", lat=33.7, lon=-84.4)


def ship(i, day, weight, carrier="C1", o=A, d=B, pieces=1):
    return Shipment(i, date(2024, 3, day), carrier, D(weight), D(weight) / 10, o, d, "TL", None, None, pieces, None, 2)


def test_pack_bins():
    bins, opt = pack_bins([6, 5, 4, 3, 2], 10)
    assert len(bins) == 2 and opt
    assert sorted(i for b in bins for i in b) == [0, 1, 2, 3, 4]
    assert all(sum([6, 5, 4, 3, 2][i] for i in b) <= 10 for b in bins)
    assert pack_bins([1, 2], 10) == ([[0, 1]], True)
    assert pack_bins([], 10) == ([], True)


def test_consolidate_window_and_lanes():
    ships = (ship("S1", 1, 10000), ship("S2", 2, 12000), ship("S3", 3, 8000),      # within 3 days, sum 30000
             ship("S4", 6, 5000),                                                   # outside window
             ship("S5", 1, 5000, carrier="C2"),                                     # other carrier
             ship("S6", 1, 5000, d=C), ship("S7", 2, 6000, d=C, pieces=None))       # other lane, pieces None
    ds = Dataset(ships, (RateCard("C1", "flat", D(1), None, None, None, 2),), (A, B, C), {})
    out, rep = consolidate(ds, ConsolidationWindow(3, D(44000)))
    ids = [s.id for s in out.shipments]
    assert ids == ["CONS-0001", "S4", "S5", "CONS-0002"]
    c1 = out.shipments[0]
    assert c1.weight_lb == D(30000) and c1.actual_cost == D(3000) and c1.ship_date == date(2024, 3, 1) and c1.pieces == 3
    assert out.shipments[3].pieces is None
    assert rep.bins == (("CONS-0001", ("S1", "S2", "S3")), ("CONS-0002", ("S6", "S7")))
    assert (rep.shipments_before, rep.shipments_after, rep.solver_calls) == (7, 4, 0)
    assert out.rates is ds.rates and out.locations is ds.locations


def test_consolidate_capacity_and_oversize():
    ships = (ship("S1", 1, 30000), ship("S2", 1, 30000), ship("S3", 1, 10000), ship("S4", 1, 50000))
    ds = Dataset(ships, (), (A, B), {})
    out, rep = consolidate(ds, ConsolidationWindow(2, D(44000)))
    weights = sorted(s.weight_lb for s in out.shipments)
    assert weights == [D(30000), D(40000), D(50000)]
    assert rep.oversize == ("S4",) and rep.solver_calls == 1 and rep.solver_optimal == 1
    assert len(rep.bins) == 1 and set(rep.bins[0][1]) == {"S3", "S1"} or set(rep.bins[0][1]) == {"S3", "S2"}


def test_optimize_dispatch():
    ds = Dataset((ship("S1", 1, 100), ship("S2", 1, 100)), (), (A, B), {})
    same, reps = optimize(ds, [])
    assert same is ds and reps == ()
    out, reps = optimize(ds, [ConsolidationWindow(1, D(1000))])
    assert len(out.shipments) == 1 and len(reps) == 1
