# P08 — Phase 2: Multiple Depot

상태: FROZEN (2026-09-12 승인)
버전: 1.0 (P04 v1.2, P06 표시 확장)

## 범위
- `scenario.settings.multi_depot = true`이면 차량은 **자기 `vehicle.depot_id`** 에서 출발·복귀. false(기본)면 기존처럼 시나리오 depot 하나
- 모델: `RoutingIndexManager(N, V, starts, ends)` — depot 노드 = 시나리오 차량들의 distinct depot 위치, stop 노드는 그 뒤. 거리·시간 행렬은 depot 위치 전부 포함
- PICKUP 회수는 차량 자기 depot에서 하차. P&D는 depot 무관
- 결과: `optimization_route` DEPOT 행의 `stop_location_id` = 차량 depot 위치
- 시나리오 생성 시 차량 자동 선택은 여전히 시나리오 depot 소속만. multi_depot 시나리오는 PUT `vehicles`로 다른 depot 차량 추가
- UI: 시나리오 편집에 "multi-depot" 체크(settings), 지도에 depot 마커 여러 개(차량별 route의 시작 위치)

## 승인 기준 (테스트)
1. depot 2개(서로 먼 위치), 각 depot 차량 1대, 각 depot 근처 shipment 3건씩, multi_depot=true → 각 차량이 자기 depot 근처만 배송, DEPOT 행 위치 = 차량 depot
2. 같은 데이터 multi_depot=false → 모든 route가 시나리오 depot에서 시작
3. 기존 테스트 회귀 없음

## 알려진 한계 (ponytail)
- 차량 depot 고정(출발=복귀). open route/다른 depot 복귀는 요구 시
