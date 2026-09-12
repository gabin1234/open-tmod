"""W01: FastAPI app. Run: uv run uvicorn tmod.web.app:app --host 0.0.0.0 --port 8080"""
from __future__ import annotations

import ipaddress
import os
import secrets
import re
import tempfile
import urllib.request
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from tmod.lmd_optimize import LmdScenario
from tmod.product.api import build_router
from tmod.web.refresh import RefreshJobs, default_extractor
from tmod.web.runs import DATA_DIR, RUNS_DIR, RunStore, list_datasets
from tmod.web.upload import convert_xlsx

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


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hub: str = "LPHB-30260"
    crt_by: str | None = "demo"     # "all" or None -> every CRT_BY


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


def create_app(data_dir: Path = DATA_DIR, runs_dir: Path = RUNS_DIR, extractor=default_extractor,
               token: str | None = None) -> FastAPI:
    """token (or env TMOD_WEB_TOKEN): when set, every request needs ?token=, a Bearer header, or the cookie it sets.
    Meant for exposing the app beyond the LAN (ngrok) — the data is confidential."""
    app = FastAPI(title="Open T-Modeler LMD")
    token = token if token is not None else os.getenv("TMOD_WEB_TOKEN")

    if token:
        @app.middleware("http")
        async def require_token(request: Request, call_next):
            # Same-LAN clients (private IP, not via the Cloudflare tunnel) skip the token; tunnel traffic always needs it.
            client = request.client.host if request.client else ""
            try:
                private = ipaddress.ip_address(client).is_private and "cf-connecting-ip" not in request.headers
            except ValueError:
                private = False
            if private:
                return await call_next(request)
            q = request.query_params.get("token")
            hdr = request.headers.get("authorization", "")
            ok = bool(q and secrets.compare_digest(q, token)) or (hdr.startswith("Bearer ") and secrets.compare_digest(hdr[7:], token)) \
                or secrets.compare_digest(request.cookies.get("tmod_token", ""), token)
            if not ok:
                return JSONResponse({"detail": "token required"}, status_code=401)
            if q and request.method == "GET" and not request.url.path.startswith("/api/"):
                resp = RedirectResponse(request.url.path or "/")
                resp.set_cookie("tmod_token", token, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
                return resp
            return await call_next(request)

    store = RunStore(data_dir, runs_dir)
    jobs = RefreshJobs(data_dir, extractor)
    app.state.store, app.state.jobs = store, jobs

    @app.get("/api/health")
    def health():
        return {"status": "ok", "valhalla": valhalla_alive(), "datasets": len(list_datasets(data_dir)), "db": jobs.health()}

    @app.post("/api/datasets/upload", status_code=201)
    async def upload(file: UploadFile = File(...), name: str | None = Form(None), hub: str = Form("LPHB-30260"),
                     template: str | None = Form(None)):
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(400, "xlsx file required")
        ds = list_datasets(data_dir)
        tpl = data_dir / (template or next((d["id"] for d in ds if d["has_truth"]), ds[0]["id"] if ds else ""))
        if not (tpl / "trucks.csv").exists():
            raise HTTPException(400, f"template dataset not found: {tpl.name}")
        slug = re.sub(r"[^a-z0-9]+", "_", (name or Path(file.filename).stem).lower()).strip("_")[:40] or "upload"
        out = data_dir / f"lmd_upload_{slug}"
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(await file.read())
        try:
            return convert_xlsx(tmp.name, tpl, out, hub)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            Path(tmp.name).unlink(missing_ok=True)
            store.prepared.pop((out.name, None), None)
            for k in [k for k in store.prepared if k[0] == out.name]:
                store.prepared.pop(k)

    @app.post("/api/datasets/refresh", status_code=202)
    def refresh(body: RefreshIn):
        crt = None if body.crt_by in (None, "all") else body.crt_by
        return {"job_id": jobs.submit(body.hub, crt), "status": "queued"}

    @app.get("/api/refresh/{job_id}")
    def refresh_status(job_id: str):
        j = jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

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

    app.include_router(build_router())   # P05 product API (/api/v2), PostgreSQL-backed

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/product")
        def product_index():
            return FileResponse(WEB_DIR / "product" / "index.html")

    return app


app = create_app()
