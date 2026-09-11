"""LMD Node 13: baseline vs scenario route KPI comparison. Contract: docs/nodes/lmd_13_14_compare_map.md"""
from __future__ import annotations

from dataclasses import dataclass

from tmod.lmd_baseline import BaselineRoutes, RouteKPI

FIELDS = ("loads", "stops", "miles", "hub_miles", "inter_stop_miles", "drive_min", "service_min", "duty_min",
          "over_work", "over_duty", "max_trucks_per_day")


@dataclass(frozen=True)
class RouteComparison:
    scenario_name: str
    baseline: RouteKPI
    scenario: RouteKPI
    delta: dict[str, float]
    delta_pct: dict[str, float]
    unrouted: tuple[str, ...]
    gate_passed: bool

    def summary(self) -> str:
        g = self.gate_passed
        head = f"scenario: {self.scenario_name}" + ("" if g else "  [distance gate not passed: deltas hidden]")
        lines = [head, f"{'kpi':<20}{'baseline':>12}{'scenario':>12}{'delta':>12}{'delta%':>10}"]
        for f in FIELDS:
            b, s = getattr(self.baseline, f), getattr(self.scenario, f)
            d = f"{self.delta[f]:+,.0f}" if g else "GATED"
            p = f"{self.delta_pct[f]:+.1f}%" if g and self.delta_pct[f] == self.delta_pct[f] else ("GATED" if not g else "-")
            lines.append(f"{f:<20}{b:>12,.0f}{s:>12,.0f}{d:>12}{p:>10}")
        if self.unrouted:
            lines.append(f"unrouted in scenario: {len(self.unrouted)}")
        return "\n".join(lines)


def compare_routes(name: str, base: BaselineRoutes, scen: BaselineRoutes, unrouted: tuple[str, ...],
                   gate_passed: bool) -> RouteComparison:
    b, s = base.kpi, scen.kpi
    delta = {f: getattr(s, f) - getattr(b, f) for f in FIELDS}
    pct = {f: (delta[f] / getattr(b, f) * 100) if getattr(b, f) else float("nan") for f in FIELDS}
    return RouteComparison(name, b, s, delta, pct, tuple(unrouted), gate_passed)
