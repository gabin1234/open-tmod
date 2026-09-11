import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tmod.web.app import create_app

SHIP = ("shipment_id,hub_cd,ship_to_id,req_capa_min,status_cd,appt_dt,zip_cd,zone_cd,charge_min,tot_wgt,item_cnt,load_id,appt_truck_id,appt_window\n"
        "S1,LPHB-30260,A1,50,OPTIMIZED,2026-09-01,30309,Z2,30,50,1,L1,T01,08:00-12:00\n"
        "S2,LPHB-30260,B2,50,OPTIMIZED,2026-09-01,30310,Z1,30,50,1,L1,T01,08:00-12:00\n"
        "S3,LPHB-30260,C3,50,OPTIMIZED,2026-09-01,30030,Z1,30,50,1,L2,T02,08:00-12:00\n"
        "S4,LPHB-30260,D4,50,OPTIMIZED,2026-09-02,30032,Z1,30,50,1,L3,T01,08:00-12:00\n")
TRUCKS = "truck_id,daily_work_min,daily_duty_min,shift_start_hh,shift_end_hh\nT01,500,600,08:00,18:00\nT02,500,600,08:00,18:00\n"
TRUTH = "hub_zip,zip,n_loads,median_miles,mean_miles,min_miles,max_miles\n" + "".join(
    f"30260,{z},5,{m},{m},{m},{m}\n" for z, m in [("30309", 20.1), ("30310", 15.3), ("30030", 18.0), ("30032", 14.2), ("30305", 22.0), ("30318", 19.5), ("30060", 25.0), ("30080", 21.0)])


@pytest.fixture
def client(tmp_path):
    d = tmp_path / "lmd_test"
    d.mkdir()
    (d / "shipments.csv").write_text(SHIP)
    (d / "trucks.csv").write_text(TRUCKS)
    (d / "distance_truth.csv").write_text(TRUTH)
    (tmp_path / "other.txt").write_text("x")
    app = create_app(tmp_path, tmp_path / "runs")
    with TestClient(app) as c:
        yield c


def _wait(c, run_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = c.get(f"/api/runs/{run_id}").json()
        if d["status"] in ("done", "error"):
            return d
        time.sleep(0.2)
    raise TimeoutError


def test_health_and_datasets(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["datasets"] == 1 and isinstance(h["valhalla"], bool)
    ds = client.get("/api/datasets").json()
    assert ds[0]["id"] == "lmd_test" and ds[0]["shipments"] == 4 and ds[0]["trucks"] == 2 and ds[0]["has_truth"]
    assert client.get("/api/scenarios/default").json()["stop_pool"] == "baseline"


def test_run_lifecycle(client):
    r = client.post("/api/runs", json={"dataset": "lmd_test", "scenario": {"name": "t", "time_limit_s": 1}})
    assert r.status_code == 202
    rid = r.json()["run_id"]
    d = _wait(client, rid)
    assert d["status"] == "done", d.get("error")
    assert d["kpi"]["baseline"]["loads"] == 3 and d["optimize"]["routed"] == 4 and d["gate"]["passed"] in (True, False)
    p = d["plans"]["scenario"][0]
    assert p["legs"][0]["miles"] > 0 and p["stops"][0]["lat"] is not None and p["day"] == "2026-09-01"
    assert d["hub"]["zip"] == "30260" and "loads" in d["kpi"]["summary"]
    lst = client.get("/api/runs").json()
    assert lst[0]["run_id"] == rid and lst[0]["status"] == "done" and lst[0]["kpi_summary"]["loads"] == [3, d["kpi"]["scenario"]["loads"]]
    assert client.delete(f"/api/runs/{rid}").status_code == 204
    assert client.get(f"/api/runs/{rid}").status_code == 404


def test_validation_errors(client):
    assert client.post("/api/runs", json={"dataset": "nope"}).status_code == 404
    assert client.post("/api/runs", json={"dataset": "lmd_test", "scenario": {"bogus": 1}}).status_code == 422
    assert client.get("/api/runs/zzz").status_code == 404
    assert client.get("/").status_code == 200 and "app.js" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


REAL = Path("data/private/lmd_lphb30260_demo")


@pytest.mark.skipif(not (REAL / "distance_truth.csv").exists(), reason="private extract not present")
def test_real_smoke(tmp_path):
    with TestClient(create_app(Path("data/private"), tmp_path / "runs")) as c:
        rid = c.post("/api/runs", json={"dataset": REAL.name, "scenario": {"name": "smoke", "time_limit_s": 1}}).json()["run_id"]
        d = _wait(c, rid, timeout=300)
        assert d["status"] == "done", d.get("error")
        assert d["kpi"]["baseline"]["loads"] == 68 and d["optimize"]["routed"] == 175


def _fake_extractor(hub, crt_by, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "shipments.csv").write_text(SHIP)
    (out / "trucks.csv").write_text(TRUCKS)
    return out


def _boom(hub, crt_by, out):
    raise RuntimeError("ORA-12170: TNS:Connect timeout")


def test_refresh_job_and_health(tmp_path):
    d = tmp_path / "lmd_lphb30260_demo"
    d.mkdir()
    (d / "shipments.csv").write_text(SHIP)
    (d / "trucks.csv").write_text(TRUCKS)
    (d / "distance_truth.csv").write_text(TRUTH)
    with TestClient(create_app(tmp_path, tmp_path / "runs", extractor=_fake_extractor)) as c:
        h = c.get("/api/health").json()
        assert "db" in h and isinstance(h["db"]["ok"], bool)
        job = c.post("/api/datasets/refresh", json={"hub": "LPHB-30260", "crt_by": "all"}).json()["job_id"]
        for _ in range(50):
            j = c.get(f"/api/refresh/{job}").json()
            if j["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert j["status"] == "done" and j["dataset"] == "lmd_lphb30260_all" and j["rows"] == 4 and j["truth"] is True
        assert {x["id"] for x in c.get("/api/datasets").json()} == {"lmd_lphb30260_demo", "lmd_lphb30260_all"}
        assert c.get("/api/refresh/nope").status_code == 404
    with TestClient(create_app(tmp_path, tmp_path / "runs", extractor=_boom)) as c:
        job = c.post("/api/datasets/refresh", json={}).json()["job_id"]
        for _ in range(50):
            j = c.get(f"/api/refresh/{job}").json()
            if j["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert j["status"] == "error" and "ORA-12170" in j["error"]


def test_token_auth(tmp_path):
    with TestClient(create_app(tmp_path, tmp_path / "runs", token="s3cret")) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert c.get("/api/health?token=s3cret").status_code == 200
        r = c.get("/?token=s3cret", follow_redirects=False)
        assert r.status_code in (302, 307) and "tmod_token" in r.cookies
        assert c.get("/api/health").status_code == 200  # cookie kept by client
        c.cookies.clear()
        assert c.get("/api/health", headers={"Authorization": "Bearer nope"}).status_code == 401
