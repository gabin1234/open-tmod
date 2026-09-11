"""LMD Node 08: evaluate given loads with providers (nearest-neighbour order). Contract: docs/nodes/lmd_08_baseline.md"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from tmod.address import normalize
from tmod.canonical import Location
from tmod.geocoding import ZipCentroidGeocoder, geocode
from tmod.ingestion import ingest
from tmod.lmd import LmdDataset, Stop, Truck, apply_geocoded, build_lmd, to_dataset, LMD_SCHEMAS
from tmod.lmd_routing import AffineHaversineProvider, Calibration, TruthProvider, calibrate, load_calibration, load_truth, save_calibration
from tmod.routing import Route, RoutingProvider
from tmod.validation import validate


@dataclass(frozen=True)
class RoutePlan:
    load_id: str
    day: date | None
    truck_id: str | None
    pool: bool
    stops: tuple[Stop, ...]
    legs: tuple[Route, ...]
    miles: float
    hub_miles: float
    drive_min: float
    service_min: int
    duty_min: float
    over_work: bool
    over_duty: bool


@dataclass(frozen=True)
class RouteKPI:
    loads: int
    stops: int
    shipments: int
    miles: float
    hub_miles: float
    inter_stop_miles: float
    drive_min: float
    service_min: int
    duty_min: float
    over_work: int
    over_duty: int
    pool_loads: int
    avg_stops_per_load: float
    avg_duty_min: float
    days: int
    max_trucks_per_day: int
    by_provider_miles: dict[str, float]

    def summary(self) -> str:
        prov = ", ".join(f"{k} {v:,.0f}mi" for k, v in self.by_provider_miles.items())
        return (f"loads {self.loads} (pool {self.pool_loads}), stops {self.stops}, shipments {self.shipments}, days {self.days}, "
                f"max trucks/day {self.max_trucks_per_day}\n"
                f"miles {self.miles:,.0f} (hub legs {self.hub_miles:,.0f}, inter-stop {self.inter_stop_miles:,.0f}) [{prov}]\n"
                f"drive {self.drive_min:,.0f} min, service {self.service_min:,} min, duty {self.duty_min:,.0f} min; "
                f"avg stops/load {self.avg_stops_per_load:.2f}, avg duty/load {self.avg_duty_min:.0f} min; "
                f"over_work {self.over_work}, over_duty {self.over_duty}")


@dataclass(frozen=True)
class BaselineRoutes:
    plans: tuple[RoutePlan, ...]
    kpi: RouteKPI
    skipped: tuple[tuple[str, str], ...]


class _Dist:
    def __init__(self, providers: Sequence[RoutingProvider]) -> None:
        self.providers, self.cache = providers, {}

    def __call__(self, o: Location, d: Location) -> Route:
        k = (o.key, d.key)
        if k not in self.cache:
            if o.key == d.key:
                self.cache[k] = Route(0.0, 0.0, "same")
            else:
                r = next((r for p in self.providers if (r := p.route(o, d)) is not None), None)
                if r is None:
                    raise ValueError(f"no provider could route {o.key} -> {d.key}")
                self.cache[k] = r
        return self.cache[k]


def sequence_nearest(hub: Location, stops: Sequence[Stop], dist: _Dist) -> tuple[tuple[Stop, ...], tuple[Route, ...]]:
    left, cur, order, legs = list(stops), hub, [], []
    while left:
        nxt = min(left, key=lambda s: (dist(cur, s.location).miles, s.id))
        legs.append(dist(cur, nxt.location))
        order.append(nxt)
        left.remove(nxt)
        cur = nxt.location
    legs.append(dist(cur, hub))
    return tuple(order), tuple(legs)


def sequence_given(hub: Location, stops: Sequence[Stop], dist: _Dist) -> tuple[tuple[Stop, ...], tuple[Route, ...]]:
    legs, cur = [], hub
    for s in stops:
        legs.append(dist(cur, s.location))
        cur = s.location
    legs.append(dist(cur, hub))
    return tuple(stops), tuple(legs)


def evaluate_loads(lmd: LmdDataset, loads: dict[str, Sequence[Stop]], providers: Sequence[RoutingProvider],
                   truck_of: dict[str, Truck] | None = None, keep_order: bool = False) -> BaselineRoutes:
    """keep_order=False: nearest-neighbour (baseline, no STOP_SEQ). True: visit in given order (optimizer output)."""
    truck_of = truck_of if truck_of is not None else {t.id: t for t in lmd.trucks}
    dflt_work, dflt_duty = int(lmd.params.get("TRUCK_WORK_MIN", 500)), int(lmd.params.get("TRUCK_DUTY_MIN", 600))
    dist = _Dist(providers)
    plans: list[RoutePlan] = []
    skipped: list[tuple[str, str]] = []
    for load_id, stops in loads.items():
        ok = [s for s in stops if s.location.lat is not None and s.location.lon is not None]
        skipped.extend((s.id, "NO_COORDS") for s in stops if s not in ok)
        if not ok:
            continue
        order, legs = (sequence_given if keep_order else sequence_nearest)(lmd.hub, ok, dist)
        truck_id = ok[0].truck_id
        truck = truck_of.get(truck_id or "")
        work_lim, duty_lim = (truck.work_min, truck.duty_min) if truck else (dflt_work, dflt_duty)
        miles = sum(l.miles for l in legs)
        drive = sum(l.minutes for l in legs)
        service = sum(s.service_min for s in order)
        plans.append(RoutePlan(load_id, ok[0].appt_dt, truck_id, truck is None, order, legs, miles,
                               legs[0].miles + legs[-1].miles, drive, service, drive + service,
                               service > work_lim, drive + service > duty_lim))
    return BaselineRoutes(tuple(plans), _kpi(plans), tuple(skipped))


def _kpi(plans: Sequence[RoutePlan]) -> RouteKPI:
    n = len(plans)
    miles = sum(p.miles for p in plans)
    hub_miles = sum(p.hub_miles for p in plans)
    by_prov: dict[str, float] = {}
    for p in plans:
        for l in p.legs:
            by_prov[l.provider] = by_prov.get(l.provider, 0.0) + l.miles
    per_day: dict[date | None, set] = {}
    for p in plans:
        per_day.setdefault(p.day, set()).add(p.truck_id or p.load_id)
    stops = sum(len(p.stops) for p in plans)
    duty = sum(p.duty_min for p in plans)
    return RouteKPI(n, stops, sum(len(s.shipments) for p in plans for s in p.stops), miles, hub_miles, miles - hub_miles,
                    sum(p.drive_min for p in plans), sum(p.service_min for p in plans), duty,
                    sum(p.over_work for p in plans), sum(p.over_duty for p in plans), sum(p.pool for p in plans),
                    stops / n if n else 0.0, duty / n if n else 0.0, len(per_day),
                    max((len(v) for v in per_day.values()), default=0), by_prov)


def baseline(lmd: LmdDataset, providers: Sequence[RoutingProvider]) -> BaselineRoutes:
    return evaluate_loads(lmd, lmd.baseline_loads(), providers)


def prepare_lmd(folder: str | Path) -> tuple[LmdDataset, list[RoutingProvider], Calibration]:
    folder = Path(folder)
    names = [n for n in ("shipments", "trucks", "zone_zip", "params") if (folder / f"{n}.csv").exists()]
    tables = ingest({n: folder / f"{n}.csv" for n in names})
    rep = validate(tables, LMD_SCHEMAS)
    lmd = build_lmd(tables, rep)
    ds, _ = normalize(to_dataset(lmd))
    ds, _ = geocode(ds, [ZipCentroidGeocoder()])
    lmd = apply_geocoded(lmd, ds)
    truth = load_truth(folder / "distance_truth.csv") if (folder / "distance_truth.csv").exists() else {}
    cpath = folder / "calibration.json"
    if cpath.exists():
        cal = load_calibration(cpath)
    else:
        with open(folder / "distance_truth.csv", newline="") as f:
            weights = {(r["hub_zip"], r["zip"]): int(r["n_loads"]) for r in csv.DictReader(f)}
        cal = calibrate(Location(zip=lmd.hub.zip), truth, weights=weights)
        save_calibration(cpath, cal)
    providers: list[RoutingProvider] = [TruthProvider(truth, cal.mph), AffineHaversineProvider(cal.a, cal.b, cal.mph)]
    return lmd, providers, cal


if __name__ == "__main__":
    lmd, providers, cal = prepare_lmd(sys.argv[1])
    res = baseline(lmd, providers)
    print(f"calibration a={cal.a:.2f} b={cal.b:.3f} mph={cal.mph} gate={'PASS' if cal.within_tolerance else 'FAIL'} (test gap {cal.test_gap_pct:+.2f}%)")
    print(res.kpi.summary())
    if res.skipped:
        print(f"skipped {len(res.skipped)}: {res.skipped[:5]}")
    per_day: dict = {}
    for p in res.plans:
        per_day.setdefault(p.day, []).append(p)
    for d in sorted(per_day, key=lambda x: (x is None, x)):
        ps = per_day[d]
        print(f"  {d}: loads {len(ps)}, stops {sum(len(p.stops) for p in ps)}, miles {sum(p.miles for p in ps):.0f}, "
              f"duty {sum(p.duty_min for p in ps):.0f} min, over {sum(p.over_duty for p in ps)}")
