"""W01: FastAPI app. Run: uv run uvicorn tmod.web.app:app --host 0.0.0.0 --port 8080"""
from __future__ import annotations

import urllib.request
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from tmod.lmd_optimize import LmdScenario
from tmod.web.runs import DATA_DIR, RUNS_DIR, RunStore, list_datasets

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


class ScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "vrp"
    trucks: int | None = None
    work_min: int | None = None
    duty_min: int | None = None
    stop_pool: str = "baseline"
    zone_penalty_min: int = 0
    time_limit_s: float = 5.0
    use_windows: bool = False


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: str
    scenario: ScenarioIn = ScenarioIn()
    valhalla_url: str | None = None


def valhalla_alive(url: str = "http://localhost:8002") -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/status", timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def create_app(data_dir: Path = DATA_DIR, runs_dir: Path = RUNS_DIR) -> FastAPI:
    app = FastAPI(title="Open T-Modeler LMD")
    store = RunStore(data_dir, runs_dir)
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"status": "ok", "valhalla": valhalla_alive(), "datasets": len(list_datasets(data_dir))}

    @app.get("/api/datasets")
    def datasets():
        return list_datasets(data_dir)

    @app.get("/api/scenarios/default")
    def default_scenario():
        return asdict(LmdScenario("vrp"))

    @app.post("/api/runs", status_code=202)
    def create_run(body: RunIn):
        sc = LmdScenario(**{f.name: getattr(body.scenario, f.name) for f in fields(LmdScenario)})
        try:
            run_id = store.submit(body.dataset, sc, body.valhalla_url)
        except FileNotFoundError:
            raise HTTPException(404, f"dataset not found: {body.dataset}")
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/runs")
    def runs():
        return store.list()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        if not store.exists(run_id):
            raise HTTPException(404, "run not found")
        return JSONResponse(store.get(run_id))

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str):
        if not store.exists(run_id):
            raise HTTPException(404, "run not found")
        store.delete(run_id)

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
