# P07 — Phase 2: Pickup & Delivery

상태: REVIEW (승인 대기)
버전: 1.0 (P04 v1.1, P02 v1.1, P01 v1.2 additive, P05/P06 표시 확장)

## 범위
- `shipment.kind`: `DELIVERY`(depot→고객, 기존) · `PICKUP`(고객→depot 회수) · `PICKUP_DELIVERY`(고객 A→고객 B 이동). `pickup_location_id`가 P&D의 출발지
- 모델: P&D 쌍은 노드 2개(pickup +demand, delivery −demand). `AddPickupAndDelivery` + 같은 차량 + pickup 선행(time cumul). PICKUP은 노드 1개(+demand, depot에서 하차). 용량 차원은 부호 있는 demand로 적재량 추적
- drop: 노드별 disjunction. 쌍 제약 때문에 한쪽이 빠지면 다른 쪽도 빠짐 → unassigned에 shipment 1행
- 결과: `optimization_route.stop_kind` (`DEPOT`|`PICKUP`|`DELIVERY`) 추가(v1.2 additive). `load_after_kg` 채움
- ETL: target_table `pickup_location` 지원(두 번째 위치 upsert → `pickup_location_id`), xlsx 매핑 행 추가(`kind`, `pickup_address/zip/latitude/longitude`), `kind` 규칙 `upper`
- UI: 시퀀스 표·지도 라벨에 P/D 표시, Shipments 표에 kind·pickup 열

## Interface 변경
- `load_scenario`: `Stop`에 `kind`, `pair_id`(P&D 쌍 식별), `demand_sign`. P&D shipment는 stop 그룹핑에서 제외(개별 노드)
- `optimization_route` INSERT에 `stop_kind`
- 스펙 §Phase 2 항목 중 이번: Pickup & Delivery. Vehicle Compatibility·Max Route Duration·Max Distance·Optional/Penalty는 P04에서 이미 구현. Multiple Depot는 별도 노드

## 승인 기준 (테스트, pg + Mock)
1. P&D 1건(L0→L2, 500kg) + 배송 4건, 용량 600: 같은 차량, pickup seq < delivery seq, 적재량 ≤ 600, stop_kind 정확
2. PICKUP 1건: route에 PICKUP 행, depot 복귀, load_after 증가
3. 용량 부족 + optional P&D → 쌍 전체 unassigned 1행
4. ETL xlsx: kind=PICKUP_DELIVERY 행 → pickup_location 생성·연결
5. 기존 Phase 1 테스트 전부 통과(회귀 없음)

## 알려진 한계 (ponytail)
- P&D 노드는 위치별 그룹핑 안 함(같은 위치 P&D 여러 건이면 stop_base 중복). 실 데이터 나오면 그룹핑 확장
- 시간창은 delivery 쪽만(pickup window 컬럼 없음). 필요 시 `pickup_window_*` 추가
