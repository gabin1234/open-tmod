"""Node 12 Re-rating: scenario Dataset with baseline knobs. Contract: docs/nodes/12_rerating.md"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Collection, Sequence

from tmod.baseline import Knobs
from tmod.canonical import Dataset
from tmod.rating import RatedCost, rate_all
from tmod.routing import HaversineProvider, RouteMatrix, RoutingProvider, route_matrix


@dataclass(frozen=True)
class RerateResult:
    knobs: Knobs
    rated: tuple[RatedCost, ...]
    matrix: RouteMatrix
    total: Decimal
    unrated: tuple[tuple[str, str], ...]
    members: dict[str, tuple[str, ...]]


def rerate(ds: Dataset, knobs: Knobs, bins: Sequence[tuple[str, tuple[str, ...]]] = (),
           baseline_ids: Collection[str] | None = None, providers: Sequence[RoutingProvider] | None = None
           ) -> RerateResult:
    providers = providers or [HaversineProvider(knobs.circuity, knobs.mph)]
    matrix, _ = route_matrix(ds, providers)
    rated, rep = rate_all(ds, matrix, knobs.cwt_round_up)
    cons = dict(bins)
    members = {s.id: cons.get(s.id, (s.id,)) for s in ds.shipments}
    if baseline_ids is not None:
        flat = [m for ms in members.values() for m in ms]
        if sorted(flat) != sorted(baseline_ids):
            missing = set(baseline_ids) - set(flat)
            dup = {m for m in flat if flat.count(m) > 1}
            raise ValueError(f"member map mismatch: missing={sorted(missing)} duplicate={sorted(dup)}")
    return RerateResult(knobs, rated, matrix, rep.total, rep.unrated, members)
