"""W03: QA DB re-extraction jobs + DB health. Contract: docs/nodes/w03_refresh_health.md"""
from __future__ import annotations

import shutil
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def default_extractor(hub: str, crt_by: str | None, out: Path) -> Path:
    from extract_lmd import main  # noqa: PLC0415 — scripts/ import, only when a refresh runs
    return main(hub=hub, crt_by=crt_by, out=out)


def db_health(timeout_s: float = 3.0) -> dict:
    try:
        import oracledb  # noqa: F401
        from ora import creds
        u, p, d = creds()
        host, rest = d.split(":", 1)
        port, sid = rest.split("/", 1)
        import oracledb as odb
        t0 = time.time()
        params = odb.ConnectParams(host=host, port=int(port), sid=sid, user=u, password=p, disable_oob=True, tcp_connect_timeout=timeout_s)
        with odb.connect(params=params) as con, con.cursor() as cur:
            cur.execute("SELECT 1 FROM dual")
            cur.fetchone()
        return {"ok": True, "latency_ms": round((time.time() - t0) * 1000), "sid": sid}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"}


class RefreshJobs:
    def __init__(self, data_dir: Path, extractor=default_extractor) -> None:
        self.data_dir, self.extractor = data_dir, extractor
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.jobs: dict[str, dict] = {}
        self._health: tuple[float, dict] | None = None

    def health(self, ttl: float = 30.0) -> dict:
        if self._health is None or time.time() - self._health[0] > ttl:
            self._health = (time.time(), db_health())
        return self._health[1]

    def submit(self, hub: str, crt_by: str | None) -> str:
        job_id = uuid.uuid4().hex[:8]
        self.jobs[job_id] = {"job_id": job_id, "status": "queued", "hub": hub, "crt_by": crt_by}
        self.pool.submit(self._run, job_id, hub, crt_by)
        return job_id

    def _run(self, job_id: str, hub: str, crt_by: str | None) -> None:
        j = self.jobs[job_id]
        j["status"] = "running"
        try:
            out = self.data_dir / f"lmd_{hub.lower().replace('-', '')}_{crt_by or 'all'}"
            self.extractor(hub, crt_by, out)
            if not (out / "distance_truth.csv").exists():
                src = next((p / "distance_truth.csv" for p in self.data_dir.glob(f"lmd_{hub.lower().replace('-', '')}_*")
                            if p != out and (p / "distance_truth.csv").exists()), None)
                if src:
                    shutil.copy(src, out / "distance_truth.csv")
            rows = sum(1 for _ in open(out / "shipments.csv")) - 1
            j.update(status="done", dataset=out.name, rows=rows, truth=(out / "distance_truth.csv").exists())
        except Exception as e:  # noqa: BLE001
            j.update(status="error", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-1500:])

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)
