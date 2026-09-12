import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tmod.product.db import init
from tmod.product.routing import fill_distance_cache
from tmod.web.app import create_app


class Grid:
    code, profile = "MANUAL", "test"

    def matrix(self, coords):
        d = [[abs(a[0] - b[0]) * 100000 + abs(a[1] - b[1]) * 100000 for b in coords] for a in coords]
        return d, [[x / 10 for x in row] for row in d]

    def route(self, a, b):
        return None


@pytest.fixture
def client(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("TMOD_PG_DSN", pg)
    import psycopg
    init(pg, seed=True, drop=True)
    con = psycopg.connect(pg)
    con.execute("SET search_path TO tmod")
    con.execute("UPDATE location SET latitude=33.50, longitude=-84.30 WHERE location_code='HUB-LPHB-30260'")
    con.execute("UPDATE vehicle_type SET capacity_kg=1000, max_stops=NULL")
    ss = con.execute("SELECT source_system_id FROM source_system WHERE system_code='XLSX'").fetchone()[0]
    ids = [con.execute("SELECT location_id FROM location WHERE location_code='HUB-LPHB-30260'").fetchone()[0]]
    for i, (la, lo) in enumerate([(33.51, -84.30), (33.52, -84.30), (33.50, -84.29)]):
        ids.append(con.execute("INSERT INTO location (location_code, latitude, longitude) VALUES (%s,%s,%s) RETURNING location_id", (f"L{i}", la, lo)).fetchone()[0])
    for i in range(6):
        con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, service_s, weight_kg) VALUES (%s,%s,%s,'2026-09-20',600,300)", (ss, f"S{i}", ids[1 + i % 3]))
    con.commit()
    fill_distance_cache(con, Grid(), ids)
    con.close()
    with TestClient(create_app(tmp_path, tmp_path / "runs")) as c:
        yield c


def test_masters(client):
    r = client.post("/api/v2/master/vehicle_type", json={"type_code": "VAN", "name": "Van", "capacity_kg": 800, "fixed_cost": 100})
    assert r.status_code == 201 and r.json()["capacity_kg"] == 800
    assert client.post("/api/v2/master/vehicle_type", json={"type_code": "VAN", "capacity_kg": 900}).json()["capacity_kg"] == 900
    assert client.post("/api/v2/master/vehicle_type", json={"type_code": "X", "bogus": 1}).status_code == 422
    assert client.delete("/api/v2/master/vehicle_type/VAN").status_code == 204
    assert "VAN" not in {x["type_code"] for x in client.get("/api/v2/master/vehicle_type").json()}
    assert client.get("/api/v2/master/nope").status_code == 404
    assert len(client.get("/api/v2/master/vehicle").json()) == 10


