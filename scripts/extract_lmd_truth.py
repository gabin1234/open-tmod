"""Node 00 v1.1: Atlanta 1Y historical xlsx -> distance_truth.csv (hub->zip actual LM miles, aggregated, no PII).

Usage: uv run --with openpyxl python scripts/extract_lmd_truth.py "<xlsx path>" [--out data/private/lmd_lphb30260_demo/distance_truth.csv]
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

BLANK = {None, "", " ", "NULL", "N/A", "-", "141"}  # '141' = export placeholder for null


def main(xlsx: str, out: Path) -> None:
    ws = openpyxl.load_workbook(xlsx, read_only=True)["raw"]
    rows = ws.iter_rows(values_only=True)
    ix = {h: i for i, h in enumerate(next(rows))}
    seen: set = set()
    per_zip: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        load, z, mi, hub = r[ix["LM_LOAD_ID"]], r[ix["END_ZIP"]], r[ix["LM_MILE_DISTANCE"]], r[ix["AGENT_ZIP"]]
        if load in BLANK or z in BLANK or mi in BLANK or load in seen:
            continue
        try:
            mi = float(mi)
        except (TypeError, ValueError):
            continue
        seen.add(load)
        per_zip[(str(hub).strip()[:5], str(z).strip()[:5].zfill(5))].append(mi)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hub_zip", "zip", "n_loads", "median_miles", "mean_miles", "min_miles", "max_miles"])
        for (hub, z), v in sorted(per_zip.items()):
            w.writerow([hub, z, len(v), round(statistics.median(v), 1), round(statistics.mean(v), 1), min(v), max(v)])
    print(f"{len(seen)} loads -> {len(per_zip)} hub-zip rows -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    out = Path(a[a.index("--out") + 1]) if "--out" in a else Path("data/private/lmd_lphb30260_demo/distance_truth.csv")
    main(a[0], out)
