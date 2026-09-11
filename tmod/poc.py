"""POC end-to-end: CSV folder + scenario.json -> Baseline vs Scenario HTML. Order = Master Graph 01..14."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from tmod.baseline import calibrate, evaluate, load_knobs, prepare, save_knobs
from tmod.comparison import Comparison, compare
from tmod.map import write_html
from tmod.optimization import optimize
from tmod.rerating import rerate
from tmod.routing import HaversineProvider, route_matrix
from tmod.scenario import apply, load_scenario
from tmod.simulation import simulate


def run(folder: str | Path, scenario_path: str | Path, out_html: str | Path, real_data: bool = False,
        capacity_lb: Decimal | None = None) -> tuple[Comparison, Path]:
    folder = Path(folder)
    ds, reports = prepare({"shipments": folder / "shipments.csv", "rates": folder / "rates.csv"})   # 01-05
    kpath = folder / "baseline_knobs.json"
    if kpath.exists():
        base = evaluate(ds, load_knobs(kpath))                                                     # 06-08
    else:
        base = calibrate(ds)
        save_knobs(kpath, base.knobs)
    ds_base, _ = simulate(ds, base.matrix)                                                         # 11 (baseline transit KPI)

    scenario = load_scenario(scenario_path)
    ds_s, arep = apply(ds, scenario)                                                               # 09
    ds_s, oreps = optimize(ds_s, arep.pending)                                                     # 10
    matrix, _ = route_matrix(ds_s, [HaversineProvider(base.knobs.circuity, base.knobs.mph)])       # 06 for scenario
    ds_s, srep = simulate(ds_s, matrix)                                                            # 11
    bins = tuple(b for r in oreps for b in r.bins)
    rr = rerate(ds_s, base.knobs, bins=bins, baseline_ids=[s.id for s in ds.shipments])           # 12

    gate = base.within_tolerance and real_data
    cmp = compare(scenario.name, ds_base, base, ds_s, rr, gate, capacity_lb)                        # 13
    out = write_html(out_html, cmp, ds_base, ds_s, base.matrix, rr.matrix, rr)                     # 14

    for k, v in reports.items():
        print(f"[{k}] {v}")
    print(f"[baseline] {base.summary().splitlines()[2]}  (real_data={real_data})")
    print(f"[scenario] changed {len(arep.changed)}, consolidated bins {len(bins)}, shipments {len(ds.shipments)} -> {len(ds_s.shipments)}")
    print(cmp.summary())
    print(f"html -> {out}")
    return cmp, out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0], args[1], args[2] if len(args) > 2 else "poc.html", real_data="--real-data" in sys.argv)