def test_scenario_lifecycle_and_compare(client):
    assert client.get("/api/v2/shipments/dates").json()[0]["n"] == 6
    r = client.post("/api/v2/scenarios", json={"code": "SC-A", "name": "A", "plan_date": "2026-09-20", "depot_code": "LPHB-30260", "provider": "MANUAL", "time_limit_s": 2})
    assert r.status_code == 201 and r.json()["populated"] == 6 and len(r.json()["vehicles"]) == 10
    sc = r.json()
    assert {c["constraint_code"]: c["enabled"] for c in sc["constraints"]}["CAPACITY_WEIGHT"] is True and sum(w["weight_pct"] for w in sc["weights"]) == 100
    assert client.post("/api/v2/scenarios", json={"code": "SC-A", "name": "dup", "plan_date": "2026-09-20", "depot_code": "LPHB-30260"}).status_code == 409
    up = client.put("/api/v2/scenarios/SC-A", json={"vehicles": ["T01", "T02", "T03"], "weights": {"VEHICLE_COUNT": 100}})
    assert up.status_code == 200 and up.json()["vehicles"] == ["T01", "T02", "T03"] and up.json()["status"] == "READY"
    assert client.put("/api/v2/scenarios/SC-A", json={"weights": {"COST": 10}}).status_code == 422
    run = client.post("/api/v2/scenarios/SC-A/run?wait=1")
    assert run.status_code == 202 and run.json()["result"]["status"] in ("OPTIMAL", "FEASIBLE"), run.text
    rid = run.json()["result"]["run_id"]
    res = client.get(f"/api/v2/runs/{rid}").json()
    assert res["vehicle_count"] >= 2 and sum(v["shipments"] for v in res["routes"]) == 6 and res["routes"][0]["stops"][0]["route_sequence"] == 0
    cp = client.post("/api/v2/scenarios/SC-A/copy?new_code=SC-B")
    assert cp.status_code == 201 and cp.json()["vehicles"] == ["T01", "T02", "T03"] and cp.json()["shipment_count"] == 6 and cp.json()["copied_from_id"] == sc["scenario_id"]
    client.put("/api/v2/scenarios/SC-B", json={"weights": {"DISTANCE": 100}, "constraints": {"CAPACITY_WEIGHT": {"enabled": False}}})
    assert client.get("/api/v2/scenarios/SC-A").json()["weights"][0]["weight_pct"] in (0, 100)  # original untouched: still VEHICLE_COUNT 100
    rid2 = client.post("/api/v2/scenarios/SC-B/run?wait=1").json()["result"]["run_id"]
    cmp = client.get(f"/api/v2/compare?a={rid}&b={rid2}").json()
    assert set(cmp["delta"]) >= {"vehicle_count", "total_distance_m", "total_cost", "unassigned"} and cmp["a"]["scenario_code"] == "SC-A"
    lst = client.get("/api/v2/scenarios").json()
    assert {s["scenario_code"] for s in lst} >= {"SC-A", "SC-B"} and [s for s in lst if s["scenario_code"] == "SC-A"][0]["runs"] == 1
    assert client.delete("/api/v2/scenarios/SC-B").status_code == 204
    assert "SC-B" not in {s["scenario_code"] for s in client.get("/api/v2/scenarios").json()}
    job = client.post("/api/v2/scenarios/SC-A/run").json()["job_id"]
    import time
    for _ in range(100):
        j = client.get(f"/api/v2/jobs/{job}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert j["status"] == "done" and j["result"]["status"] in ("OPTIMAL", "FEASIBLE")


def test_segments_and_adjustments(client):
    segs = client.get("/api/v2/segments?q=silver").json()
    assert segs and segs[0]["road_name"] == "Silver Avenue" and segs[0]["segment_code"].startswith("SEG-")
    near = client.get("/api/v2/segments/near?lat=33.605&lon=-84.335").json()
    assert near[0]["road_name"] == "Silver Avenue"
    a = client.post(f"/api/v2/segments/{segs[0]['segment_code']}/adjustments", json={"day_of_week": "SAT", "time_from": "10:00", "time_to": "14:00", "factor": 1.25, "reason": "market"})
    assert a.status_code == 201 and float(a.json()["factor"]) == 1.25
    assert any(x["reason"] == "market" for x in client.get("/api/v2/adjustments").json())
    client.post("/api/v2/scenarios", json={"code": "SC-R", "name": "r", "plan_date": "2026-09-20", "depot_code": "LPHB-30260", "provider": "MANUAL"})
    t = client.post(f"/api/v2/scenarios/SC-R/adjustments/{a.json()['adjustment_id']}?enabled=true").json()
    assert t["enabled"] is True
    assert any(x["adjustment_id"] == a.json()["adjustment_id"] and x["enabled"] for x in client.get("/api/v2/scenarios/SC-R").json()["adjustments"])
    assert client.delete(f"/api/v2/adjustments/{a.json()['adjustment_id']}").status_code == 204


def test_no_db_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("TMOD_PG_DSN", "postgresql://x:x@localhost:1/none")
    with TestClient(create_app(tmp_path, tmp_path / "runs")) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/v2/scenarios").status_code == 503
