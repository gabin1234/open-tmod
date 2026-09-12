"""P04: OR-Tools routing model from ScenarioData; results into optimization_run/route/unassigned. Contract: docs/nodes/p04_model.md"""
from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import psycopg
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from tmod.product.db import connect
from tmod.product.model import ScenarioData, load_scenario, matrices, populate_scenario
from tmod.product.routing import OSRMProvider, RoadProvider, ValhallaRoadProvider

BIG = 10 ** 9
PRIORITY_FACTOR = {1: 3.0, 2: 2.0, 3: 1.5, 4: 1.2, 5: 1.0}   # drop-penalty multiplier for optional shipments by priority (1 = highest)
SCALE = 100          # objective integer scale
NONOPT_PENALTY = 10 ** 7


@dataclass(frozen=True)
class SolveResult:
    run_id: int
    status: str
    vehicles: int
    stops: int
    unassigned: int
    total_distance_m: int
    total_route_s: int
    total_cost: float


def _arc_cost(data: ScenarioData, v, dist_m: int, dur_s: int) -> int:
    w = data.weights
    cost = w.get("COST", 0) * (v.cost_per_km * dist_m / 1000 + v.cost_per_hour * dur_s / 3600)
    cost += w.get("TRAVEL_TIME", 0) * dur_s / 60           # minutes
    cost += w.get("DISTANCE", 0) * dist_m / 1000            # km
    return int(round(cost * SCALE))


def _vehicle_fixed(data: ScenarioData, v) -> int:
    w = data.weights
    return int(round((w.get("COST", 0) * v.fixed_cost + w.get("VEHICLE_COUNT", 0) * 500.0) * SCALE))


