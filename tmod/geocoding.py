"""Node 05 Geocoding: fill Location lat/lon via providers + cache. Contract: docs/nodes/05_geocoding.md"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol, Sequence

from tmod.canonical import Dataset, Location

DEFAULT_ZIP_TABLE = Path(__file__).resolve().parent.parent / "data" / "zip_centroids.csv"


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    precision: str


class Geocoder(Protocol):
    name: str

    def geocode(self, loc: Location) -> GeoResult | None: ...


class ZipCentroidGeocoder:
    name = "zip_centroid"

    def __init__(self, path: str | Path = DEFAULT_ZIP_TABLE) -> None:
        self.exact: dict[str, tuple[float, float]] = {}
        acc: dict[str, list[tuple[float, float]]] = defaultdict(list)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                pt = (float(row["lat"]), float(row["lon"]))
                self.exact[row["zip"]] = pt
                acc[row["zip"][:3]].append(pt)
        self.prefix = {k: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for k, v in acc.items()}

    def geocode(self, loc: Location) -> GeoResult | None:
        z = loc.zip
        if not z:
            return None
        if z in self.exact:
            return GeoResult(*self.exact[z], "zip")
        if z[:3] in self.prefix:
            return GeoResult(*self.prefix[z[:3]], "zip3")
        return None


@dataclass(frozen=True)
class GeocodeReport:
    total: int
    by_precision: dict[str, int]
    ungeocoded: tuple[str, ...]
    cache_hits: int


def load_cache(path: str | Path) -> dict[str, GeoResult]:
    p = Path(path)
    if not p.exists():
        return {}
    return {k: GeoResult(**v) for k, v in json.loads(p.read_text()).items()}


def save_cache(path: str | Path, cache: dict[str, GeoResult]) -> None:
    Path(path).write_text(json.dumps({k: asdict(v) for k, v in cache.items()}, indent=0))


def geocode(ds: Dataset, providers: Sequence[Geocoder], cache: dict[str, GeoResult] | None = None
            ) -> tuple[Dataset, GeocodeReport]:
    cache = cache if cache is not None else {}
    resolved: dict[str, GeoResult | None] = {}
    by_prec: dict[str, int] = defaultdict(int)
    hits = 0

    for loc in ds.locations:
        if loc.lat is not None and loc.lon is not None:
            resolved[loc.key] = GeoResult(loc.lat, loc.lon, "given")
        elif loc.key in cache:
            resolved[loc.key] = cache[loc.key]
            hits += 1
        else:
            r = next((g for p in providers if (g := p.geocode(loc)) is not None), None)
            resolved[loc.key] = r
            if r is not None:
                cache[loc.key] = r
        if resolved[loc.key] is not None:
            by_prec[resolved[loc.key].precision] += 1

    def fill(loc: Location) -> Location:
        r = resolved.get(loc.key)
        return loc if r is None or loc.lat is not None else replace(loc, lat=r.lat, lon=r.lon)

    shipments = tuple(replace(s, origin=fill(s.origin), dest=fill(s.dest)) for s in ds.shipments)
    named = {k: fill(v) for k, v in ds.named_locations.items()}
    uniq: dict[str, Location] = {}
    for s in shipments:
        uniq.setdefault(s.origin.key, s.origin)
        uniq.setdefault(s.dest.key, s.dest)
    out = Dataset(shipments, ds.rates, tuple(uniq.values()), named)
    ungeo = tuple(k for k, r in resolved.items() if r is None)
    return out, GeocodeReport(len(ds.locations), dict(by_prec), ungeo, hits)
