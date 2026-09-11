# Node 00 — Extract (LMD adapter)

상태: FROZEN (2026-09-11 승인)
버전: 1.0
위치: Master Graph 바깥(01 Ingestion 상류). 소스 시스템 의존 코드는 전부 여기 격리.

## 책임
- `TMS_IF.LMD_SHIPMENT`(HUB, CRT_BY 필터) + `LMD_MST_TRUCK`, `LMD_MST_ZONE`, `LMD_MST_ZONE_ZIP`, `LMD_MST_PARAM`, `LMD_CAPA_STOP`, `V_LMD_LOAD` → `data/private/lmd_<hub>_<crt_by>/*.csv`
- 고객 연락처 컬럼(CUST_NM, CUST_PHONE, CUST_EMAIL, MEMO) 제외
- 읽기 전용 SELECT. 자격증명 출력 금지 (`scripts/ora.py` 경유)
- (다음 버전) Atlanta xlsx → `distance_truth.csv` (zip, n, median_miles) — Node 06 캘리브레이션용

## Interface
```
uv run --extra extract python scripts/extract_lmd.py [--hub LPHB-30260] [--crt-by demo|all] [--out DIR]
```
출력: shipments.csv(548), trucks.csv(10), zones.csv(6), zone_zip.csv(42), params.csv(21), capa_stop.csv(329), loads_view.csv(68), README.md

## 승인 기준
1. 실행 성공, 행 수 위 표와 일치
2. shipments.csv에 cust_nm/cust_phone/cust_email 컬럼 없음
3. `data/private/` gitignore 확인

## 알려진 한계
- xlsx 변환 미포함 (Node 06 캘리브레이션 착수 시 추가)
- 테스트 없음: DB 의존 스크립트. 스키마 변경 시 실행 실패로 감지
