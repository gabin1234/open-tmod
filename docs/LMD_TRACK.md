# LMD Routing Track — Master Graph 적용 (2026-09-11)

방향 전환: TL 비용 재현 대신 **LMD(Last Mile Delivery) 라우팅 최적화**. 데이터 = `TMS_IF.LMD_SHIPMENT` @ AICTMSNQ (Atlanta hub LPHB-30260). Master Graph 14 Node 순서와 게이트 방식은 그대로, 각 Node의 도메인 해석만 바꾼다. 기존 FROZEN Node는 재사용하고, LMD 전용 로직은 `tmod/lmd*.py` 신규 모듈로 추가한다 (기존 계약 불변).

## 데이터 현황 (실측 2026-09-11)
| 항목 | 값 |
|------|----|
| LMD_SHIPMENT (CRT_BY=demo) | 548건, APPT_DT 2026-09-01~10-05, 35 zip, 6 zone, 좌표 NULL |
| Baseline 대상 (LOAD_ID 있음, OPTIMIZED/HARD_CONSUME) | 232건 / 68 load / 27일 |
| 트럭 | 10대 BOX26 2MAN, 작업 500분, 근무 600분, 08:00–18:00 |
| 파라미터 | STOP_BASE_MIN 20, TRAVEL_MIN_PER_STOP 15(고정), TRUCK_PICK_RULE PACK, 4H window 08–12 등 |
| Zone | zip 범위 → Z1~Z6 (LMD_MST_ZONE_ZIP 42행), CENTER_LAT/LON NULL |
| 실적 거리 | LMD_SHIPMENT에 없음. `LPHB-ATLANTA-1Y-HISTORICAL-SHIPMENTS_v2.xlsx` raw: 16,281건 hub→zip `LM_MILE_DISTANCE` (load 단위, 331 zip) |

demo 데이터는 v4 시뮬레이터 실적을 +64일 시프트한 것. Cloning Job 정식 가동(송에릭, 09/17) 후 실 clone으로 교체 가능 — 어댑터 파라미터 `--crt-by all`.

## Node 매핑
| NN | Node | LMD 해석 | 상태 |
|----|------|----------|------|
| 00 | Extract (adapter) | `scripts/extract_lmd.py`: LMD_SHIPMENT + 마스터 → CSV. Atlanta xlsx → `distance_truth.csv` | 이번 |
| 01 | Ingestion | 재사용 | FROZEN |
| 02 | Validation | `LMD_SCHEMAS` 추가 (shipments: shipment_id, appt_dt, hub_cd, zip_cd, zone_cd, req_capa_min, load_id, truck_id; trucks; zone_zip). `validate(tables, schemas=LMD_SCHEMAS)` — 기존 함수 그대로 | 다음 |
| 03 | Canonical | `LmdDataset(hub: Location, stops: tuple[Stop], trucks, zones, params)`. Stop = ship_to 단위 묶음(shipment 여러 개), service_min = STOP_BASE_MIN + Σ CHARGE_MIN | 다음 |
| 04 | Address | 재사용 (zip 정규화) | FROZEN |
| 05 | Geocoding | 재사용. hub 30260 + 35 zip → ZCTA centroid | FROZEN |
| 06 | Routing | 재사용. **게이트 여기서**: haversine×circuity vs Atlanta `LM_MILE_DISTANCE` (hub→zip, 16k건) ±2%. 실패 시 Valhalla(Georgia OSM) | FROZEN + 캘리브레이션 |
| 07 | Rating | LMD 비용 없음 → 거리·시간 비용 함수 (mi × $/mi, 트럭 일당) 옵션. POC 생략 가능 | 보류 |
| 08 | Baseline | 실적 LOAD_ID 그대로 → 각 load의 stop 방문 순서(STOP_SEQ 없음 → 최근접 순) → Provider로 거리·시간. KPI: load 수, stop/load, 총 mi, 트럭 duty 분, 600분 초과 건수 | 다음 |
| 09 | Scenario | 규칙: 트럭 수 변경, zone 병합 허용, window 변경, TRAVEL_MIN 고정→실거리 | 다음 |
| 10 | Optimization | **일별 VRP** (OR-Tools routing solver = 운영 최적화, 허용): depot=hub, stop service_min, 차량 10대, 작업 500분·근무 600분(주행 포함), zone 제약, 목표 = 트럭 수 → 거리 | 다음 |
| 11 | Simulation | stub 재사용 | FROZEN |
| 12 | Re-rating | 시나리오 route 거리·시간 재계산 (Node 08 함수 재사용) | 다음 |
| 13 | Comparison | 재사용 + route KPI (load 수, mi, duty 분, 초과 건수) | 확장 |
| 14 | Map | hub + stop 마커, load별 polyline 색상 | 확장 |

## 게이트 재정의
- 기존 "Baseline 비용 ±2%" → **"Baseline 거리 ±2%"**: Node 06 Provider가 Atlanta 실적 hub→zip 거리 합계를 ±2% 이내로 재현해야 Node 09 이후 절감(거리·트럭) 수치 논의 허용.
- Baseline load 구성은 LMD_SHIPMENT `LOAD_ID` 그대로이므로 재현 오차 없음. stop 순서만 모델 가정 (최근접) — Comparison에서 baseline·scenario 동일 규칙 적용.

## 하지 않는 것 (POC)
- Appointment Suggest / Capacity 차감 로직 재구현 (Nate 엔진 영역). 우리는 확정 APPT_DT 이후 라우팅만
- 실시간 연동, DB 쓰기. 읽기 전용 추출 → CSV → 모델
