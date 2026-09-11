"""Node 10 Optimization: shipment consolidation via CP-SAT bin packing. Contract: docs/nodes/10_optimization.md"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from ortools.sat.python import cp_model

from tmod.canonical import Dataset, Shipment
from tmod.scenario import ConsolidationWindow, Rule


def pack_bins(weights: Sequence[int], capacity: int, time_limit_s: float = 5.0) -> tuple[list[list[int]], bool]:
    """Min-bin packing. Returns (bins as index lists, optimal?)."""
    n = len(weights)
    if n == 0:
        return [], True
    if sum(weights) <= capacity:
        return [list(range(n))], True
    m = cp_model.CpModel()
    x = [[m.NewBoolVar(f"x{i}_{b}") for b in range(n)] for i in range(n)]
    y = [m.NewBoolVar(f"y{b}") for b in range(n)]
    for i in range(n):
        m.AddExactlyOne(x[i])
    for b in range(n):
        m.Add(sum(weights[i] * x[i][b] for i in range(n)) <= capacity * y[b])
        if b:
            m.AddImplication(y[b], y[b - 1])  # symmetry: use bins in order
    m.Minimize(sum(y))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"bin packing failed: {solver.StatusName(status)}")
    bins = [[i for i in range(n) if solver.Value(x[i][b])] for b in range(n) if solver.Value(y[b])]
    return [b for b in bins if b], status == cp_model.OPTIMAL


@dataclass(frozen=True)
class ConsolidationReport:
    shipments_before: int
    shipments_after: int
    bins: tuple[tuple[str, tuple[str, ...]], ...]
    oversize: tuple[str, ...]
    solver_calls: int
    solver_optimal: int


def _sum_opt(vals):
    vals = list(vals)
    return None if any(v is None for v in vals) else sum(vals)


def _merge(cons_id: str, members: list[Shipment]) -> Shipment:
    first = members[0]
    deliver = [s.deliver_date for s in members if s.deliver_date]
    return replace(first, id=cons_id, ship_date=min(s.ship_date for s in members),
                   weight_lb=sum(s.weight_lb for s in members), actual_cost=sum(s.actual_cost for s in members),
                   deliver_date=max(deliver) if deliver else None,
                   pieces=_sum_opt(s.pieces for s in members), pallets=_sum_opt(s.pallets for s in members))


def consolidate(ds: Dataset, window: ConsolidationWindow, time_limit_s: float = 5.0
                ) -> tuple[Dataset, ConsolidationReport]:
    cap = int(window.max_weight_lb)
    lanes: dict[tuple, list[Shipment]] = {}
    for s in ds.shipments:
        lanes.setdefault((s.origin.key, s.dest.key, s.carrier_id, s.mode), []).append(s)

    replacement: dict[str, Shipment] = {}   # first member id -> consolidated shipment
    absorbed: set[str] = set()
    bins_out: list[tuple[str, tuple[str, ...]]] = []
    oversize: list[str] = []
    calls = optimal = 0
    seq = 0

    for group in lanes.values():
        group.sort(key=lambda s: (s.ship_date, s.source_row))
        i = 0
        while i < len(group):
            end = group[i].ship_date + timedelta(days=window.days)
            win = [s for s in group[i:] if s.ship_date < end]
            i += len(win)
            fit = [s for s in win if int(s.weight_lb) <= cap]
            oversize.extend(s.id for s in win if int(s.weight_lb) > cap)
            if len(fit) < 2:
                continue
            need_solver = sum(int(s.weight_lb) for s in fit) > cap
            bins, opt = pack_bins([int(s.weight_lb) for s in fit], cap, time_limit_s)
            if need_solver:
                calls += 1
                optimal += opt
            for b in bins:
                if len(b) < 2:
                    continue
                members = [fit[k] for k in b]
                seq += 1
                cid = f"CONS-{seq:04d}"
                replacement[members[0].id] = _merge(cid, members)
                absorbed.update(s.id for s in members[1:])
                bins_out.append((cid, tuple(s.id for s in members)))

    shipments = tuple(replacement.get(s.id, s) for s in ds.shipments if s.id not in absorbed)
    return replace(ds, shipments=shipments), ConsolidationReport(
        len(ds.shipments), len(shipments), tuple(bins_out), tuple(oversize), calls, optimal)


def optimize(ds: Dataset, pending: Sequence[Rule], time_limit_s: float = 5.0
             ) -> tuple[Dataset, tuple[ConsolidationReport, ...]]:
    reports: list[ConsolidationReport] = []
    for rule in pending:
        if isinstance(rule, ConsolidationWindow):
            ds, rep = consolidate(ds, rule, time_limit_s)
            reports.append(rep)
        else:
            raise ValueError(f"rule not executable in Node 10: {rule!r}")
    return ds, tuple(reports)
