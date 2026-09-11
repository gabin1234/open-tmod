from datetime import date
from decimal import Decimal

from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.geocoding import GeoResult, ZipCentroidGeocoder, geocode, load_cache, save_cache

ZIPS = ZipCentroidGeocoder()


def _ds(*pairs):
    ships = tuple(Shipment(f"S{i}", date(2024, 1, 1), "C1", Decimal(1), Decimal(1), o, d,
                           None, None, None, None, None, 2) for i, (o, d) in enumerate(pairs))
    uniq = {}
    for s in ships:
        uniq.setdefault(s.origin.key, s.origin)
        uniq.setdefault(s.dest.key, s.dest)
    return Dataset(ships, (RateCard("C1", "flat", Decimal(1), None, None, None, 2),), tuple(uniq.values()), {})


def test_zip_provider():
    r = ZIPS.geocode(Location(zip="60601"))
    assert r.precision == "zip" and 41.8 < r.lat < 41.9 and -87.7 < r.lon < -87.6
    r3 = ZIPS.geocode(Location(zip="60699"))
    assert r3.precision == "zip3" and 41.5 < r3.lat < 42.2
    assert ZIPS.geocode(Location(zip="00099")) is None
    assert ZIPS.geocode(Location(address="x")) is None


class Counting:
    name = "counting"

    def __init__(self, result=None):
        self.calls, self.result = 0, result

    def geocode(self, loc):
        self.calls += 1
        return self.result


def test_geocode_dataset_given_cache_and_fallback(tmp_path):
    given = Location(zip="10001", lat=40.75, lon=-73.99)
    ds = _ds((Location(zip="60601"), given), (Location(zip="60601"), Location(zip="00099")))
    first = Counting()
    cache = {}
    out, rep = geocode(ds, [first, ZIPS], cache)
    assert first.calls == 2  # 60601 once (deduped), 00099 once; given skipped
    assert rep.total == 3 and rep.by_precision == {"zip": 1, "given": 1}
    assert rep.ungeocoded == ("zip:00099",) and rep.cache_hits == 0
    o = out.shipments[0].origin
    assert o.lat is not None and o.key.startswith("ll:") and out.shipments[1].origin == o
    assert out.shipments[1].dest.lat is None
    assert out.shipments[0].dest == given
    assert len(out.locations) == 3

    save_cache(tmp_path / "c.json", cache)
    cache2 = load_cache(tmp_path / "c.json")
    assert cache2 == cache and set(cache2) == {"zip:60601"}
    second = Counting()
    _, rep2 = geocode(ds, [second], cache2)
    assert rep2.cache_hits == 1 and second.calls == 1  # only 00099 re-tried
    assert load_cache(tmp_path / "nope.json") == {}


def test_provider_order():
    ds = _ds((Location(zip="60601"), Location(zip="10001")))
    fixed = Counting(GeoResult(1.0, 2.0, "fake"))
    out, rep = geocode(ds, [Counting(), fixed])
    assert rep.by_precision == {"fake": 2} and out.shipments[0].origin.lat == 1.0
