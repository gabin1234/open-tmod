"""Node 00 adapter: Blue Yonder TMS (AICTMSNQ, read-only) -> CSVs for Node 01 Ingestion.

Load-leg level (1 load leg = 1 shipment for the model). Output folder is gitignored (data/private/).
Usage: uv run --extra extract python scripts/extract_bytms.py 2022-03-01 2022-04-01 [--srvc TL] [--stops 2] [--out DIR]
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ora import connect  # noqa: E402

LOADS = """
SELECT l.LD_LEG_ID shipment_id, TO_CHAR(l.SHPD_DTT,'YYYY-MM-DD') ship_date, l.CARR_CD carrier_id,
       ROUND(l.TOT_SCLD_WGT, 1) weight_lb, l.CHGD_AMT_DLR actual_cost,
       l.FRST_PSTL_CD origin_zip, l.FRST_CTY_NAME origin_city, l.FRST_STA_CD origin_state,
       l.LAST_PSTL_CD dest_zip, l.LAST_CTY_NAME dest_city, l.LAST_STA_CD dest_state,
       NULLIF(a.LATITUDE,0) origin_lat, NULLIF(a.LONGITUDE,0) origin_lon,
       NULLIF(b.LATITUDE,0) dest_lat, NULLIF(b.LONGITUDE,0) dest_lon,
       l.SRVC_CD "MODE", l.TOT_PCE pieces, l.TOT_SKID pallets,
       l.TFF_ID tff_id, l.RATE_CD rate_cd, l.EQMT_TYP equipment, l.MILE_DIST tms_miles,
       l.FRST_SHPG_LOC_CD origin_loc_cd, l.LAST_SHPG_LOC_CD dest_loc_cd, l.NUM_STOP num_stop, l.NUM_SHPM num_shpm,
       l.SYS_CALC_AMT_DLR sys_calc_cost, l.SPOT_RATE_YN spot_yn, l.FRST_CTRY_CD origin_country, l.LAST_CTRY_CD dest_country
FROM TMS_PROD.LD_LEG_T l
LEFT JOIN TMS_PROD.ADDR_T a ON a.ADDR_ID = l.FRST_ADDR_ID
LEFT JOIN TMS_PROD.ADDR_T b ON b.ADDR_ID = l.LAST_ADDR_ID
WHERE l.SHPD_DTT >= :d1 AND l.SHPD_DTT < :d2 AND l.SRVC_CD = :srvc AND l.NUM_STOP = :stops AND l.CHGD_AMT_DLR > 0
ORDER BY l.SHPD_DTT, l.LD_LEG_ID"""

TFF_SUBQ = """(SELECT DISTINCT l.TFF_ID FROM TMS_PROD.LD_LEG_T l
   WHERE l.SHPD_DTT >= :d1 AND l.SHPD_DTT < :d2 AND l.SRVC_CD = :srvc AND l.NUM_STOP = :stops AND l.CHGD_AMT_DLR > 0)"""

TARIFFS = f"""
SELECT t.TFF_ID tff_id, t.TFF_CD tff_cd, t.CARR_CD carrier_id, t.MSTR_TFF_ID master_tff_id,
       TO_CHAR(t.EFCT_DT,'YYYY-MM-DD') efct_dt, TO_CHAR(t.EXPD_DT,'YYYY-MM-DD') expd_dt, t.TFF_GRP_TYP grp
FROM TMS_PROD.TFF_T t WHERE t.TFF_ID IN {TFF_SUBQ} OR t.TFF_ID IN (SELECT MSTR_TFF_ID FROM TMS_PROD.TFF_T WHERE TFF_ID IN {TFF_SUBQ})"""

RATES = f"""
SELECT r.TFF_ID tff_id, r.RATE_CD rate_cd, r.CHRG_CD chrg_cd, r.RNG_CD rng_cd, r.SRVC_CD srvc_cd, r.EQMT_TYP_CD eqmt,
       r.FRHT_CLS_CD frht_cls, TO_CHAR(r.EFCT_DT,'YYYY-MM-DD') efct_dt, TO_CHAR(r.EXPD_DT,'YYYY-MM-DD') expd_dt,
       r.BS_CHRG_DLR bs_chrg, r.MIN_CHRG_DLR min_chrg, r.MAX_CHRG_DLR max_chrg,
       rr.RNG_TO rng_to, rr.CHRG_TYP_ENU chrg_typ, rr.BRK_BS_DLR brk_bs, rr.BRK_AMT_DLR brk_amt, rr.CLIP_YN clip_yn, r.RATE_ID rate_id
