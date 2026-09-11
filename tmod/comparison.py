"""Node 13 Comparison: Baseline vs Scenario KPIs, gate-aware summary. Contract: docs/nodes/13_comparison.md"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from tmod.baseline import BaselineResult
from tmod.canonical import Dataset
from tmod.rating import RatedCost
from tmod.rerating import RerateResult
from tmod.routing import RouteMatrix


@dataclass(frozen=True)
class KPI:
    shipments: int
    total_cost: Decimal
    total_miles: float
    avg_weight_lb: Decimal
    avg_utilization_pct: float | None
    avg_transit_days: float | None
    by_carrier: dict[str, Decimal]


@dataclass(frozen=True)
class ShipmentDelta:
    scenario_id: str
    members: tuple[str, ...]
    baseline_cost: Decimal | None
    scenario_cost: Decimal
    delta: Decimal | None


@dataclass(frozen=True)
class Comparison:
    scenario_name: str
    baseline: KPI
    scenario: KPI
    delta_cost: Decimal
    delta_pct: float
    per_shipment: tuple[ShipmentDelta, ...]
    gate_passed: bool

    def summary(self) -> str:
        b, s = self.baseline, self.scenario
        money = (lambda x: f"{x:,.2f}") if self.gate_passed else (lambda x: "GATED")
        pct = (lambda x: f"{x:+.2f}%") if self.gate_passed else (lambda x: "GATED")
        fmt = lambda v, f: "-" if v is None else f(v)  # noqa: E731
        lines = [f"scenario: {self.scenario_name}" + ("" if self.gate_passed else "  [Baseline gate not passed: cost figures hidden]"),
                 f"{'kpi':<20}{'baseline':>16}{'scenario':>16}",
                 f"{'shipments':<20}{b.shipments:>16}{s.shipments:>16}",
                 f"{'total_cost':<20}{money(b.total_cost):>16}{money(s.total_cost):>16}",
                 f"{'delta_cost':<20}{'':>16}{money(self.delta_cost):>16}",
                 f"{'delta_pct':<20}{'':>16}{pct(self.delta_pct):>16}",
                 f"{'total_miles':<20}{b.total_miles:>16,.0f}{s.total_miles:>16,.0f}",
                 f"{'avg_weight_lb':<20}{b.avg_weight_lb:>16,.0f}{s.avg_weight_lb:>16,.0f}",
                 f"{'avg_utilization_pct':<20}{fmt(b.avg_utilization_pct, lambda x: f'{x:.1f}'):>16}{fmt(s.avg_utilization_pct, lambda x: f'{x:.1f}'):>16}",
                 f"{'avg_transit_days':<20}{fmt(b.avg_transit_days, lambda x: f'{x:.2f}'):>16}{fmt(s.avg_transit_days, lambda x: f'{x:.2f}'):>16}"]
        return "\n".join(lines)


def kpi(ds: Dataset, rated: Sequence[RatedCost], matrix: RouteMatrix, capacity_lb: Decimal | None = None) -> KPI:
    by_id = {s.id: s for s in ds.shipments}
    ships = [by_id[r.shipment_id] for r in rated]
    n = len(ships)
    if n == 0:
        return KPI(0, Decimal(0), 0.0, Decimal(0), None, None, {})
    miles = sum((r.miles or 0.0) for r in rated)
    weights = [s.weight_lb for s in ships]
    util = float(sum(w / capacity_lb for w in weights) / n * 100) if capacity_lb else None
    transit = [(s.deliver_date - s.ship_date).days for s in ships if s.deliver_date]
    by_carrier: dict[str, Decimal] = {}
    for r in rated:
        by_carrier[r.carrier_id] = by_carrier.get(r.carrier_id, Decimal(0)) + r.total
    return KPI(n, sum((r.total for r in rated), Decimal(0)), miles, sum(weights) / n, util,
               sum(transit) / len(transit) if transit else None, by_carrier)


def compare(name: str, ds_base: Dataset, base: BaselineResult, ds_scen: Dataset, scen: RerateResult,
            gate_passed: bool, capacity_lb: Decimal | None = None) -> Comparison:
    b = kpi(ds_base, base.rated, base.matrix, capacity_lb)
    s = kpi(ds_scen, scen.rated, scen.matrix, capacity_lb)
    base_cost = {r.shipment_id: r.total for r in base.rated}
    per = []
    for r in scen.rated:
        members = scen.members.get(r.shipment_id, (r.shipment_id,))
        bc = None if any(m not in base_cost for m in members) else sum((base_cost[m] for m in members), Decimal(0))
        per.append(ShipmentDelta(r.shipment_id, members, bc, r.total, None if bc is None else r.total - bc))
    delta = s.total_cost - b.total_cost
    pct = float(delta / b.total_cost * 100) if b.total_cost else 0.0
    return Comparison(name, b, s, delta, pct, tuple(per), gate_passed)
