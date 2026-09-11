"""Node 11 Simulation: POC deterministic pass-through stub. Contract: docs/nodes/11_simulation.md"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import timedelta

from tmod.canonical import Dataset
from tmod.routing import RouteMatrix


@dataclass(frozen=True)
class SimConfig:
    drive_hours_per_day: float = 11.0
    seed: int = 0


@dataclass(frozen=True)
class SimReport:
    shipments: int
    transit_days_filled: int
    avg_transit_days: float
    engine: str


def transit_days(minutes: float, drive_hours_per_day: float) -> int:
    return max(1, math.ceil(minutes / (drive_hours_per_day * 60)))


def simulate(ds: Dataset, matrix: RouteMatrix, config: SimConfig = SimConfig()) -> tuple[Dataset, SimReport]:
    # ponytail: deterministic stub; swap body for SimPy when service KPIs need distributions
    out = []
    days: list[int] = []
    filled = 0
    for s in ds.shipments:
        r = matrix.get((s.origin.key, s.dest.key))
        if r is None:
            out.append(s)
            continue
        d = transit_days(r.minutes, config.drive_hours_per_day)
        days.append(d)
        if s.deliver_date is None:
            s = replace(s, deliver_date=s.ship_date + timedelta(days=d))
            filled += 1
        out.append(s)
    avg = sum(days) / len(days) if days else 0.0
    return replace(ds, shipments=tuple(out)), SimReport(len(out), filled, avg, "deterministic-stub")
