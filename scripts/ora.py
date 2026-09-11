"""Read-only Oracle query runner for AICTMSNQ (QA). SELECT only.

Credentials: env TMOD_ORA_USER / TMOD_ORA_PASSWORD / TMOD_ORA_DSN, else falls back to the
JDAext-Modules application-local.yml datasource. Never prints credentials.
Usage: uv run --extra extract python scripts/ora.py "SELECT ..." [--csv out.csv] [--max N]
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

import oracledb

YML = Path.home() / "orca/projects/JDAext-Modules/JDAext-Modules/backend/src/main/resources/application-local.yml"


def creds() -> tuple[str, str, str]:
    u, p, d = os.getenv("TMOD_ORA_USER"), os.getenv("TMOD_ORA_PASSWORD"), os.getenv("TMOD_ORA_DSN")
    if u and p and d:
        return u, p, d
    t = YML.read_text()
    m = re.search(r"jdbc:oracle:thin:@([\w.\-]+):(\d+)[:/](\w+)", t)
    host, port, sid = m.groups()
    u = re.search(r"^\s*username:\s*(\S+)", t, re.M).group(1)
    p = re.search(r"^\s*password:\s*(\S+)", t, re.M).group(1)
    return u, p, f"{host}:{port}/{sid}"


def connect():
    u, p, d = creds()
    host, rest = d.split(":", 1)
    port, sid = rest.split("/", 1)
    params = oracledb.ConnectParams(host=host, port=int(port), sid=sid, user=u, password=p, disable_oob=True)
    return oracledb.connect(params=params)


def run(sql: str, max_rows: int = 50, out_csv: str | None = None) -> None:
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        raise SystemExit("SELECT only")
    with connect() as con, con.cursor() as cur:
        cur.arraysize = 5000
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        if out_csv:
            n = 0
            with open(out_csv, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                while rows := cur.fetchmany():
                    w.writerows(rows)
                    n += len(rows)
            print(f"{n} rows -> {out_csv}")
            return
        rows = cur.fetchmany(max_rows)
        widths = [max(len(c), *(len(str(r[i])) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
        print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
        for r in rows:
            print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
        print(f"({len(rows)} rows shown)")


if __name__ == "__main__":
    sys.excepthook = lambda et, e, tb: print(f"ERROR: {str(e).splitlines()[0]}", file=sys.stderr)
    a = sys.argv[1:]
    out = a[a.index("--csv") + 1] if "--csv" in a else None
    mx = int(a[a.index("--max") + 1]) if "--max" in a else 50
    sql = a[0] if a and not a[0].startswith("--") else sys.stdin.read()
    run(sql, mx, out)
