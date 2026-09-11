"""W05: shipment xlsx -> LMD dataset folder. Contract: docs/nodes/w05_upload.md"""
from __future__ import annotations

import csv
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import openpyxl

REQUIRED = ("shipment_id", "delivery_date")
COPY = ("trucks.csv", "zone_zip.csv", "params.csv", "distance_truth.csv", "calibration.json")
OUT_COLS = ("shipment_id", "hub_cd", "ship_to_id", "req_capa_min", "status_cd", "appt_dt", "zip_cd", "lat", "lon", "zone_cd",
            "charge_min", "stop_base_min", "tot_wgt", "tot_cuft", "item_cnt", "load_id", "appt_truck_id", "appt_window",
            "order_type", "addr_line", "purchase_order")


def _zones(template: Path) -> list[tuple[str, str, str]]:
    p = template / "zone_zip.csv"
    if not p.exists():
        return []
    rows = list(csv.DictReader(open(p, newline="")))
    rows.sort(key=lambda r: (int(r["zip_to"]) - int(r["zip_from"]) if r["zip_to"].isdigit() and r["zip_from"].isdigit() else 0,
                             -int(r.get("match_priority") or 0)))
    return [(r["zip_from"], r["zip_to"], r["zone_cd"]) for r in rows]


def _stop_base(template: Path) -> int:
    p = template / "params.csv"
    if p.exists():
        for r in csv.DictReader(open(p, newline="")):
            if r["param_cd"] == "STOP_BASE_MIN":
                return int(r["param_val"])
    return 20


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def convert_xlsx(xlsx: str | Path, template: Path, out: Path, hub: str = "LPHB-30260") -> dict:
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip().lower() if h is not None else "" for h in next(rows)]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if "zip" not in header and not ("latitude" in header and "longitude" in header):
        raise ValueError("need 'zip' or 'latitude'+'longitude'")
    ix = {h: i for i, h in enumerate(header)}
    g = lambda r, c: _cell(r[ix[c]]) if c in ix and ix[c] < len(r) else ""  # noqa: E731
    zones, base = _zones(template), _stop_base(template)
    zone_of = lambda z: next((zc for lo, hi, zc in zones if lo <= z <= hi), "")  # noqa: E731

    out.mkdir(parents=True, exist_ok=True)
    ship_to: dict[tuple[str, str], str] = {}
    n = 0
    unknown_zone = 0
    days: set[str] = set()
    with open(out / "shipments.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OUT_COLS)
        for r in rows:
            sid = g(r, "shipment_id")
            if not sid:
                continue
            zip_ = re.sub(r"\D", "", g(r, "zip"))[:5].zfill(5) if g(r, "zip") else ""
            key = (g(r, "address").lower(), zip_) if g(r, "address") else (sid, zip_)
            st = ship_to.setdefault(key, f"A{len(ship_to) + 1:04d}")
            svc = int(float(g(r, "service_minutes") or 0))
            zone = zone_of(zip_) if zip_ else ""
            unknown_zone += not zone
            days.add(g(r, "delivery_date"))
            w.writerow([sid, hub, st, base + svc, "SOFT_ALLOC", g(r, "delivery_date"), zip_, g(r, "latitude"), g(r, "longitude"), zone,
                        svc, base, g(r, "weight_lb"), g(r, "volume_cuft"), g(r, "pieces"), g(r, "load_id"), g(r, "truck_id"),
                        g(r, "window"), g(r, "order_type"), g(r, "address"), g(r, "purchase_order")])
            n += 1
    if n == 0:
        raise ValueError("no shipment rows")
    for name in COPY:
        if (template / name).exists():
            shutil.copy(template / name, out / name)
    (out / "README.md").write_text(f"Uploaded from {Path(xlsx).name} at {datetime.now():%Y-%m-%d %H:%M}. {n} shipments, "
                                   f"{len(ship_to)} ship-to, {len(days)} days. Template: {template.name}. "
                                   f"customer_name/phone/notes dropped. Confidential.\n")
    return {"dataset": out.name, "rows": n, "stops": len(ship_to), "days": len(days), "unknown_zone": unknown_zone}
