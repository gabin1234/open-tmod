"""W01: engine dataclasses -> plain JSON for the frontend. Contract: docs/nodes/w01_api.md"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tmod.lmd_baseline import BaselineRoutes, RoutePlan
from tmod.lmd_compare import RouteComparison


def plan_to_json(p: RoutePlan) -> dict[str, Any]:
    return {
        "load_id": p.load_id, "day": p.day.isoformat() if p.day else None, "truck_id": p.truck_id, "pool": p.pool,
        "miles": round(p.miles, 1), "hub_miles": round(p.hub_miles, 1), "drive_min": round(p.drive_min, 1),
        "service_min": p.service_min, "duty_min": round(p.duty_min, 1), "over_work": p.over_work, "over_duty": p.over_duty,
        "late_stops": p.late_stops, "wait_min": round(p.wait_min, 1),
        "stops": [{"id": s.id, "ship_to_id": s.ship_to_id, "zone": s.zone, "lat": s.location.lat, "lon": s.location.lon,
                   "zip": s.location.zip, "service_min": s.service_min, "window": s.window, "shipments": list(s.shipments)}
                  for s in p.stops],
        "legs": [{"miles": round(l.miles, 2), "minutes": round(l.minutes, 1), "provider": l.provider,
                  "geometry": [list(q) for q in l.geometry] if l.geometry else None} for l in p.legs],
    }


def run_to_json(run_id: str, dataset: str, scenario: dict, created_at: str, cal, orep, hub, cmp: RouteComparison,
                base: BaselineRoutes, scen: BaselineRoutes) -> dict[str, Any]:
    return {
        "run_id": run_id, "dataset": dataset, "scenario": scenario, "created_at": created_at, "status": "done",
        "gate": {"passed": cal.within_tolerance, "test_gap_pct": round(cal.test_gap_pct, 2), "a": round(cal.a, 3), "b": round(cal.b, 4)},
        "optimize": {"days": orep.days, "stops": orep.stops, "routed": orep.routed, "loads": orep.loads, "unrouted": list(orep.unrouted)},
        "hub": {"lat": hub.lat, "lon": hub.lon, "zip": hub.zip},
        "kpi": {"baseline": asdict(cmp.baseline), "scenario": asdict(cmp.scenario), "delta": cmp.delta,
                "delta_pct": {k: (None if v != v else round(v, 2)) for k, v in cmp.delta_pct.items()}, "summary": cmp.summary()},
        "plans": {"baseline": [plan_to_json(p) for p in base.plans], "scenario": [plan_to_json(p) for p in scen.plans]},
    }
