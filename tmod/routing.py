"""Node 06 Road Routing: O-D pairs -> Route via providers. Contract: docs/nodes/06_routing.md"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

from tmod.canonical import Dataset, Location

EARTH_MILES = 3958.8


@dataclass(frozen=True)
class Route:
    miles: float
    minutes: float
    provider: str
    geometry: tuple[tuple[float, float], ...] | None = None   # v1.1: road polyline [(lat, lon), ...] when the provider has it


def decode_polyline6(s: str) -> tuple[tuple[float, float], ...]:
    """Valhalla encoded shape (precision 1e-6) -> ((lat, lon), ...)."""
    out, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        out.append((lat / 1e6, lon / 1e6))
    return tuple(out)


class RoutingProvider(Protocol):
    name: str

    def route(self, o: Location, d: Location) -> Route | None: ...


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


class HaversineProvider:
    name = "haversine"

    def __init__(self, circuity: float = 1.2, mph: float = 50.0) -> None:
        self.circuity, self.mph = circuity, mph  # ponytail: calibration knobs, tune at Node 08

    def route(self, o: Location, d: Location) -> Route | None:
        miles = haversine_miles(o.lat, o.lon, d.lat, d.lon) * self.circuity
        return Route(miles, miles / self.mph * 60, self.name)


class ValhallaProvider:
    name = "valhalla"

    def __init__(self, base_url: str = "http://localhost:8002", costing: str = "truck", timeout: float = 10) -> None:
        self.base_url, self.costing, self.timeout = base_url.rstrip("/"), costing, timeout

    def route(self, o: Location, d: Location) -> Route | None:
        body = json.dumps({"locations": [{"lat": o.lat, "lon": o.lon}, {"lat": d.lat, "lon": d.lon}],
                           "costing": self.costing, "units": "miles"}).encode()
        req = urllib.request.Request(f"{self.base_url}/route", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                trip = json.load(resp)["trip"]
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
            return None
        s = trip["summary"]
        shape = tuple(pt for leg in trip.get("legs", []) for pt in decode_polyline6(leg.get("shape", "")))
        return Route(float(s["length"]), float(s["time"]) / 60, self.name, shape or None)


RouteMatrix = dict[tuple[str, str], Route]


@dataclass(frozen=True)
class RoutingReport:
    pairs: int
    by_provider: dict[str, int]
    unrouted: tuple[tuple[str, str], ...]
    cache_hits: int


def load_cache(path: str | Path) -> RouteMatrix:
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for k, v in json.loads(p.read_text()).items():
        g = v.get("geometry")
        out[tuple(k.split("|", 1))] = Route(v["miles"], v["minutes"], v["provider"], tuple(map(tuple, g)) if g else None)
    return out


def save_cache(path: str | Path, cache: RouteMatrix) -> None:
    Path(path).write_text(json.dumps({f"{o}|{d}": asdict(r) for (o, d), r in cache.items()}, indent=0))


def route_matrix(ds: Dataset, providers: Sequence[RoutingProvider], cache: RouteMatrix | None = None
                 ) -> tuple[RouteMatrix, RoutingReport]:
    cache = cache if cache is not None else {}
    pairs = {(s.origin.key, s.dest.key): (s.origin, s.dest) for s in ds.shipments}
    matrix: RouteMatrix = {}
    by_prov: dict[str, int] = defaultdict(int)
    unrouted: list[tuple[str, str]] = []
    hits = 0
    for key, (o, d) in pairs.items():
        if key in cache:
            matrix[key] = cache[key]
            hits += 1
        elif o.key == d.key:
            matrix[key] = cache[key] = Route(0.0, 0.0, "same")
        elif None in (o.lat, o.lon, d.lat, d.lon):
            unrouted.append(key)
            continue
        else:
            r = next((r for p in providers if (r := p.route(o, d)) is not None), None)
            if r is None:
                unrouted.append(key)
                continue
            matrix[key] = cache[key] = r
        by_prov[matrix[key].provider] += 1
    return matrix, RoutingReport(len(pairs), dict(by_prov), tuple(unrouted), hits)
