"""LMD POC end-to-end: folder (+ scenario.json) -> baseline vs optimized routes HTML. Order = Master Graph."""
from __future__ import annotations

import sys
from pathlib import Path

from tmod.lmd_baseline import baseline, evaluate_loads, prepare_lmd
from tmod.lmd_compare import RouteComparison, compare_routes
from tmod.lmd_map import write_lmd_html
from tmod.lmd_optimize import LmdScenario, load_lmd_scenario, optimize


def run(folder: str | Path, scenario: LmdScenario | str | Path | None = None, out_html: str | Path = "lmd_poc.html"
        ) -> tuple[RouteComparison, Path]:
    sc = scenario if isinstance(scenario, LmdScenario) else (load_lmd_scenario(scenario) if scenario else LmdScenario("vrp-default"))
    lmd, providers, cal = prepare_lmd(folder)                                   # 01-06
    base = baseline(lmd, providers)                                             # 08
    loads, orep = optimize(lmd, providers, sc)                                  # 09-10
    scen = evaluate_loads(lmd, loads, providers, keep_order=True)               # 12
    cmp = compare_routes(sc.name, base, scen, orep.unrouted, cal.within_tolerance)   # 13
    out = write_lmd_html(out_html, cmp, base, scen, lmd.hub)                    # 14
    print(f"gate {'PASS' if cal.within_tolerance else 'FAIL'} (test gap {cal.test_gap_pct:+.2f}%, a={cal.a:.2f} b={cal.b:.3f})")
    print(f"optimize: days {orep.days}, stops {orep.stops}, routed {orep.routed}, loads {orep.loads}, status {orep.solver_status}")
    print(cmp.summary())
    print(f"html -> {out}")
    return cmp, out


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0], a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else "lmd_poc.html")
