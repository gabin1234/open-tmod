"""LMD Node 09/10: scenario rules + daily VRP (OR-Tools routing). Contract: docs/nodes/lmd_09_10_scenario_vrp.md"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from tmod.lmd import LmdDataset, Stop
from tmod.lmd_baseline import _Dist, hhmm, window
from tmod.routing import RoutingProvider


@dataclass(frozen=True)
class LmdScenario:
    name: str
    trucks: int | None = None
    work_min: int | None = None
    duty_min: int | None = None
    stop_pool: str = "baseline"
    zone_penalty_min: int = 0
    time_limit_s: float = 5.0
    use_windows: bool = False          # v1.1: enforce stop appt_window + truck shift as a time dimension


def load_lmd_scenario(path: str | Path) -> LmdScenario:
    return LmdScenario(**json.loads(Path(path).read_text()))


@dataclass(frozen=True)
class OptimizeReport:
    days: int
    stops: int
    routed: int
    unrouted: tuple[str, ...]
    loads: int
    solver_status: dict[str, int]


def _limits(lmd: LmdDataset, sc: LmdScenario) -> tuple[int, int, int, list[str]]:
    trucks = list(lmd.trucks)
    n = sc.trucks or len(trucks) or int(lmd.params.get("TRUCK_CNT", 10))
    work = sc.work_min or (trucks[0].work_min if trucks else int(lmd.params.get("TRUCK_WORK_MIN", 500)))
    duty = sc.duty_min or (trucks[0].duty_min if trucks else int(lmd.params.get("TRUCK_DUTY_MIN", 600)))
    ids = [t.id for t in trucks[:n]] + [f"V{k+1:02d}" for k in range(len(trucks), n)]
    return n, work, duty, ids


def optimize_day(lmd: LmdDataset, stops: Sequence[Stop], providers: Sequence[RoutingProvider], sc: LmdScenario,
                 day: date | None = None) -> tuple[dict[str, tuple[Stop, ...]], tuple[str, ...]]:
    stops = [s for s in stops if s.location.lat is not None and s.location.lon is not None]
    if not stops:
        return {}, ()
    n_veh, work, duty, ids = _limits(lmd, sc)
    dist = _Dist(providers)
    locs = [lmd.hub] + [s.location for s in stops]
    service = [0] + [s.service_min for s in stops]
    zones = [None] + [s.zone for s in stops]
    N = len(locs)
    drive = [[0 if i == j else math.ceil(dist(locs[i], locs[j]).minutes) for j in range(N)] for i in range(N)]
    miles = [[0 if i == j else int(round(dist(locs[i], locs[j]).miles * 100)) for j in range(N)] for i in range(N)]

    mgr = pywrapcp.RoutingIndexManager(N, n_veh, 0)
    rt = pywrapcp.RoutingModel(mgr)

    def cost_cb(a, b):
        i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
        pen = sc.zone_penalty_min * 100 if sc.zone_penalty_min and i and j and zones[i] != zones[j] else 0
        return miles[i][j] + pen

    def duty_cb(a, b):
        i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
        return drive[i][j] + service[j]

    def work_cb(a, b):
        return service[mgr.IndexToNode(b)]

    rt.SetArcCostEvaluatorOfAllVehicles(rt.RegisterTransitCallback(cost_cb))
    if sc.use_windows:
        # time: cumul(j) = arrival at j. transit = service(i) + drive(i,j); slack = waiting. capacity = duty limit.
        def time_cb(a, b):
            i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
            return service[i] + drive[i][j]

        rt.AddDimension(rt.RegisterTransitCallback(time_cb), duty, duty, True, "time")
        tdim = rt.GetDimensionOrDie("time")
        start = hhmm(lmd.trucks[0].shift_start if lmd.trucks else None, 480)
        for node in range(1, N):
            w = window(stops[node - 1].window)
            if w:
                tdim.CumulVar(mgr.NodeToIndex(node)).SetRange(max(0, w[0] - start), max(0, w[1] - start))
        tdim.SetSpanCostCoefficientForAllVehicles(1)   # discourage waiting
    else:
        rt.AddDimension(rt.RegisterTransitCallback(duty_cb), 0, duty, True, "duty")
    rt.AddDimension(rt.RegisterTransitCallback(work_cb), 0, work, True, "work")
    rt.SetFixedCostOfAllVehicles(1_000_000)  # ponytail: vehicle count dominates miles; tune if miles matter more
    for node in range(1, N):
        rt.AddDisjunction([mgr.NodeToIndex(node)], 10_000_000)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(min(sc.time_limit_s, 1 + 0.3 * len(stops)) * 1000))
    sol = rt.SolveWithParameters(params)
    if sol is None:
        return {}, tuple(s.id for s in stops)

    loads: dict[str, tuple[Stop, ...]] = {}
    tag = day.isoformat() if day else "none"
    k = 0
    for v in range(n_veh):
        idx = rt.Start(v)
        route = []
        while not rt.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node:
                route.append(stops[node - 1])
            idx = sol.Value(rt.NextVar(idx))
        if route:
            k += 1
            lid = f"OPT-{tag}-{k}"
            loads[lid] = tuple(Stop(**{**s.__dict__, "load_id": lid, "truck_id": ids[v]}) for s in route)
    routed = {s.id for st in loads.values() for s in st}
    return loads, tuple(s.id for s in stops if s.id not in routed)


def optimize(lmd: LmdDataset, providers: Sequence[RoutingProvider], sc: LmdScenario
             ) -> tuple[dict[str, tuple[Stop, ...]], OptimizeReport]:
    pool = [s for s in lmd.stops if s.appt_dt and (sc.stop_pool == "all" or s.load_id)]
    by_day: dict[date, list[Stop]] = {}
    for s in pool:
        by_day.setdefault(s.appt_dt, []).append(s)
    loads: dict[str, tuple[Stop, ...]] = {}
    unrouted: list[str] = []
    status = {"solved": 0, "no_solution": 0}
    for day in sorted(by_day):
        l, u = optimize_day(lmd, by_day[day], providers, sc, day)
        status["solved" if l or not by_day[day] else "no_solution"] += 1
        loads.update(l)
        unrouted.extend(u)
    routed = sum(len(v) for v in loads.values())
    return loads, OptimizeReport(len(by_day), len(pool), routed, tuple(unrouted), len(loads), status)