def build_and_solve(data: ScenarioData, dist: list[list[int]], dur: list[list[int]]):
    n, V = len(data.locations), len(data.vehicles)
    if V == 0:
        raise ValueError("scenario has no vehicles")
    D = len(data.depot_locations)                     # depot nodes 0..D-1, stops D..n-1
    depots = [data.vehicle_depot_node(v) for v in data.vehicles]
    mgr = pywrapcp.RoutingIndexManager(n, V, depots, depots)
    rt = pywrapcp.RoutingModel(mgr)
    C = data.constraints
    stops = data.stops
    service = [0] * D + [s.service_s if "SERVICE_TIME" in C else 0 for s in stops]
    node_stop = lambda node: stops[node - D] if node >= D else None  # noqa: E731

    for vi, v in enumerate(data.vehicles):
        def cb(a, b, v=v):
            i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
            return 0 if i == j else _arc_cost(data, v, dist[i][j], dur[i][j])
        rt.SetArcCostEvaluatorOfVehicle(rt.RegisterTransitCallback(cb), vi)
        rt.SetFixedCostOfVehicle(_vehicle_fixed(data, v), vi)

    # time dimension: cumul = arrival (seconds from midnight); transit = service(i) + drive(i,j); slack = waiting
    max_wait = int(C.get("TIME_WINDOW", {}).get("max_wait_s", 7200)) if "TIME_WINDOW" in C else 0
    horizon = max(v.shift_end_s for v in data.vehicles) + 6 * 3600
    def time_cb(a, b):
        i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
        return service[i] + (0 if i == j else dur[i][j])
    rt.AddDimension(rt.RegisterTransitCallback(time_cb), max_wait, horizon, False, "time")
    tdim = rt.GetDimensionOrDie("time")
    for vi, v in enumerate(data.vehicles):
        tdim.CumulVar(rt.Start(vi)).SetRange(v.shift_start_s, v.shift_start_s + (0 if "TIME_WINDOW" in C else 0))
        tdim.CumulVar(rt.End(vi)).SetMax(v.shift_end_s)
        lim = [x for x in (v.duty_limit_s if "DUTY_LIMIT" in C else None, v.max_route_s if "DUTY_LIMIT" in C else None) if x]
        if lim:
            tdim.SetSpanUpperBoundForVehicle(min(lim), vi)
    lat_pen = C.get("SOFT_TIME_WINDOW", {}).get("penalty_per_min", 2.0) if "SOFT_TIME_WINDOW" in C else None
    for k, s in enumerate(stops, start=D):
        idx = mgr.NodeToIndex(k)
        if s.window_start_s is not None:
            tdim.CumulVar(idx).SetMin(max(0, s.window_start_s))
        if s.window_end_s is not None:
            if lat_pen is not None:
                tdim.SetCumulVarSoftUpperBound(idx, s.window_end_s, int(round(float(lat_pen) / 60 * data.weights.get("LATENESS", 1.0) * SCALE)))
            elif "TIME_WINDOW" in C:
                tdim.CumulVar(idx).SetMax(s.window_end_s)

    # distance dimension
    def dist_cb(a, b):
        i, j = mgr.IndexToNode(a), mgr.IndexToNode(b)
        return 0 if i == j else dist[i][j]
    rt.AddDimension(rt.RegisterTransitCallback(dist_cb), 0, BIG, True, "distance")
    if "MAX_DISTANCE" in C:
        ddim = rt.GetDimensionOrDie("distance")
        for vi, v in enumerate(data.vehicles):
            if v.max_distance_m:
                ddim.SetSpanUpperBoundForVehicle(v.max_distance_m, vi)

    # capacities (signed: pickups load, P&D deliveries unload)
    for code, attr, cap_attr, scale in (("CAPACITY_WEIGHT", "weight_kg", "capacity_kg", 1000), ("CAPACITY_VOLUME", "volume_m3", "capacity_m3", 1000)):
        if code in C:
            demand = [0] * D + [int(round(getattr(s, attr) * scale)) * s.demand_sign for s in stops]
            caps = [int(round(getattr(v, cap_attr) * scale)) if getattr(v, cap_attr) else BIG for v in data.vehicles]
            rt.AddDimensionWithVehicleCapacity(rt.RegisterUnaryTransitCallback(lambda a, d=demand: d[mgr.IndexToNode(a)]), 0, caps, True, code)
    # pickup & delivery pairs: same vehicle, pickup first
    solver = rt.solver()
    pick = {s.pair: k for k, s in enumerate(stops, start=D) if s.kind == "PICKUP_DELIVERY_P"}
    for k, s in enumerate(stops, start=D):
        if s.kind == "PICKUP_DELIVERY_D" and s.pair in pick:
            p, d = mgr.NodeToIndex(pick[s.pair]), mgr.NodeToIndex(k)
            rt.AddPickupAndDelivery(p, d)
            solver.Add(rt.VehicleVar(p) == rt.VehicleVar(d))
            solver.Add(tdim.CumulVar(p) <= tdim.CumulVar(d))
    if "WORK_LIMIT" in C:
        work = [0] * D + [s.service_s for s in stops]
        caps = [v.work_limit_s or BIG for v in data.vehicles]
        rt.AddDimensionWithVehicleCapacity(rt.RegisterUnaryTransitCallback(lambda a, w=work: w[mgr.IndexToNode(a)]), 0, caps, True, "work")
    # max stops per vehicle
    if any(v.max_stops for v in data.vehicles):
        rt.AddDimensionWithVehicleCapacity(rt.RegisterUnaryTransitCallback(lambda a: 0 if mgr.IndexToNode(a) < D else 1), 0,
                                           [v.max_stops or BIG for v in data.vehicles], True, "stops")
    # compatibility
    if "VEHICLE_COMPAT" in C:
        for k, s in enumerate(stops, start=D):
            if s.forbidden_vehicles:
                # ortools 9.15 SWIG rejects SetAllowedVehiclesForIndex(list) -> constrain the VehicleVar directly (-1 = unperformed stays allowed)
                forbidden = [vi for vi, v in enumerate(data.vehicles) if v.vehicle_id in s.forbidden_vehicles]
                rt.VehicleVar(mgr.NodeToIndex(k)).RemoveValues(forbidden)
    # optional / drop
    default_pen = float(C.get("OPTIONAL_DROP", {}).get("default_penalty", 500))
    for k, s in enumerate(stops, start=D):
        if "OPTIONAL_DROP" in C and s.optional:
            pen = int(round((s.drop_penalty or default_pen) * PRIORITY_FACTOR.get(s.priority, 1.0) * SCALE))
        else:
            pen = NONOPT_PENALTY * SCALE
        rt.AddDisjunction([mgr.NodeToIndex(k)], pen)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(max(1, data.time_limit_s))
    sol = rt.SolveWithParameters(params)
    return mgr, rt, sol, tdim, D


def _departures(data: ScenarioData, mgr, rt, sol, tdim, D: int) -> dict[tuple[int, int], int]:
    """(from_node, to_node) -> departure second, from a solution. Used to re-time legs for DYNAMIC_TRAFFIC."""
    out: dict[tuple[int, int], int] = {}
    for vi, v in enumerate(data.vehicles):
        idx = rt.Start(vi)
        while not rt.IsEnd(idx):
            nxt = sol.Value(rt.NextVar(idx))
            i, j = mgr.IndexToNode(idx), mgr.IndexToNode(nxt)
            depart = sol.Value(tdim.CumulVar(idx)) + (data.stops[i - D].service_s if i >= D else 0)
            out[(i, j)] = depart
            idx = nxt
    return out


