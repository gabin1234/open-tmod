"""LMD Node 06: distance providers + calibration gate. Contract: docs/nodes/lmd_06_distance.md"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tmod.canonical import Location
from tmod.geocoding import ZipCentroidGeocoder
from tmod.routing import Route, haversine_miles

BANDS = (("0-10", 0, 10), ("10-25", 10, 25), ("25-50", 25, 50), ("50-100", 50, 100), ("100+", 100, 1e9))


class AffineHaversineProvider:
    name = "affine_haversine"

    def __init__(self, a: float, b: float, mph: float = 30.0) -> None:
        self.a, self.b, self.mph = a, b, mph

    def route(self, o: Location, d: Location) -> Route | None:
        miles = max(self.a + self.b * haversine_miles(o.lat, o.lon, d.lat, d.lon), 0.5)
        return Route(miles, miles / self.mph * 60, self.name)


class TruthProvider:
    name = "truth"

    def __init__(self, truth: dict[tuple[str, str], float], mph: float = 30.0) -> None:
        self.truth, self.mph = truth, mph

    def route(self, o: Location, d: Location) -> Route | None:
        if not o.zip or not d.zip:
            return None
        miles = self.truth.get((o.zip, d.zip), self.truth.get((d.zip, o.zip)))
        return None if miles is None else Route(miles, miles / self.mph * 60, self.name)


def load_truth(path: str | Path) -> dict[tuple[str, str], float]:
    with open(path, newline="") as f:
        return {(r["hub_zip"], r["zip"]): float(r["median_miles"]) for r in csv.DictReader(f)}


@dataclass(frozen=True)
class Calibration:
    a: float
    b: float
    mph: float
    n_zips: int
    train_gap_pct: float
    test_gap_pct: float
    test_mape_pct: float
    band_gap_pct: dict[str, float]
    within_tolerance: bool


def _wls(pts: list[tuple[float, float, int]]) -> tuple[float, float]:
    w = sum(n for _, _, n in pts)
    mx = sum(gc * n for gc, _, n in pts) / w
    my = sum(t * n for _, t, n in pts) / w
    sxx = sum(n * (gc - mx) ** 2 for gc, _, n in pts)
    b = sum(n * (gc - mx) * (t - my) for gc, t, n in pts) / sxx if sxx else 0.0
    return my - b * mx, b


def _gap(a: float, b: float, pts) -> float:
    tot_t = sum(t * n for _, t, n in pts)
    return (sum((a + b * gc) * n for gc, _, n in pts) - tot_t) / tot_t * 100 if tot_t else 0.0


def calibrate(hub: Location, truth: dict[tuple[str, str], float], geocoder=None, tolerance: float = 2.0,
              mph: float = 30.0, weights: dict[tuple[str, str], int] | None = None) -> Calibration:
    geocoder = geocoder or ZipCentroidGeocoder()
    hub_pt = geocoder.geocode(hub) if hub.lat is None else hub
    pts: list[tuple[float, float, int]] = []
    for (_, z), miles in sorted(truth.items()):
        p = geocoder.geocode(Location(zip=z))
        if p is None:
            continue
        gc = haversine_miles(hub_pt.lat, hub_pt.lon, p.lat, p.lon)
        if gc >= 1:
            pts.append((gc, miles, (weights or {}).get((_, z), 1)))
    train, test = pts[0::2], pts[1::2] or pts[0::2]
    a, b = _wls(train)
    mape = sum(abs(a + b * gc - t) / t for gc, t, _ in test) / len(test) * 100
    bands = {name: round(_gap(a, b, sub), 2) for name, lo, hi in BANDS if (sub := [p for p in test if lo <= p[0] < hi])}
    test_gap = _gap(a, b, test)
    return Calibration(a, b, mph, len(pts), _gap(a, b, train), test_gap, mape, bands, abs(test_gap) <= tolerance)


def save_calibration(path: str | Path, cal: Calibration) -> None:
    Path(path).write_text(json.dumps(asdict(cal), indent=1))


def load_calibration(path: str | Path) -> Calibration:
    return Calibration(**json.loads(Path(path).read_text()))


def validate_provider(provider, hub: Location, truth: dict[tuple[str, str], float], geocoder=None,
                      weights: dict[tuple[str, str], int] | None = None, sample: int | None = None) -> dict:
    """Compare any RoutingProvider's hub->zip miles against the truth table. Returns gap/MAPE and a per-band gap."""
    geocoder = geocoder or ZipCentroidGeocoder()
    hub_pt = hub if hub.lat is not None else geocoder.geocode(hub)
    hub_loc = Location(zip=hub.zip, lat=hub_pt.lat, lon=hub_pt.lon)
    rows = []
    for (h, z), miles in sorted(truth.items())[: sample or None]:
        p = geocoder.geocode(Location(zip=z))
        if p is None:
            continue
        r = provider.route(hub_loc, Location(zip=z, lat=p.lat, lon=p.lon))
        if r is None or miles <= 0:
            continue
        rows.append((haversine_miles(hub_pt.lat, hub_pt.lon, p.lat, p.lon), r.miles, miles, (weights or {}).get((h, z), 1)))
    if not rows:
        return {"n": 0}
    tot_m = sum(m * n for _, m, _, n in rows)
    tot_t = sum(t * n for _, _, t, n in rows)
    bands = {}
    for name, lo, hi in BANDS:
        sub = [x for x in rows if lo <= x[0] < hi]
        if sub:
            bands[name] = round((sum(m * n for _, m, _, n in sub) - sum(t * n for _, _, t, n in sub)) / sum(t * n for _, _, t, n in sub) * 100, 2)
    return {"n": len(rows), "gap_pct": round((tot_m - tot_t) / tot_t * 100, 2),
            "mape_pct": round(sum(abs(m - t) / t for _, m, t, _ in rows) / len(rows) * 100, 1), "band_gap_pct": bands}