FROM TMS_PROD.RATE_T r LEFT JOIN TMS_PROD.RNG_RATE_T rr ON rr.RATE_ID = r.RATE_ID
WHERE (r.TFF_ID IN {TFF_SUBQ} OR r.TFF_ID IN (SELECT MSTR_TFF_ID FROM TMS_PROD.TFF_T WHERE TFF_ID IN {TFF_SUBQ}))
ORDER BY r.TFF_ID, r.RATE_CD, r.CHRG_CD, r.EFCT_DT, rr.RNG_TO"""

LANES = f"""
SELECT la.TFF_ID tff_id, la.RATE_CD rate_cd, la.SRVC_CD srvc_cd, la.ORIG_ZN_CD orig_zn, la.DEST_ZN_CD dest_zn,
       la.ORIG_SHPG_LOC_CD orig_loc, la.DEST_SHPG_LOC_CD dest_loc, la.ORIG_STA_CD orig_sta, la.DEST_STA_CD dest_sta,
       la.CDTY_CD cdty, la.BS_CHRG_DLR bs_chrg, la.MIN_CHRG_DLR min_chrg, la.STAT_ENU stat
FROM TMS_PROD.LANE_ASSC_T la WHERE la.TFF_ID IN {TFF_SUBQ}"""

CHARGES = """
SELECT c.LD_LEG_ID shipment_id, c.CHRG_CD chrg_cd, c.UNIT_TYP_ENU unit_typ, c.LKUP_UNIT lkup_unit, c.RATD_UNIT ratd_unit,
       c.CHGD_UNIT_RATE unit_rate, c.CHRG_AMT_DLR chrg_amt, c.DSCT_AMT_DLR dsct_amt, c.TOT_AMT_DLR tot_amt, c.TFF_ID tff_id
FROM TMS_PROD.CHRG_DETL_T c
WHERE c.CHRG_LVL_ENU = 2 AND c.LD_LEG_ID IN (SELECT l.LD_LEG_ID FROM TMS_PROD.LD_LEG_T l
   WHERE l.SHPD_DTT >= :d1 AND l.SHPD_DTT < :d2 AND l.SRVC_CD = :srvc AND l.NUM_STOP = :stops AND l.CHGD_AMT_DLR > 0)
ORDER BY c.LD_LEG_ID, c.CHRG_CD"""


def dump(cur, sql: str, binds: dict, path: Path) -> int:
    cur.execute(sql, binds)
    cols = [d[0].lower() for d in cur.description]
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        while rows := cur.fetchmany():
            w.writerows(rows)
            n += len(rows)
    print(f"{path.name:>14}: {n:>8} rows")
    return n


def main(d1: str, d2: str, srvc: str = "TL", stops: int = 2, out: Path | None = None) -> Path:
    out = out or Path("data/private") / f"bytms_{srvc.lower()}_{d1.replace('-', '')}_{d2.replace('-', '')}"
    out.mkdir(parents=True, exist_ok=True)
    binds = {"d1": datetime.fromisoformat(d1), "d2": datetime.fromisoformat(d2), "srvc": srvc, "stops": stops}
    with connect() as con, con.cursor() as cur:
        cur.arraysize = 5000
        dump(cur, LOADS, binds, out / "shipments.csv")
        dump(cur, TARIFFS, binds, out / "tariffs.csv")
        dump(cur, RATES, binds, out / "rates_raw.csv")
        dump(cur, LANES, binds, out / "lanes.csv")
        dump(cur, CHARGES, binds, out / "charges.csv")
    (out / "README.md").write_text(
        f"Source: AICTMSNQ (QA, prod snapshot to 2022) TMS_PROD.LD_LEG_T / CHRG_DETL_T / TFF_T / RATE_T / RNG_RATE_T / LANE_ASSC_T\n"
        f"Filter: SHPD_DTT [{d1}, {d2}), SRVC_CD={srvc}, NUM_STOP={stops}, CHGD_AMT_DLR>0. Extracted {datetime.now():%Y-%m-%d %H:%M}.\n"
        f"Confidential operational data — do not commit, do not share outside team.\n")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    kw = {}
    if "--srvc" in a:
        kw["srvc"] = a[a.index("--srvc") + 1]
    if "--stops" in a:
        kw["stops"] = int(a[a.index("--stops") + 1])
    if "--out" in a:
        kw["out"] = Path(a[a.index("--out") + 1])
    print(main(a[0], a[1], **kw))
