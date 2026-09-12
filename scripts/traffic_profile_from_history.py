"""P10: Atlanta history xlsx -> traffic_profile rows (OSRM free-flow baseline).

Usage: uv run --with openpyxl python scripts/traffic_profile_from_history.py "<xlsx>" [--osrm http://localhost:5001] [--apply] [--out CSV]
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tmod.canonical import Location  # noqa: E402
from tmod.geocoding import ZipCentroidGeocoder  # noqa: E402
from tmod.product.history import estimate_factors, merge_hours, service_estimate  # noqa: E402
from tmod.product.routing import OSRMProvider  # noqa: E402

BLANK = {None, "", "141", "N/A"}
DOW = {"WEEKDAY": ["MON", "TUE", "WED", "THU", "FRI"], "WEEKEND": ["SAT", "SUN"]}


def load_pairs(xlsx: str) -> tuple[list[tuple[str, str, dt.datetime, float]], list[float]]:
    ws = openpyxl.load_workbook(xlsx, read_only=True)["raw"]
    it = ws.iter_rows(values_only=True)
    ix = {h: i for i, h in enumerate(next(it))}
    routes: dict[tuple, dict] = defaultdict(dict)
    for r in it:
        e, z, load, rid = r[ix["END_DELIVERED"]], r[ix["END_ZIP"]], r[ix["LM_LOAD_ID"]], r[ix["ROUTE_ID"]]
        if not isinstance(e, dt.datetime) or z in BLANK or load in BLANK or rid in BLANK:
            continue
        routes[(rid, e.date())].setdefault(load, (e, str(z).strip()[:5].zfill(5)))
    pairs, same = [], []
    for stops in routes.values():
        seq = sorted(stops.values())
        for (ta, za), (tb, zb) in zip(seq, seq[1:]):
            gap = (tb - ta).total_seconds() / 60
            if gap <= 0 or gap > 300:
                continue
            (same if za == zb else pairs).append(gap if za == zb else (za, zb, ta, gap))
    return pairs, same


def freeflow(zips: set[str], osrm: str, cache: Path) -> dict[tuple[str, str], float]:
    have: dict[tuple[str, str], float] = {}
    if cache.exists():
        with open(cache, newline="") as f:
            have = {(r["a"], r["b"]): float(r["min"]) for r in csv.DictReader(f)}
    geo = ZipCentroidGeocoder()
    pts = {z: geo.geocode(Location(zip=z)) for z in zips}
    pts = {z: (g.lat, g.lon) for z, g in pts.items() if g}
    todo = sorted(z for z in pts if any((z, b) not in have for b in pts))
    if todo:
        prov = OSRMProvider(osrm)
        ids = sorted(pts)
        for i in range(0, len(todo), 50):
            src = todo[i:i + 50]
            for j in range(0, len(ids), 100):
                tgt = ids[j:j + 100]
                block = list(dict.fromkeys(src + tgt))
                _, dur = prov.matrix([pts[z] for z in block])
                k = {z: n for n, z in enumerate(block)}
                for a in src:
                    for b in tgt:
                        have[(a, b)] = (dur[k[a]][k[b]] or 0) / 60
        with open(cache, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["a", "b", "min"])
            w.writerows([a, b, round(m, 2)] for (a, b), m in have.items())
    return have


def main(xlsx: str, osrm: str, apply: bool, out: Path) -> None:
    pairs, same = load_pairs(xlsx)
    service = service_estimate(same)
    ff = freeflow({z for a, b, _, _ in pairs for z in (a, b)}, osrm, out.parent / "zip_freeflow_osrm.csv")
    obs = [(ta, gap, ff[(za, zb)]) for za, zb, ta, gap in pairs if (za, zb) in ff]
    factors = estimate_factors(obs, service, lo=1.0)   # free-flow is the floor: evening "faster than car" values are service-time noise
    merged = merge_hours(factors)
    print(f"pairs {len(pairs)} (same-zip {len(same)}), service estimate {service:.0f} min, usable {sum(1 for o in obs if o[2] >= 5)}")
    for dt_, h1, h2, f, n in merged:
        print(f"  {dt_:<8} {h1:02d}:00-{h2:02d}:00  x{f:.2f}  (n={n})")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["daytype", "from_hour", "to_hour", "factor", "n"])
        w.writerows(merged)
    print(f"-> {out}")
    if apply:
        from tmod.product.db import connect
        with connect() as con:
            con.execute("UPDATE traffic_profile SET active_flag=false WHERE source IN ('SAMPLE','HISTORICAL')")
            for dt_, h1, h2, fac, n in merged:
                for d in DOW[dt_]:
                    con.execute("INSERT INTO traffic_profile (day_of_week, time_from, time_to, factor, source) VALUES (%s::day_of_week, %s, %s, %s, 'HISTORICAL')",
                                (d, f"{h1:02d}:00", "24:00" if h2 >= 24 else f"{h2:02d}:00", fac))
            con.commit()
            print("applied:", con.execute("SELECT count(*) FROM traffic_profile WHERE active_flag AND source='HISTORICAL'").fetchone()[0], "rows active")


if __name__ == "__main__":
    a = sys.argv[1:]
    out = Path(a[a.index("--out") + 1]) if "--out" in a else Path("data/private/lmd_lphb30260_demo/traffic_profile_history.csv")
    main(a[0], a[a.index("--osrm") + 1] if "--osrm" in a else "http://localhost:5001", "--apply" in a, out)
