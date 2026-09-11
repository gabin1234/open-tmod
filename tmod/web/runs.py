"""W01: datasets registry + run execution/store. Contract: docs/nodes/w01_api.md"""
from __future__ import annotations

import csv
import json
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from tmod.lmd_baseline import baseline, evaluate_loads, prepare_lmd
from tmod.lmd_compare import compare_routes
from tmod.lmd_optimize import LmdScenario, optimize
from tmod.web.serialize import run_to_json

DATA_DIR = Path("data/private")
RUNS_DIR = Path("data/runs")


def _count(path: Path) -> int:
    with open(path, newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def list_datasets(data_dir: Path = DATA_DIR) -> list[dict]:
    out = []
    for d in sorted(p for p in data_dir.glob("lmd_*") if (p / "shipments.csv").exists()):
        out.append({"id": d.name, "path": str(d), "shipments": _count(d / "shipments.csv"),
                    "trucks": _count(d / "trucks.csv") if (d / "trucks.csv").exists() else 0,
                    "extracted_at": datetime.fromtimestamp((d / "shipments.csv").stat().st_mtime).isoformat(timespec="minutes"),
                    "has_truth": (d / "distance_truth.csv").exists(), "has_calibration": (d / "calibration.json").exists()})
    return out


class RunStore:
    """Runs execute one at a time in a worker thread; results persist as data/runs/<id>.json."""

    def __init__(self, data_dir: Path = DATA_DIR, runs_dir: Path = RUNS_DIR) -> None:
        self.data_dir, self.runs_dir = data_dir, runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1)  # ponytail: single worker; raise if the team queues up
        self.prepared: dict[tuple[str, str | None], tuple] = {}
        self.lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _write(self, run_id: str, doc: dict) -> None:
        tmp = self._path(run_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc))
        tmp.replace(self._path(run_id))

    def submit(self, dataset: str, scenario: LmdScenario, valhalla_url: str | None) -> str:
        folder = self.data_dir / dataset
        if not (folder / "shipments.csv").exists():
            raise FileNotFoundError(dataset)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self._write(run_id, {"run_id": run_id, "dataset": dataset, "scenario": asdict(scenario), "valhalla_url": valhalla_url,
                             "created_at": datetime.now().isoformat(timespec="seconds"), "status": "queued"})
        self.pool.submit(self._execute, run_id, folder, scenario, valhalla_url)
        return run_id

    def _execute(self, run_id: str, folder: Path, sc: LmdScenario, valhalla_url: str | None) -> None:
        doc = self.get(run_id)
        try:
            doc["status"] = "running"
            self._write(run_id, doc)
            key = (folder.name, valhalla_url)
            with self.lock:
                if key not in self.prepared:
                    self.prepared[key] = prepare_lmd(folder, valhalla_url)
            lmd, providers, cal = self.prepared[key]
            base = baseline(lmd, providers)
            loads, orep = optimize(lmd, providers, sc)
            scen = evaluate_loads(lmd, loads, providers, keep_order=True)
            cmp = compare_routes(sc.name, base, scen, orep.unrouted, cal.within_tolerance)
            if hasattr(providers[0], "flush"):
                providers[0].flush()
            self._write(run_id, {**run_to_json(run_id, folder.name, asdict(sc), doc["created_at"], cal, orep, lmd.hub, cmp, base, scen),
                                 "valhalla_url": valhalla_url})
        except Exception as e:  # noqa: BLE001 — surfaced to the client as status=error
            doc.update(status="error", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-2000:])
            self._write(run_id, doc)

    def get(self, run_id: str) -> dict:
        return json.loads(self._path(run_id).read_text())

    def exists(self, run_id: str) -> bool:
        return self._path(run_id).exists()

    def delete(self, run_id: str) -> None:
        self._path(run_id).unlink()

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.runs_dir.glob("*.json"), reverse=True):
            d = json.loads(p.read_text())
            item = {k: d.get(k) for k in ("run_id", "dataset", "created_at", "status", "error")}
            item["scenario_name"] = (d.get("scenario") or {}).get("name")
            if d.get("status") == "done":
                k = d["kpi"]
                item["kpi_summary"] = {f: [k["baseline"][f], k["scenario"][f]] for f in ("loads", "miles", "duty_min", "late_stops", "over_duty")}
                item["gate_passed"] = d["gate"]["passed"]
            out.append(item)
        return out
