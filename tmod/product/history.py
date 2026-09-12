"""P10: estimate time-of-day travel factors from delivery history. Contract: docs/nodes/p10_history_profile.md"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

DAYTYPE = lambda d: "WEEKDAY" if d.weekday() < 5 else "WEEKEND"  # noqa: E731


def service_estimate(same_zip_gaps_min: list[float], default: float = 30.0) -> float:
    return statistics.median(same_zip_gaps_min) if len(same_zip_gaps_min) >= 10 else default


def estimate_factors(pairs: list[tuple[datetime, float, float]], service_min: float, min_n: int = 30, min_freeflow: float = 5.0,
                     lo: float = 0.5, hi: float = 3.0) -> dict[tuple[str, int], tuple[float, int]]:
    """pairs = (departure datetime of leg, observed gap minutes, free-flow minutes). Returns {(daytype, hour): (median factor, n)}."""
    buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    for dep, gap, ff in pairs:
        if ff < min_freeflow:
            continue
        f = (gap - service_min) / ff
        buckets[(DAYTYPE(dep), dep.hour)].append(min(hi, max(lo, f)))
    return {k: (round(statistics.median(v), 3), len(v)) for k, v in buckets.items() if len(v) >= min_n}


def merge_hours(factors: dict[tuple[str, int], tuple[float, int]], tol: float = 0.05) -> list[tuple[str, int, int, float, int]]:
    """Merge adjacent hours with similar factors -> (daytype, from_hour, to_hour_exclusive, factor, n)."""
    out = []
    for dt_ in sorted({k[0] for k in factors}):
        hours = sorted(h for d, h in factors if d == dt_)
        cur = None
        for h in hours:
            f, n = factors[(dt_, h)]
            if cur and h == cur[2] and abs(f - cur[3]) < tol:
                tot = cur[4] + n
                cur = (dt_, cur[1], h + 1, round((cur[3] * cur[4] + f * n) / tot, 3), tot)
            else:
                if cur:
                    out.append(cur)
                cur = (dt_, h, h + 1, f, n)
        if cur:
            out.append(cur)
    return out
