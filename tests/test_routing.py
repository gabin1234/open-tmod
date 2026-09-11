import io
import json
from datetime import date
from decimal import Decimal

import pytest

import tmod.routing as routing
from tmod.canonical import Dataset, Location, RateCard, Shipment
from tmod.routing import HaversineProvider, Route, ValhallaProvider, haversine_miles, load_cache, route_matrix, save_cache

CHI = Location(zip="60601", lat=41.8781, lon=-87.6298)
NYC = Location(zip="10001", lat=40.7128, lon=-74.0060)
NOGEO = Location(zip="00099")


def _ds(*pairs):
    ships = tuple(Shipment(f"S{i}", date(2024, 1, 1), "C1", Decimal(1), Decimal(1), o, d,
                           None, None, None, None, None, 2) for i, (o, d) in enumerate(pairs))
    return Dataset(ships, (RateCard("C1", "flat", Decimal(1), None, None, None, 2),), (), {})


def test_haversine():
    assert abs(haversine_miles(CHI.lat, CHI.lon, NYC.lat, NYC.lon) - 711) < 5
    r = HaversineProvider(circuity=1.2).route(CHI, NYC)
    assert abs(r.miles - 711 * 1.2) < 6 and abs(r.minutes - r.miles / 50 * 60) < 1e-9 and r.provider == "haversine"


class Fixed:
    def __init__(self, name, result):
        self.name, self.result, self.calls = name, result, 0

    def route(self, o, d):
        self.calls += 1
        return self.result


def test_matrix_order_dedupe_unrouted_cache(tmp_path):
    ds = _ds((CHI, NYC), (CHI, NYC), (NYC, CHI), (CHI, NOGEO), (CHI, CHI))
    none, hav = Fixed("none", None), HaversineProvider()
    cache = {}
    m, rep = route_matrix(ds, [none, hav], cache)
    assert rep.pairs == 4 and none.calls == 2
    assert rep.by_provider == {"haversine": 2, "same": 1}
    assert rep.unrouted == ((CHI.key, NOGEO.key),) and (CHI.key, NOGEO.key) not in m
    assert m[(CHI.key, CHI.key)] == Route(0.0, 0.0, "same")
    assert rep.cache_hits == 0

    save_cache(tmp_path / "r.json", cache)
    c2 = load_cache(tmp_path / "r.json")
    assert c2 == cache and len(c2) == 3
    m2, rep2 = route_matrix(ds, [Fixed("x", Route(1, 1, "x"))], c2)
    assert rep2.cache_hits == 3 and m2 == m
    assert load_cache(tmp_path / "none.json") == {}


def test_valhalla(monkeypatch):
    payload = {"trip": {"summary": {"length": 790.5, "time": 45000}}}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return Resp(json.dumps(payload).encode())

    monkeypatch.setattr(routing.urllib.request, "urlopen", fake_urlopen)
    r = ValhallaProvider("http://v:8002/").route(CHI, NYC)
    assert r == Route(790.5, 750.0, "valhalla")
    assert seen["url"] == "http://v:8002/route" and seen["body"]["costing"] == "truck"

    def boom(req, timeout):
        raise routing.urllib.error.URLError("down")

    monkeypatch.setattr(routing.urllib.request, "urlopen", boom)
    assert ValhallaProvider().route(CHI, NYC) is None
