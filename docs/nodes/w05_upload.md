# W05 — Shipment Upload (xlsx → dataset)

상태: FROZEN (2026-09-11 전체 사전 승인 범위)
버전: 1.0

## 입력 포맷 (`sample_shipments_2026-09-11.xlsx`, 시트 "Shipments")
`shipment_id, purchase_order, delivery_date, order_type, customer_name, phone, address, city, state, zip, latitude, longitude, model_code, pieces, weight_lb, volume_cuft, service_minutes, notes`
- 필수: shipment_id, delivery_date, zip 또는 latitude+longitude
- 선택: service_minutes(기본 0), pieces, weight_lb, volume_cuft, order_type, address, window(`08:00-12:00`), load_id, truck_id
- customer_name, phone, notes는 **CSV로 옮기지 않음** (PII)

## 변환 규칙 (`tmod/web/upload.py: convert_xlsx`)
- ship_to_id = 같은 (address, zip) 묶음 → `A0001…`. 없으면 shipment별
- appt_dt = delivery_date, zip_cd = zip(5자리 0채움), lat/lon 그대로, zone_cd = 템플릿 데이터셋 zone_zip으로 산출
- stop_base_min = 템플릿 params STOP_BASE_MIN(20), charge_min = service_minutes, req_capa_min = 합
- status_cd = SOFT_ALLOC, load_id/appt_truck_id = 입력에 있으면 사용(=baseline), 없으면 빈값
- trucks.csv, zone_zip.csv, params.csv, distance_truth.csv, calibration.json = 템플릿 데이터셋에서 복사
- 출력 폴더 `data/private/lmd_upload_<name>/` + `README.md`(원본 파일명, 행 수, 변환 시각)

## API / UI
- `POST /api/datasets/upload` multipart `file`, form `name?`, `hub=LPHB-30260`, `template=<dataset id>` → `{dataset, rows, stops, days, unknown_zone}`
- `GET /api/datasets` 항목에 `baseline_loads` 추가. 0이면 프론트가 stop_pool을 `all`로 자동 전환 (baseline 없음 → 비교표 baseline 열 0)
- UI: Dataset 아래 "Upload shipments (.xlsx)" 파일 선택 + 업로드 → 완료 시 목록 갱신·선택

## 승인 기준 (테스트)
1. 합성 xlsx 3행(주소 2곳) → shipments.csv 3행, ship_to 2개, zone 산출, PII 컬럼 없음, 템플릿 파일 복사
2. 업로드 엔드포인트 → 데이터셋 목록에 등장, baseline_loads 0 → run(stop_pool=all) 성공
3. 필수 컬럼 누락 → 400

## 알려진 한계 (ponytail)
- 시트명·헤더 고정(소문자, 첫 시트). 헤더 alias는 Node 02 방식으로 필요 시 추가
- 다중 hub 미지원
