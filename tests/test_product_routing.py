import urllib.request
from datetime import date

import pytest

from tmod.product.db import init
from tmod.product.routing import Edge, OSRMProvider, RouteDetail, ValhallaRoadProvider, adjusted_duration, fill_distance_cache, route_detail


class Mock:
    code, profile = "MANUAL", "test"

    def __init__(self):
        self.calls = 0

    def matrix(self, coords):
        self.calls += 1
        n = len(coords)
        return ([[0 if i == j else 1000.0 * (i + j) for j in range(n)] for i in range(n)],
                [[0 if i == j else 60.0 * (i + j) for j in range(n)] for i in range(n)])

    def route(self, a, b):
        return RouteDetail(1500.0, 200.0, ((a[0], a[1]), (b[0], b[1])),
                           (Edge(111, "v:1", "Silver Avenue", 900.0, 120.0, ((a[0], a[1]), (a[0] + 0.005, a[1]))), Edge(222, "v:2", "Oak St", 600.0, 80.0)))


def _setup(pg):
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    con.execute("SET search_path TO tmod")
    ids = [con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", 33.5 + i / 100, -84.3)).fetchone()[0] for i in range(3)]
    con.commit()
    return con, ids


def test_fill_cache_and_route_detail(pg):
    con, ids = _setup(pg)
    m = Mock()
    assert fill_distance_cache(con, m, ids) == 6 and m.calls == 1
    assert fill_distance_cache(con, m, ids) == 0
    assert con.execute("SELECT distance_m, duration_s FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s", (ids[0], ids[2])).fetchone() == (2000, 120)
    rd = route_detail(con, m, ids[0], ids[1])
    assert rd.distance_m == 1500 and con.execute("SELECT count(*) FROM road_segment WHERE osm_way_id IN (111,222)").fetchone()[0] == 2
    route_detail(con, m, ids[1], ids[2])
    assert con.execute("SELECT count(*) FROM road_segment WHERE osm_way_id IN (111,222)").fetchone()[0] == 2  # no dupes
    row = con.execute("SELECT segment_ids, segment_durations_s, distance_m FROM distance_cache WHERE from_location_id=%s AND to_location_id=%s", (ids[0], ids[1])).fetchone()
    assert len(row[0]) == 2 and row[1] == [120, 80] and row[2] == 1500
    codes = con.execute("SELECT segment_code, road_name, geometry FROM road_segment WHERE osm_way_id=111").fetchone()
    assert codes[0].startswith("SEG-") and codes[1] == "Silver Avenue" and len(codes[2]) == 2
    con.close()


def test_adjusted_duration(pg):
    con, ids = _setup(pg)
    m = Mock()
    route_detail(con, m, ids[0], ids[1])
    seg = con.execute("SELECT segment_id FROM road_segment WHERE osm_way_id=111").fetchone()[0]
    con.execute("INSERT INTO road_adjustment (segment_id, day_of_week, time_from, time_to, factor, reason) VALUES (%s,'MON','07:00','09:00',1.5,'am')", (seg,))
    con.commit()
    mon = date(2026, 9, 14)
    assert adjusted_duration(con, ids[0], ids[1], "MANUAL", "test", mon, 8 * 3600) == 120 * 1.5 + 80
    assert adjusted_duration(con, ids[0], ids[1], "MANUAL", "test", mon, 9 * 3600 + 1) == 200
    assert adjusted_duration(con, ids[0], ids[1], "MANUAL", "test", date(2026, 9, 15), 8 * 3600) == 200  # TUE
    sc = con.execute("SELECT scenario_id FROM scenario LIMIT 1").fetchone()[0]
    assert adjusted_duration(con, ids[0], ids[1], "MANUAL", "test", mon, 8 * 3600, scenario_id=sc) == 200  # not selected in scenario
    con.execute("INSERT INTO scenario_road_adjustment (scenario_id, adjustment_id) SELECT %s, adjustment_id FROM road_adjustment WHERE segment_id=%s", (sc, seg))
    con.commit()
    assert adjusted_duration(con, ids[0], ids[1], "MANUAL", "test", mon, 8 * 3600, scenario_id=sc) == 260
    assert adjusted_duration(con, ids[1], ids[0], "MANUAL", "test", mon, 8 * 3600) is None  # not cached
    con.close()


def _up(url):
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _up("http://localhost:8002/status"), reason="valhalla down")
def test_valhalla_real():
    p = ValhallaRoadProvider()
    rd = p.route((33.587, -84.334), (33.79, -84.39))
    assert rd and rd.distance_m > 20000 and len(rd.edges) > 50 and any(e.way_id for e in rd.edges) and abs(sum(e.duration_s for e in rd.edges) - rd.duration_s) < 5
    assert sum(1 for e in rd.edges if e.geometry) > 40
    dist, dur = p.matrix([(33.587, -84.334), (33.79, -84.39)])
    assert dist[0][1] > 20000 and dur[0][1] > 600


@pytest.mark.skipif(not _up("http://localhost:5001/route/v1/driving/-84.334,33.587;-84.39,33.79?overview=false"), reason="osrm down")
def test_osrm_real():
    p = OSRMProvider()
    rd = p.route((33.587, -84.334), (33.79, -84.39))
    assert rd and rd.distance_m > 20000 and rd.edges and rd.geometry
    dist, dur = p.matrix([(33.587, -84.334), (33.79, -84.39)])
    assert dist[0][1] > 20000