def _sequence(data: ScenarioData, mgr, rt, sol) -> tuple:
    seq = []
    for vi in range(len(data.vehicles)):
        idx, route = rt.Start(vi), []
        while not rt.IsEnd(idx):
            route.append(mgr.IndexToNode(idx))
            idx = sol.Value(rt.NextVar(idx))
        seq.append(tuple(route))
    return tuple(seq)


def run_scenario(con: psycopg.Connection, scenario_code: str, provider: RoadProvider | None = None) -> SolveResult:
    data = load_scenario(con, scenario_code)
    run_id = con.execute("INSERT INTO optimization_run (scenario_id, start_time, solver_status, engine_params) VALUES (%s, now(), 'RUNNING', %s) RETURNING optimization_run_id",
                         (data.scenario_id, psycopg.types.json.Json({"time_limit_s": data.time_limit_s, "constraints": list(data.constraints), "weights": data.weights, "provider": data.provider_code}))).fetchone()[0]
    con.execute("UPDATE scenario SET status='RUNNING' WHERE scenario_id=%s", (data.scenario_id,))
    con.commit()
    try:
        dist, dur = matrices(con, data, provider)
        mgr, rt, sol, tdim, D = build_and_solve(data, dist, dur)
        iterations_used = 1
        if sol is not None and "DYNAMIC_TRAFFIC" in data.constraints:
            max_it = int(data.constraints["DYNAMIC_TRAFFIC"].get("iterations", 3))
            prev = _sequence(data, mgr, rt, sol)
            while iterations_used < max_it:
                deps = _departures(data, mgr, rt, sol, tdim, D)
                # pairs not on the previous solution get the median departure, so untimed arcs are not artificially cheap
                dist, dur = matrices(con, data, provider, deps, int(statistics.median(deps.values())) if deps else None)
                mgr, rt, sol2, tdim, D = build_and_solve(data, dist, dur)
                iterations_used += 1
                if sol2 is None:
                    break
                sol = sol2
                cur = _sequence(data, mgr, rt, sol)
                if cur == prev:
                    break
                prev = cur
        retime = sol is not None and "DYNAMIC_TRAFFIC" in data.constraints
        if retime:   # final legs timed at their actual departures (the last matrix may predate the last sequence change)
            deps = _departures(data, mgr, rt, sol, tdim, D)
            dist, dur = matrices(con, data, provider, deps, int(statistics.median(deps.values())) if deps else None)
        if sol is None:
            con.execute("UPDATE optimization_run SET solver_status='INFEASIBLE', end_time=now() WHERE optimization_run_id=%s", (run_id,))
            con.execute("UPDATE scenario SET status='READY' WHERE scenario_id=%s", (data.scenario_id,))
            con.commit()
            return SolveResult(run_id, "INFEASIBLE", 0, len(data.stops), len(data.stops), 0, 0, 0.0)
        midnight = datetime.combine(data.plan_date, time(0), tzinfo=data.tz)
        routed: set[int] = set()
        tot_dist = tot_drive = tot_service = tot_route = 0
        tot_cost = 0.0
        used = 0
        rows = []
        for vi, v in enumerate(data.vehicles):
            idx = rt.Start(vi)
            if rt.IsEnd(sol.Value(rt.NextVar(idx))):
                continue
            used += 1
            dnode = data.vehicle_depot_node(v)
            depot_loc = data.locations[dnode]
            seq, prev_node, v_dist, v_drive, v_service = 0, dnode, 0, 0, 0
            start_s = sol.Value(tdim.CumulVar(idx))
            clock = start_s
            load = 0.0
            rows.append((run_id, v.vehicle_id, 0, depot_loc, None, midnight + timedelta(seconds=start_s), midnight + timedelta(seconds=start_s), 0, 0, 0, 0, 0, "DEPOT", None))
            idx = sol.Value(rt.NextVar(idx))
            while not rt.IsEnd(idx):
                node = mgr.IndexToNode(idx)
                s = data.stops[node - D]
                d_prev, t_prev = dist[prev_node][node], dur[prev_node][node]
                if retime:
                    arr = max(clock + t_prev, s.window_start_s or 0)
                    clock = arr + s.service_s
                else:
                    arr = sol.Value(tdim.CumulVar(idx))
                late = max(0, arr - s.window_end_s) if s.window_end_s is not None else 0
                per = max(1, len(s.shipment_ids))
                kind = {"PICKUP": "PICKUP", "PICKUP_DELIVERY_P": "PICKUP"}.get(s.kind, "DELIVERY")
                load += s.weight_kg * s.demand_sign if s.kind != "DELIVERY" else 0.0
                for k, shid in enumerate(s.shipment_ids):
                    seq += 1
                    rows.append((run_id, v.vehicle_id, seq, s.location_id, shid, midnight + timedelta(seconds=arr), midnight + timedelta(seconds=arr + s.service_s),
                                 0, s.service_s // per if k else s.service_s - s.service_s // per * (per - 1), d_prev if k == 0 else 0, t_prev if k == 0 else 0, late, kind, round(load, 3)))
                    if s.kind != "PICKUP_DELIVERY_P":
                        routed.add(shid)
                v_dist += d_prev
                v_drive += t_prev
                v_service += s.service_s
                prev_node = node
                idx = sol.Value(rt.NextVar(idx))
            d_prev, t_prev = dist[prev_node][dnode], dur[prev_node][dnode]
            end_s = clock + t_prev if retime else sol.Value(tdim.CumulVar(idx))
            v_dist += d_prev
            v_drive += t_prev
            seq += 1
            rows.append((run_id, v.vehicle_id, seq, depot_loc, None, midnight + timedelta(seconds=end_s), midnight + timedelta(seconds=end_s), 0, 0, d_prev, t_prev, 0, "DEPOT", round(load, 3)))
            route_s = end_s - start_s
            tot_dist += v_dist
            tot_drive += v_drive
            tot_service += v_service
            tot_route += route_s
            tot_cost += v.fixed_cost + v.cost_per_km * v_dist / 1000 + v.cost_per_hour * route_s / 3600
        con.cursor().executemany("""INSERT INTO optimization_route (optimization_run_id, vehicle_id, route_sequence, stop_location_id, shipment_id, arrival_time, departure_time,
                                    wait_s, service_s, distance_from_previous_m, travel_time_from_previous_s, late_s, stop_kind, load_after_kg) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        un = [(run_id, shid, "DROPPED_OPTIONAL" if s.optional else "INFEASIBLE_DROPPED", s.drop_penalty)
              for s in data.stops if s.kind != "PICKUP_DELIVERY_P" for shid in s.shipment_ids if shid not in routed]
        un += [(run_id, shid, reason, None) for shid, reason in data.unsupported]
        if un:
            con.cursor().executemany("INSERT INTO optimization_unassigned (optimization_run_id, shipment_id, reason, penalty_applied) VALUES (%s,%s,%s,%s)", un)
        status = "OPTIMAL" if rt.status() == 1 else "FEASIBLE"
        con.execute("""UPDATE optimization_run SET end_time=now(), solver_status=%s, objective_value=%s, vehicle_count=%s, total_distance_m=%s, total_drive_s=%s,
                       total_service_s=%s, total_route_s=%s, total_cost=%s, engine_params = engine_params || %s::jsonb WHERE optimization_run_id=%s""",
                    (status, sol.ObjectiveValue() / SCALE, used, tot_dist, tot_drive, tot_service, tot_route, round(tot_cost, 2),
                     psycopg.types.json.Json({"iterations_used": iterations_used}), run_id))
        con.execute("UPDATE scenario SET status='DONE' WHERE scenario_id=%s", (data.scenario_id,))
        con.commit()
        return SolveResult(run_id, status, used, len(data.stops), len(un), tot_dist, tot_route, round(tot_cost, 2))
    except Exception as e:
        con.rollback()
        con.execute("UPDATE optimization_run SET solver_status='ERROR', end_time=now(), error_message=%s WHERE optimization_run_id=%s", (f"{type(e).__name__}: {e}"[:1000], run_id))
        con.execute("UPDATE scenario SET status='READY' WHERE scenario_id=%s", (data.scenario_id,))
        con.commit()
        raise


if __name__ == "__main__":
    a = sys.argv[1:]
    prov = None
    if "--provider" in a:
        prov = ValhallaRoadProvider() if a[a.index("--provider") + 1] == "VALHALLA" else OSRMProvider()
    with connect() as con:
        sid = con.execute("SELECT scenario_id FROM scenario WHERE scenario_code=%s", (a[0],)).fetchone()[0]
        print("populated", populate_scenario(con, sid))
        print(run_scenario(con, a[0], prov))
