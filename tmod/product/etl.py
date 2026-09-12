"""P02: source_mapping_master driven ETL into location/customer/shipment. Contract: docs/nodes/p02_etl.md"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

import psycopg

from tmod.canonical import Location
from tmod.geocoding import ZipCentroidGeocoder
from tmod.product.db import SEED, connect

# ---------- transformation rules: (value, row, arg) -> value ----------
def _num(v):
    if v in (None, ""):
        return None
    return Decimal(str(v).replace(",", "").replace("$", ""))


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(f"bad date {v!r}")


def _window(v, row, arg, which):
    if v in (None, "") or "-" not in str(v):
        return None
    d = _date(row.get(arg.lower()))
    if d is None:
        return None
    hh = str(v).split("-")[0 if which == "start" else 1].strip()
    h, m = hh.split(":")[:2]
    return datetime(d.year, d.month, d.day) + timedelta(hours=int(h), minutes=int(m))


RULES: dict[str, Callable] = {
    "zip5": lambda v, r, a: (re.sub(r"\D", "", str(v))[:5].zfill(5) if v not in (None, "") else None),
    "lb_to_kg": lambda v, r, a: (None if _num(v) is None else _num(v) * Decimal("0.45359237")),
    "cuft_to_m3": lambda v, r, a: (None if _num(v) is None else _num(v) * Decimal("0.0283168")),
    "min_to_s": lambda v, r, a: (None if _num(v) is None else int(_num(v) * 60)),
    "int": lambda v, r, a: (None if _num(v) is None else int(_num(v))),
    "float": lambda v, r, a: (None if _num(v) is None else float(_num(v))),
    "date": lambda v, r, a: _date(v),
    "upper": lambda v, r, a: (str(v).strip().upper() if v not in (None, "") else None),
    "slug": lambda v, r, a: (re.sub(r"[^A-Z0-9]+", "-", str(v).strip().upper()).strip("-")[:60] if v not in (None, "") else None),
    "prefix": lambda v, r, a: (f"{a}{v}" if v not in (None, "") else None),
    "const": lambda v, r, a: a,
    "locid": lambda v, r, a: (f"ADDR-{hashlib.sha1((str(v).strip().lower() + '|' + str(r.get(a, '')).strip()).encode()).hexdigest()[:12]}" if v not in (None, "") else None),
    "window_start_of": lambda v, r, a: _window(v, r, a, "start"),
    "window_end_of": lambda v, r, a: _window(v, r, a, "end"),
}


def apply_rule(rule: str | None, value, row: dict):
    if rule in (None, ""):
        return None if value in (None, "") else (value.strip() if isinstance(value, str) else value)
    name, _, arg = rule.partition(":")
    if name not in RULES:
        raise ValueError(f"unknown transformation_rule {rule!r}")
    return RULES[name](value, row, arg)


@dataclass(frozen=True)
class Mapping:
    source_column: str
    target_table: str
    target_column: str
    rule: str | None


def load_mappings(con: psycopg.Connection, system_code: str) -> list[Mapping]:
    rows = con.execute("""SELECT m.source_column, m.target_table, m.target_column, m.transformation_rule
                          FROM source_mapping_master m JOIN source_system s ON s.source_system_id=m.source_system_id
                          WHERE s.system_code=%s AND m.active_flag AND (m.effective_to IS NULL OR m.effective_to >= CURRENT_DATE)
                          ORDER BY m.sort_order""", (system_code,)).fetchall()
    if not rows:
        raise ValueError(f"no active mappings for {system_code}")
    return [Mapping(*r) for r in rows]


def map_row(row: dict, mappings: list[Mapping]) -> dict[str, dict]:
    """Source row -> {"shipment": {...}, "location": {...}, "customer": {...}}. Keys matched case-insensitively."""
    lower = {str(k).lower(): v for k, v in row.items()}
    out: dict[str, dict] = {}
    for m in mappings:
        v = apply_rule(m.rule, lower.get(m.source_column.lower()), lower)
        if v is not None:
            out.setdefault(m.target_table, {})[m.target_column] = v
    return out


@dataclass
class EtlReport:
    rows: int = 0
    shipments: int = 0
    locations: int = 0
    customers: int = 0
    geocoded: int = 0
    skipped: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        return (f"rows {self.rows}: shipments {self.shipments}, locations {self.locations}, customers {self.customers}, "
                f"geocoded {self.geocoded}, skipped {dict(self.skipped)}")


def _upsert(con, table: str, key: str, values: dict) -> int:
    cols = list(values)
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != key) or f"{key}=EXCLUDED.{key}"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT ({key}) DO UPDATE SET {sets} RETURNING {table}_id")
    return con.execute(sql, [values[c] for c in cols]).fetchone()[0]


def run_etl(con: psycopg.Connection, system_code: str, rows: Iterable[dict], geocoder=None) -> EtlReport:
    mappings = load_mappings(con, system_code)
    sysid = con.execute("SELECT source_system_id FROM source_system WHERE system_code=%s", (system_code,)).fetchone()
    if not sysid:
        raise ValueError(f"unknown source_system {system_code}")
    sysid = sysid[0]
    geocoder = geocoder or ZipCentroidGeocoder()
    rep = EtlReport()
    loc_ids: dict[str, int] = {}
    cust_ids: dict[str, int] = {}
    for row in rows:
        rep.rows += 1
        m = map_row(row, mappings)
        sh, loc, cust, ploc = m.get("shipment", {}), m.get("location", {}), m.get("customer", {}), m.get("pickup_location", {})
        if not sh.get("source_ref"):
            rep.skipped["no_source_ref"] += 1
            continue
        if not sh.get("requested_date"):
            rep.skipped["no_requested_date"] += 1
            continue
        if not loc.get("location_code"):
            rep.skipped["no_location"] += 1
            continue
        code = loc["location_code"]
        if code not in loc_ids:
            if (loc.get("latitude") is None or loc.get("longitude") is None) and loc.get("postal_code"):
                g = geocoder.geocode(Location(zip=loc["postal_code"]))
                if g:
                    loc.update(latitude=g.lat, longitude=g.lon, geocode_source=f"ZCTA:{g.precision}")
                    rep.geocoded += 1
            loc_ids[code] = _upsert(con, "location", "location_code", loc)
            rep.locations += 1
        sh["delivery_location_id"] = loc_ids[code]
        if ploc.get("location_code"):
            pc = ploc["location_code"]
            if pc not in loc_ids:
                if (ploc.get("latitude") is None or ploc.get("longitude") is None) and ploc.get("postal_code"):
                    g = geocoder.geocode(Location(zip=ploc["postal_code"]))
                    if g:
                        ploc.update(latitude=g.lat, longitude=g.lon, geocode_source=f"ZCTA:{g.precision}")
                        rep.geocoded += 1
                loc_ids[pc] = _upsert(con, "location", "location_code", ploc)
                rep.locations += 1
            sh["pickup_location_id"] = loc_ids[pc]
            sh.setdefault("kind", "PICKUP_DELIVERY")
        if cust.get("customer_code"):
            cust.setdefault("name", cust["customer_code"])
            if cust["customer_code"] not in cust_ids:
                cust_ids[cust["customer_code"]] = _upsert(con, "customer", "customer_code", cust)
                rep.customers += 1
            sh["customer_id"] = cust_ids[cust["customer_code"]]
        sh["source_system_id"] = sysid
        sh["source_snapshot"] = json.dumps({str(k): (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}, default=str)
        cols = list(sh)
        con.execute(f"INSERT INTO shipment ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                    f"ON CONFLICT (source_system_id, source_ref) DO UPDATE SET " + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("source_system_id", "source_ref")),
                    [sh[c] for c in cols])
        rep.shipments += 1
    con.commit()
    return rep


# ---------- row readers ----------
def load_rows_csv(path: str | Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_rows_xlsx(path: str | Path) -> list[dict]:
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = [str(h).strip() if h is not None else "" for h in next(it)]
    return [dict(zip(hdr, r)) for r in it if any(v not in (None, "") for v in r)]


def load_rows_by(hub: str, crt_by: str | None) -> list[dict]:
    """Blue Yonder read-only SELECT via scripts/ora.py (SELECT-only guard lives there)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from extract_lmd import SHIPMENTS  # noqa: PLC0415
    from ora import connect as ora_connect  # noqa: PLC0415
    with ora_connect() as con, con.cursor() as cur:
        cur.execute(SHIPMENTS, {"hub": hub, "crt_by": crt_by})
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


if __name__ == "__main__":
    a = sys.argv[1:]
    system = a[a.index("--system") + 1] if "--system" in a else "BLUE_YONDER"
    if "--csv" in a:
        rows = load_rows_csv(a[a.index("--csv") + 1])
    elif "--xlsx" in a:
        rows = load_rows_xlsx(a[a.index("--xlsx") + 1])
    elif "--db" in a:
        rows = load_rows_by(a[a.index("--hub") + 1] if "--hub" in a else "LPHB-30260",
                            None if "--crt-by" in a and a[a.index("--crt-by") + 1] == "all" else (a[a.index("--crt-by") + 1] if "--crt-by" in a else "demo"))
    else:
        raise SystemExit(__doc__)
    with connect() as con:
        con.execute(SEED.parent.joinpath("003_mapping_xlsx.sql").read_text())
        print(run_etl(con, system, rows).summary())
