"""W01: FastAPI app. Run: uv run uvicorn tmod.web.app:app --host 0.0.0.0 --port 8080"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import secrets
import shutil
import subprocess
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


def _alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def valhalla_alive(url: str | None = None) -> bool:
    return _alive(f"{(url or os.getenv('TMOD_VALHALLA_URL', 'http://localhost:8002')).rstrip('/')}/status")


def osrm_alive(url: str | None = None) -> bool:
    return _alive(f"{(url or os.getenv('TMOD_OSRM_URL', 'http://localhost:5001')).rstrip('/')}/route/v1/driving/-84.334,33.587;-84.39,33.79?overview=false")


def postgres_health() -> dict:
    """Product DB (PostgreSQL). `db` in the same payload is the Blue Yonder Oracle source."""
    import time
    try:
        import psycopg
        from tmod.product.db import dsn
        t0 = time.time()
        with psycopg.connect(dsn(), connect_timeout=3) as con:
            con.execute("SELECT 1")
        return {"ok": True, "latency_ms": round((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e).splitlines()[0][:100]}"}


def _version() -> str:
    try:
        return subprocess.run(["git", "describe", "--tags", "--always"], capture_output=True, text=True, timeout=2, cwd=str(WEB_DIR.parent)).stdout.strip() or "dev"
    except Exception:  # noqa: BLE001
        return os.getenv("TMOD_VERSION", "dev")


def _users(spec: str | None) -> dict[str, str]:
    """TMOD_USERS="alice:pw,bob:pw" -> {user: sha256(pw)}"""
    out = {}
    for item in (spec or "").split(","):
        if ":" in item:
            u, pw = item.split(":", 1)
            out[u.strip()] = hashlib.sha256(pw.strip().encode()).hexdigest()
    return out


def create_app(data_dir: Path = DATA_DIR, runs_dir: Path = RUNS_DIR, extractor=default_extractor,
               token: str | None = None, users: str | None = None, lan_open: bool | None = None) -> FastAPI:
    """Access control (v1.1):
    - token (env TMOD_WEB_TOKEN): ?token= / Bearer / cookie — for API clients and shared links.
    - users (env TMOD_USERS="alice:pw,bob:pw"): HTTP Basic login (browser prompt), 30-day cookie.
    - lan_open (env TMOD_LAN_OPEN=1): private-IP clients not coming through the tunnel skip auth. Default off.
    With neither token nor users configured the app is open (dev)."""
    app = FastAPI(title="Open T-Modeler LMD")
    token = token if token is not None else os.getenv("TMOD_WEB_TOKEN")
    user_hashes = _users(users if users is not None else os.getenv("TMOD_USERS"))
    lan_open = lan_open if lan_open is not None else os.getenv("TMOD_LAN_OPEN", "0") == "1"
    session_key = hashlib.sha256(((token or "") + "|" + "|".join(sorted(user_hashes.values()))).encode()).hexdigest() if (token or user_hashes) else None

    if token or user_hashes:
        @app.middleware("http")
        async def require_auth(request: Request, call_next):
            client = request.client.host if request.client else ""
            try:
                private = ipaddress.ip_address(client).is_private and "cf-connecting-ip" not in request.headers
            except ValueError:
                private = False
            if lan_open and private:
                return await call_next(request)
            q = request.query_params.get("token")
            hdr = request.headers.get("authorization", "")
            ok = bool(token) and (bool(q and secrets.compare_digest(q, token)) or (hdr.startswith("Bearer ") and secrets.compare_digest(hdr[7:], token))
                                  or secrets.compare_digest(request.cookies.get("tmod_token", ""), token))
            ok = ok or (session_key is not None and secrets.compare_digest(request.cookies.get("tmod_session", ""), session_key))
            set_session = False
            if not ok and user_hashes and hdr.startswith("Basic "):
                try:
                    u, pw = base64.b64decode(hdr[6:]).decode().split(":", 1)
                    ok = u in user_hashes and secrets.compare_digest(user_hashes[u], hashlib.sha256(pw.encode()).hexdigest())
                    set_session = ok
                except Exception:  # noqa: BLE001
                    ok = False
            if not ok:
                headers = {"WWW-Authenticate": 'Basic realm="Open T-Modeler"'} if user_hashes and not request.url.path.startswith("/api/") else {}
                return JSONResponse({"detail": "login required" if user_hashes else "token required"}, status_code=401, headers=headers)
            if q and token and request.method == "GET" and not request.url.path.startswith("/api/"):
                resp = RedirectResponse(request.url.path or "/")
                resp.set_cookie("tmod_token", token, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
                return resp
            resp = await call_next(request)
            if set_session:
                resp.set_cookie("tmod_session", session_key, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
            return resp

    store = RunStore(data_dir, runs_dir)
    jobs = RefreshJobs(data_dir, extractor)
    app.state.store, app.state.jobs = store, jobs

    @app.get("/api/health")
    def health():
        du = shutil.disk_usage(str(data_dir if data_dir.exists() else Path(".")))
        return {"status": "ok", "version": _version(), "valhalla": valhalla_alive(), "osrm": osrm_alive(), "datasets": len(list_datasets(data_dir)),
                "db": jobs.health(), "postgres": postgres_health(), "disk_free_gb": round(du.free / 1e9, 1)}

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

        NO_CACHE = {"Cache-Control": "no-cache"}   # browsers otherwise keep stale index.html/app.js across deploys

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)

        @app.get("/product")
        def product_index():
            return FileResponse(WEB_DIR / "product" / "index.html", headers=NO_CACHE)

        @app.middleware("http")
        async def static_no_cache(request: Request, call_next):
            resp = await call_next(request)
            if request.url.path.startswith("/static/"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

    return app


app = create_app()
