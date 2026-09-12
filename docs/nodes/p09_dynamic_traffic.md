# P09 — Phase 3: Dynamic Traffic · Historical Travel Time · Priority

상태: FROZEN (2026-09-12 승인)
버전: 1.0 (P01 v1.3 additive 테이블, P03 v1.1, P04 v1.3)

## 범위
1. **Historical travel time profile** — 새 테이블 `traffic_profile`(요일·시간대·factor·source·active). 구간 정보 없는 leg(행렬 캐시)에도 출발 시각 기준 전역 factor 적용. segment 조정이 있는 구간은 segment factor 우선. 시드는 `source='SAMPLE'`(07–09 ×1.35, 16–18:30 ×1.40 평일) — 실 이력 확보 시 교체
2. **Dynamic traffic (시간 의존 행렬)** — 제약 `DYNAMIC_TRAFFIC`(phase 3, params `iterations`=3). OR-Tools transit은 정적이므로 반복법: 1회차 출발=shift_start로 풀고 → 해의 leg별 실제 출발 시각으로 그 쌍의 duration 재계산 → 재풀이. route 시퀀스가 같아지거나 iterations 도달 시 종료. `optimization_run.engine_params.iterations_used` 기록
3. **Priority** — optional shipment drop 페널티에 우선순위 계수 적용: priority 1→×3, 2→×2, 3→×1.5, 4→×1.2, 5→×1. 비optional은 변화 없음

## Interface
- `adjusted_duration(..., depart_s)`: segment 없으면 `traffic_profile` factor × duration; segment 있으면 segment별(조정 없으면 profile factor)
- `matrices(con, data, provider, depart_by_pair=None)`: 쌍별 출발 시각 지정
- `constraint_def`: `ROAD_ADJUSTMENT` = 정적 적용(출발=shift_start), `DYNAMIC_TRAFFIC` = 반복 적용

## 승인 기준 (테스트)
1. traffic_profile 07–09 ×1.35: 08:00 출발 duration ×1.35, 10:00 출발 원값, 주말 원값
2. DYNAMIC_TRAFFIC 반복: 2회차 이상 실행되고 leg 출발 시각 기준 duration이 run 결과(travel_time_from_previous_s)에 반영
3. priority: 용량 1건분, optional 2건(priority 1 vs 5, 같은 drop_penalty) → priority 1 배정, 5 drop
4. 회귀 없음

## 알려진 한계 (ponytail)
- 반복법은 근사(수렴 보장 없음, 최대 iterations). 완전 시간 의존 VRP는 별도 엔진 필요
- traffic_profile은 전역 1세트(hub 구분 없음). 다중 hub 프로파일은 컬럼 추가로 확장
