# P02 — Source Mapping + ETL

상태: REVIEW (승인 대기)
버전: 1.0

## 책임
`source_mapping_master` 행을 읽어 소스 행(BY 조회 결과, 추출 CSV, xlsx)을 `location` / `customer` / `shipment` 표준형으로 변환·적재한다. 소스별 코드는 **행 공급자(reader)** 뿐이고, 컬럼 해석은 전부 매핑 테이블이 결정한다 → TMS 교체 = 매핑 행 교체.

- 규칙 레지스트리 (`transformation_rule`): `zip5`, `lb_to_kg`, `cuft_to_m3`, `min_to_s`, `int`, `float`, `date`, `upper`, `prefix:X`, `const:X`, `window_start_of:COL`, `window_end_of:COL` ("08:00-12:00" + 날짜 컬럼 → timestamptz). 미등록 규칙 → ValueError (조용히 무시 금지)
- 적재 순서: location(upsert by location_code) → customer(upsert by customer_code) → shipment(upsert by source_system+source_ref; delivery_location_id·customer_id 해소). `source_snapshot`에 원본 행 보존
- 좌표 없는 location은 Node 05 `ZipCentroidGeocoder`로 채움 (`geocode_source='ZCTA'`)
- 필수(source_ref, requested_date, delivery location) 없으면 skip + 사유 집계. 예외로 중단하지 않음
- BY 접근은 `scripts/ora.py`(SELECT-only) 경유. DML 없음

## Interface
```python
from tmod.product.etl import load_rows_csv, load_rows_by, load_rows_xlsx, run_etl, EtlReport
run_etl(con, system_code: str, rows: Iterable[dict], hub_code: str | None = None) -> EtlReport(rows, shipments, locations, customers, geocoded, skipped: dict[str,int])
```
CLI: `uv run python -m tmod.product.etl --system BLUE_YONDER --csv data/private/lmd_lphb30260_demo/shipments.csv`
     `uv run --extra extract python -m tmod.product.etl --system BLUE_YONDER --db --hub LPHB-30260 --crt-by demo`
     `uv run python -m tmod.product.etl --system XLSX --xlsx sample.xlsx`
seed `db/seed/003_mapping_xlsx.sql`: XLSX 매핑 12행.

## 승인 기준 (테스트, docker pg)
1. CSV 3행(LMD 컬럼) → shipment 3, location 2(같은 ship_to 병합), customer 1, weight lb→kg, window 08:00-12:00 → timestamptz, service min→s
2. 재실행 → 건수 동일(멱등), 값 변경 시 UPDATE 반영
3. requested_date 없는 행 → skipped["no_requested_date"]
4. 미등록 rule → ValueError
5. xlsx 행 → XLSX 매핑으로 적재 (PII 컬럼 customer_name은 customer.name으로만, phone 미적재)
6. 실 추출 CSV 있으면 548행 적재 스모크 (skip-if-missing)
