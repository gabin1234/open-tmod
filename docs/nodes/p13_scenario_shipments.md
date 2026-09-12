# P13 — 시나리오 ↔ Shipment 연결 (업로드 배치 → 시나리오 → 최적화)

상태: FROZEN (2026-09-12 승인)
버전: 1.0 (P01 v2.1 additive `shipment.source_batch`, P05/P06 확장)

## 문제
시나리오는 `plan_date = requested_date`인 shipment만 자동 포함했고, 어떤 shipment가 들어갔는지 화면에 없었다. 업로드한 shipment로 최적화하려면 날짜를 맞춰 시나리오를 만들어야 했고 그 경로가 화면에 없었다.

## 변경
- `shipment.source_batch`(text): 업로드/적재 배치 식별자(`xlsx:<파일명>:<시각>`, `by:<hub>:<crt_by>:<시각>`)
- API
  - `GET /api/v2/shipments/batches` — 배치별 건수·날짜 범위
  - `GET /api/v2/shipments?batch=` 필터 추가
  - `GET /api/v2/scenarios/{code}/shipments` — 시나리오 포함 shipment 목록
  - `POST /api/v2/scenarios/{code}/shipments` `{shipment_ids?:[…], batch?:str, date?:YYYY-MM-DD}` — 추가(중복 무시), 응답 `{added, total}`
  - `DELETE /api/v2/scenarios/{code}/shipments/{shipment_id}` — 제외
  - `DELETE /api/v2/scenarios/{code}/shipments` — 전부 제외
  - `POST /api/v2/scenarios` 에 `batch?` — 생성 시 그 배치 전부 포함(날짜 무관), `plan_date` 생략 시 배치 최빈 날짜
- UI
  - Shipments 탭: 업로드 완료 후 **"Create scenario from this upload"** 버튼 → code·plan_date 자동 제안 → 생성 → Scenarios 탭으로 이동
  - Scenario 상세: **Shipments 카드** — 포함 목록(ref·고객·zip·lb·window, 제외 ✕), 추가 도구: 날짜로 추가 / 배치로 추가 / 전체 제외
  - 시나리오 목록·상세 shipment 수 갱신

## 승인 기준 (테스트)
1. xlsx 업로드 → batch 생성, `/shipments/batches`에 표시, `POST /scenarios {batch}` → shipment_count = 업로드 건수(날짜 달라도)
2. 시나리오 shipment 추가(date/batch/ids)·제외·전체제외 API
3. 브라우저: 업로드 → "Create scenario from this upload" → Optimize → 결과
