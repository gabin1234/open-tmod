"""P03: road providers (OSRM/Valhalla), distance cache, road segments, time-of-day adjustments. Contract: docs/nodes/p03_routing.md"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

import psycopg

from tmod.product.db import connect
from tmod.routing import decode_polyline6

DOW = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


@dataclass(frozen=True)
class Edge:
    way_id: int | None
    edge_ref: str
    name: str
    length_m: float
    duration_s: float
    geometry: tuple[tuple[float, float], ...] | None = None   # edge polyline slice, for map highlight / nearest-segment


@dataclass(frozen=True)
class RouteDetail:
    distance_m: float
    duration_s: float
    geometry: tuple[tuple[float, float], ...]
    edges: tuple[Edge, ...]


class RoadProvider(Protocol):
    code: str
    profile: str

    def matrix(self, coords: Sequence[tuple[float, float]]) -> tuple[list[list[float]], list[list[float]]]: ...
    def route(self, a: tuple[float, float], b: tuple[float, float]) -> RouteDetail | None: ...


def _post(url: str, body: dict, timeout: float = 30):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(url: str, timeout: float = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


class OSRMProvider:
    code = "OSRM"
    max_block = 100   # osrm-routed default --max-table-size

    def __init__(self, base_url: str = "http://localhost:5001", profile: str = "driving") -> None:
        self.base, self.profile = base_url.rstrip("/"), profile

    def _coords(self, coords):
        return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)

    def matrix(self, coords):
        d = _get(f"{self.base}/table/v1/{self.profile}/{self._coords(coords)}?annotations=duration,distance")
        return d["distances"], d["durations"]

    def route(self, a, b):
        try:
            d = _get(f"{self.base}/route/v1/{self.profile}/{self._coords([a, b])}?overview=full&geometries=polyline6&steps=true&annotations=nodes")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if d.get("code") != "Ok":
            return None
        r = d["routes"][0]
        edges = []
        for leg in r["legs"]:
            nodes = leg.get("annotation", {}).get("nodes", [])
            for i, st in enumerate(leg["steps"]):
                if st["distance"] <= 0:
                    continue
                ref = f"osrm:{nodes[0]}-{nodes[-1]}" if nodes else f"osrm:step{i}"
                edges.append(Edge(None, ref + f"#{i}", st.get("name") or "", st["distance"], st["duration"]))
        return RouteDetail(r["distance"], r["duration"], decode_polyline6(r["geometry"]), tuple(edges))


class ValhallaRoadProvider:
    code = "VALHALLA"
    max_block = 20    # valhalla crashes (container restart) on 50x50 truck matrices; 20 is safe

    def __init__(self, base_url: str = "http://localhost:8002", profile: str = "truck") -> None:
        self.base, self.profile = base_url.rstrip("/"), profile

    def matrix(self, coords):
        locs = [{"lat": lat, "lon": lon} for lat, lon in coords]
        d = _post(f"{self.base}/sources_to_targets", {"sources": locs, "targets": locs, "costing": self.profile, "units": "kilometers"}, timeout=120)
        rows = d["sources_to_targets"]
        return ([[(c["distance"] or 0) * 1000 for c in row] for row in rows], [[c["time"] or 0 for c in row] for row in rows])

    def route(self, a, b):
        try:
            t = _post(f"{self.base}/route", {"locations": [{"lat": a[0], "lon": a[1]}, {"lat": b[0], "lon": b[1]}], "costing": self.profile, "units": "kilometers"})["trip"]
            leg = t["legs"][0]
            tr = _post(f"{self.base}/trace_attributes", {"encoded_polyline": leg["shape"], "costing": self.profile, "shape_match": "edge_walk",
                       "filters": {"attributes": ["edge.way_id", "edge.names", "edge.length", "edge.id", "edge.begin_shape_index", "edge.end_shape_index", "node.elapsed_time", "shape"], "action": "include"}})
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError):
            return None
        shape = decode_polyline6(tr.get("shape") or leg["shape"])
        edges, prev = [], 0.0
        for e in tr.get("edges", []):
            t_end = (e.get("end_node") or {}).get("elapsed_time", prev)
            b, en = e.get("begin_shape_index"), e.get("end_shape_index")
            geom = shape[b:en + 1] if b is not None and en is not None and en > b else None
            edges.append(Edge(e.get("way_id"), f"valhalla:{e.get('id')}", ", ".join(e.get("names") or []), e.get("length", 0) * 1000, max(0.0, t_end - prev), geom))
            prev = t_end
        return RouteDetail(t["summary"]["length"] * 1000, t["summary"]["time"], decode_polyline6(leg["shape"]), tuple(edges))


# ---------- cache / segments ----------
def _locations(con, ids: Sequence[int]) -> dict[int, tuple[float, float]]:
    rows = con.execute("SELECT location_id, latitude, longitude FROM location WHERE location_id = ANY(%s)", (list(ids),)).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows if r[1] is not None and r[2] is not None}


def fill_distance_cache(con: psycopg.Connection, provider: RoadProvider, location_ids: Sequence[int], chunk: int | None = None) -> int:
    """Insert missing (from,to) pairs for provider/profile. Returns rows inserted. chunk = half the provider's matrix limit."""
    chunk = chunk or getattr(provider, "max_block", 100) // 2
    pts = _locations(con, location_ids)
    ids = list(pts)
    have = {(a, b) for a, b in con.execute("SELECT from_location_id, to_location_id FROM distance_cache WHERE provider=%s AND profile=%s AND from_location_id = ANY(%s)",
                                           (provider.code, provider.profile, ids)).fetchall()}
    missing_src = sorted({a for a in ids for b in ids if a != b and (a, b) not in have})
    n = 0
    for i in range(0, len(missing_src), chunk):
        src = missing_src[i:i + chunk]
        for j in range(0, len(ids), chunk):
            tgt = ids[j:j + chunk]
            block = list(dict.fromkeys(src + tgt))
            dist, dur = provider.matrix([pts[k] for k in block])
            idx = {k: n_ for n_, k in enumerate(block)}
            rows = [(a, b, provider.code, provider.profile, int(round(dist[idx[a]][idx[b]])), int(round(dur[idx[a]][idx[b]])))
                    for a in src for b in tgt if a != b and (a, b) not in have]
            con.cursor().executemany("INSERT INTO distance_cache (from_location_id, to_location_id, provider, profile, distance_m, duration_s) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
            have.update((a, b) for a, b, *_ in rows)
            n += len(rows)
    con.commit()
    return n


def _segment_id(con, e: Edge) -> int:
    if e.way_id is not None:
        row = con.execute("SELECT segment_id FROM road_segment WHERE osm_way_id=%s AND osrm_edge_ref=%s", (e.way_id, e.edge_ref)).fetchone()
    else:
        row = con.execute("SELECT segment_id FROM road_segment WHERE osrm_edge_ref=%s", (e.edge_ref,)).fetchone()
    if row:
        if e.geometry:
            con.execute("UPDATE road_segment SET geometry=%s WHERE segment_id=%s AND geometry IS NULL", (json.dumps([list(p) for p in e.geometry]), row[0]))
        return row[0]
    sid = con.execute("INSERT INTO road_segment (segment_code, road_name, osm_way_id, osrm_edge_ref, length_m, geometry) VALUES ('tmp', %s, %s, %s, %s, %s) RETURNING segment_id",
                      (e.name or "(unnamed)", e.way_id, e.edge_ref, round(e.length_m, 1), json.dumps([list(p) for p in e.geometry]) if e.geometry else None)).fetchone()[0]
    con.execute("UPDATE road_segment SET segment_code = 'SEG-' || lpad(%s::text, 6, '0') WHERE segment_id=%s", (sid, sid))
    return sid


def route_detail(con: psycopg.Connection, provider: RoadProvider, from_id: int, to_id: int) -> RouteDetail | None:
    pts = _locations(con, [from_id, to_id])
    if from_id not in pts or to_id not in pts:
        return None
    rd = provider.route(pts[from_id], pts[to_id])
    if rd is None:
        return None
    seg_ids = [_segment_id(con, e) for e in rd.edges]
    seg_dur = [int(round(e.duration_s)) for e in rd.edges]
    con.execute("""INSERT INTO distance_cache (from_location_id, to_location_id, provider, profile, distance_m, duration_s, segment_ids, segment_durations_s, geometry)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (from_location_id, to_location_id, provider, profile) DO UPDATE SET distance_m=EXCLUDED.distance_m, duration_s=EXCLUDED.duration_s,
                   segment_ids=EXCLUDED.segment_ids, segment_durations_s=EXCLUDED.segment_durations_s, geometry=EXCLUDED.geometry, computed_at=now()""",
                (from_id, to_id, provider.code, provider.profile, int(round(rd.distance_m)), int(round(rd.duration_s)), seg_ids, seg_dur,
                 json.dumps([list(p) for p in rd.geometry])))
    con.commit()
    return rd


def traffic_profile(con: psycopg.Connection, plan_date: date) -> list[tuple[int, int, float]]:
    """Global (region-less) traffic_profile windows for the day: [(from_s, to_s, factor)]."""
    dow = DOW[plan_date.weekday()]
    rows = con.execute("""SELECT time_from, time_to, factor FROM traffic_profile WHERE active_flag AND region_code IS NULL
                          AND (day_of_week IS NULL OR day_of_week=%s::day_of_week) AND effective_from <= %s AND (effective_to IS NULL OR effective_to >= %s)""",
                       (dow, plan_date, plan_date)).fetchall()
    return [(tf.hour * 3600 + tf.minute * 60, tt.hour * 3600 + tt.minute * 60 if tt.hour < 24 else 86400, float(f)) for tf, tt, f in rows]


def _profile_factor(profile: list[tuple[int, int, float]], t_s: float) -> float:
    return max((f for tf, tt, f in profile if tf <= (t_s % 86400) < tt), default=1.0)


def adjusted_duration(con: psycopg.Connection, from_id: int, to_id: int, provider_code: str, profile: str, plan_date: date, depart_s: int,
                      scenario_id: int | None = None, day_profile: list[tuple[int, int, float]] | None = None) -> int | None:
    """Cache duration with time-of-day factors: segment-level road_adjustment where known, else the global traffic_profile."""
    row = con.execute("SELECT duration_s, segment_ids, segment_durations_s FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s AND provider=%s AND profile=%s",
                      (from_id, to_id, provider_code, profile)).fetchone()
    if row is None:
        return None
    base, segs, durs = row
    prof = day_profile if day_profile is not None else traffic_profile(con, plan_date)
    if not segs or not durs:
        return int(round(base * _profile_factor(prof, depart_s)))
    dow = DOW[plan_date.weekday()]
    if scenario_id is None:
        adj = con.execute("""SELECT segment_id, day_of_week, time_from, time_to, factor FROM road_adjustment
                             WHERE active_flag AND segment_id = ANY(%s) AND (day_of_week IS NULL OR day_of_week=%s::day_of_week)
                             AND effective_from <= %s AND (effective_to IS NULL OR effective_to >= %s)""", (segs, dow, plan_date, plan_date)).fetchall()
    else:
        adj = con.execute("""SELECT a.segment_id, a.day_of_week, a.time_from, a.time_to, a.factor FROM road_adjustment a
                             JOIN scenario_road_adjustment s ON s.adjustment_id=a.adjustment_id AND s.scenario_id=%s AND s.enabled_flag
                             WHERE a.active_flag AND a.segment_id = ANY(%s) AND (a.day_of_week IS NULL OR a.day_of_week=%s::day_of_week)
                             AND a.effective_from <= %s AND (a.effective_to IS NULL OR a.effective_to >= %s)""", (scenario_id, segs, dow, plan_date, plan_date)).fetchall()
    by_seg: dict[int, list] = {}
    for sid, _, tf, tt, f in adj:
        by_seg.setdefault(sid, []).append((tf.hour * 3600 + tf.minute * 60, tt.hour * 3600 + tt.minute * 60 if tt.hour < 24 else 86400, float(f)))
    clock, total = float(depart_s), 0.0
    for sid, d in zip(segs, durs):
        factor = None
        for tf, tt, f in by_seg.get(sid, []):
            if tf <= (clock % 86400) < tt:
                factor = max(factor or 1.0, f)
        if factor is None:
            factor = _profile_factor(prof, clock)
        total += d * factor
        clock += d * factor
    return int(round(total))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fill":
        prov = ValhallaRoadProvider() if (a[a.index("--provider") + 1] if "--provider" in a else "VALHALLA") == "VALHALLA" else OSRMProvider()
        with connect() as con:
            if "--scenario" in a:
                ids = [r[0] for r in con.execute("""SELECT DISTINCT l.location_id FROM scenario s JOIN depot d ON d.depot_id=s.depot_id JOIN location l ON l.location_id=d.location_id WHERE s.scenario_code=%s
                    UNION SELECT sh.delivery_location_id FROM scenario s JOIN scenario_shipment ss ON ss.scenario_id=s.scenario_id JOIN shipment sh ON sh.shipment_id=ss.shipment_id WHERE s.scenario_code=%s""",
                    (a[a.index("--scenario") + 1],) * 2).fetchall()]
            else:
                ids = [r[0] for r in con.execute("SELECT location_id FROM location WHERE latitude IS NOT NULL").fetchall()]
            print(f"{len(ids)} locations -> {fill_distance_cache(con, prov, ids)} pairs inserted ({prov.code}/{prov.profile})")
    else:
        print(__doc__)
