# P14 — Scenarios 화면 재구성

상태: FROZEN (2026-09-13)
버전: 1.0 (web/product 만 변경, API 변경 없음)

## 문제
`/product` Scenarios 탭: 왼쪽 340px 카드에 목록 테이블(shpm/runs 컬럼)이 넘쳐 카드 밖으로 나가고, 생성 폼이 목록 아래 항상 펼쳐져 있었으며, 오른쪽은 "select a scenario" 한 줄. 상세는 카드 6개가 세로로 길게 나열되어 스크롤이 길었다.

## 변경 (web/product/index.html, app.js)
- 레이아웃 `500px | 1fr`. 목록은 `table-layout:fixed` + 컬럼 폭 지정, 날짜/숫자 nowrap, code 컬럼만 줄바꿈. 카드 내부 스크롤(52vh).
- 목록: code 아래 이름(코드와 다를 때) 표시, 상단 필터 입력(code·name·date·status 부분일치, 클라이언트 측), 선택 행 하이라이트.
- 새 시나리오 폼은 접힘(`<details>` "+ New scenario"), 생성 후 입력 초기화. 업로드 shipment 최적화 경로 안내 문구.
- 빈 상태: 3단계 안내(선택/설정/Optimize → Map). 삭제 후에도 동일 안내.
- 상세: 헤더 한 줄(code·status·name·plan date·depot·routing·time limit·multi-depot) + 액션 줄(Optimize/Save/Copy/Delete, shipments·runs 수, 메시지) + 서브탭 **Setup / Shipments (n) / Runs (n)**.
  - Setup: 좌 Constraints(params JSON), 우 Objective weights · Vehicles · Road adjustments 2단.
  - Shipments: 날짜/배치 추가, Populate, Remove all, 목록(52vh 스크롤).
  - Runs: run 목록(클릭 시 지도).
- Objective `DISTANCE` 단위 라벨 `m` → `mi` (seed + 002_imperial.sql UPDATE, 운영 DB 적용).

## 승인 기준
1. 목록 컬럼이 카드 안에 들어오고 6개 시나리오 모두 한 화면에 표시
2. 행 클릭 → 상세 헤더·서브탭 렌더, Shipments 탭에 포함 shipment 목록·배치 select 채워짐
3. `uv run pytest -q tests/test_product_api.py` 통과 (8 passed)

## 검증
브라우저(1568×779)에서 목록/상세/Shipments 서브탭 확인. 초기 구현에서 `loadScenarioShipments` 호출 누락으로 Shipments 탭이 비어 있던 것을 수정.
