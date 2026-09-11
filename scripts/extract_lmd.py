"""Node 00 adapter (LMD track): TMS_IF.LMD_SHIPMENT + masters (AICTMSNQ, read-only) -> CSVs.

Excludes customer contact columns (CUST_NM, CUST_PHONE, CUST_EMAIL, MEMO).
Usage: uv run --extra extract python scripts/extract_lmd.py [--hub LPHB-30260] [--crt-by demo] [--out DIR]
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ora import connect  # noqa: E402

SHIPMENTS = """
SELECT SHIPMENT_ID, SRC_SHIPMENT_ID, PLAN_ID, ORDER_NO, LOAD_NO, CLONE_TYPE, PARENT_SHIP_ID, ORDER_TYPE, INTAKE_PATH,
       CHANNEL_CD, CUST_CD, ORDER_DTM, PICK_DTM, MM_DEPART_DTM, HUB_ARR_DTM,
       HUB_CD, DC_CD, SHIP_TO_ID, SHIP_TO_NM, ADDR_LINE, ZIP_CD, LAT, LON, ZONE_CD,
       SVC_CD, SVC_TIER, ITEM_CNT, TOT_CUFT, TOT_WGT, INSTALL_MIN, CHARGE_MIN, STOP_BASE_MIN, REQ_CAPA_MIN, CAPA_RULE_DESC,
       DATA_ERR_CD, RAD_ORG, RAD_CUR, RDD, HUB_RDD, ETA_HUB_ARR_DT, EARLIEST_DT,
       SUGGEST_DT_1, SUGGEST_DT_2, SUGGEST_DT_3, SUGGEST_FAIL_CD, REQ_DT, APPT_DT, APPT_ZONE_CD, APPT_TRUCK_ID,
       APPT_WINDOW, APPT_TIME, LOAD_ID, FINAL_NOTICE_DTM, STATUS_CD, RUNG_NO, RESCHED_CNT, RED_FLAG_YN, MANUAL_YN,
       RULE_VER, CRT_DTM, CRT_BY
FROM TMS_IF.LMD_SHIPMENT WHERE HUB_CD = :hub AND (:crt_by IS NULL OR CRT_BY = :crt_by) ORDER BY APPT_DT, LOAD_ID, SHIPMENT_ID"""

MASTERS = {
    "trucks": "SELECT * FROM TMS_IF.LMD_MST_TRUCK WHERE HUB_CD = :hub",
    "zones": "SELECT * FROM TMS_IF.LMD_MST_ZONE WHERE HUB_CD = :hub",
    "zone_zip": "SELECT * FROM TMS_IF.LMD_MST_ZONE_ZIP WHERE HUB_CD = :hub",
    "params": "SELECT PARAM_CD, PARAM_VAL FROM TMS_IF.LMD_MST_PARAM",
    "capa_stop": "SELECT * FROM TMS_IF.LMD_CAPA_STOP WHERE HUB_CD = :hub",
    "loads_view": "SELECT * FROM TMS_IF.V_LMD_LOAD WHERE HUB_CD = :hub",
}


def dump(cur, sql: str, binds: dict, path: Path) -> int:
    cur.execute(sql, {k: v for k, v in binds.items() if f":{k}" in sql})
    cols = [d[0].lower() for d in cur.description]
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        while rows := cur.fetchmany():
            w.writerows(rows)
            n += len(rows)
    print(f"{path.name:>16}: {n:>6} rows")
    return n


def main(hub: str = "LPHB-30260", crt_by: str | None = "demo", out: Path | None = None) -> Path:
    out = out or Path("data/private") / f"lmd_{hub.lower().replace('-', '')}_{crt_by or 'all'}"
    out.mkdir(parents=True, exist_ok=True)
    binds = {"hub": hub, "crt_by": crt_by}
    with connect() as con, con.cursor() as cur:
        cur.arraysize = 5000
        dump(cur, SHIPMENTS, binds, out / "shipments.csv")
        for name, sql in MASTERS.items():
            dump(cur, sql, binds, out / f"{name}.csv")
    (out / "README.md").write_text(
        f"Source: AICTMSNQ TMS_IF.LMD_SHIPMENT (+ LMD_MST_*, LMD_CAPA_STOP, V_LMD_LOAD). HUB={hub}, CRT_BY={crt_by}. "
        f"Extracted {datetime.now():%Y-%m-%d %H:%M}. Customer contact columns excluded. Do not commit.\n")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    kw = {}
    if "--hub" in a:
        kw["hub"] = a[a.index("--hub") + 1]
    if "--crt-by" in a:
        v = a[a.index("--crt-by") + 1]
        kw["crt_by"] = None if v == "all" else v
    if "--out" in a:
        kw["out"] = Path(a[a.index("--out") + 1])
    print(main(**kw))
