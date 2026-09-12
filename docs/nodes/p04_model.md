# P04 — OR-Tools Model Builder + Solve

상태: REVIEW (승인 대기)
버전: 1.0

## 책임
DB만 읽어 OR-Tools routing 모델을 만들고, 결과를 DB 결과 테이블에 적재한다. **비즈니스 값은 전부 DB 행**(vehicle/vehicle_type, scenario_constraint.params, scenario_objective_weight, road_adjustment). 코드에는 제약의 "형태"만 있다.

흐름(스펙 17단계 매핑): scenario 로드 → 시나리오 shipment/vehicle(+override) → **Stop 생성**(같은 delivery_location·같은 window 묶음, service = Σ shipment.service_s 또는 service_time_rule: stop_base 1회 + per_unit×pieces) → 거리·시간 = `distance_cache`(provider/profile, 누락 시 provider로 fill) → ROAD_ADJUSTMENT 켜지면 `adjusted_duration`(출발 = shift_start 근사) → 제약 차원 → 목적함수 → solve → route sequence·arrival/departure → cost → `optimization_run` / `optimization_route` / `optimization_unassigned`

## 제약 → OR-Tools 표현 (enabled_flag만 반영)
| constraint_code | 표현 |
|---|---|
| CAPACITY_WEIGHT / CAPACITY_VOLUME | demand 차원, 차량 용량(scenario_vehicle override > vehicle_type) |
| SERVICE_TIME | time 차원 transit에 stop service 포함 |
| TIME_WINDOW | time cumul 범위 [window_start, window_end], 대기 slack ≤ params.max_wait_s |
| WORK_LIMIT | service 합 차원 ≤ vehicle.work_limit_s |
| DUTY_LIMIT | time 차원 span ≤ min(vehicle.duty_limit_s, type.max_route_s) |
| MAX_DISTANCE | distance 차원 ≤ type.max_distance_m |
| VEHICLE_COMPAT | vehicle_restriction(allow_flag=false) → 해당 노드 허용 차량 집합에서 제외 |
| OPTIONAL_DROP | optional shipment: disjunction penalty = Σ drop_penalty 또는 params.default_penalty. 비optional은 큰 페널티(infeasible 회피, unassigned 사유 `INFEASIBLE_DROPPED`). Stop 단위 판정: 같은 위치·window에 비optional이 하나라도 있으면 그 stop은 비optional |
| SOFT_TIME_WINDOW | window_end soft upper bound, 초당 penalty = params.penalty_per_min/60 |
| ROAD_ADJUSTMENT | 시간 행렬에 시나리오 선택 조정 적용 |

## 목적함수
`scenario_objective_weight`(합 100)로 arc 비용 합성: COST → (cost_per_km·km + cost_per_hour·h), TRAVEL_TIME → s, DISTANCE → m, VEHICLE_COUNT → 차량 고정비(fixed_cost + 가중 상수), LATENESS → soft bound 계수. 정수 스케일 ×100.

## Interface
```python
from tmod.product.model import build_stops, load_scenario, populate_scenario, ScenarioData
from tmod.product.solve import run_scenario, SolveResult
run_scenario(con, scenario_code: str, provider: RoadProvider | None = None) -> SolveResult(run_id, status, vehicles, stops, unassigned, total_distance_m, total_route_s, total_cost)
populate_scenario(con, scenario_id) -> int   # plan_date == requested_date shipment를 scenario_shipment에 추가(없는 것만)
```
CLI: `uv run python -m tmod.product.solve SC-2026-09-15-BASE [--provider OSRM|VALHALLA]`

## 승인 기준 (테스트, pg + Mock provider)
1. 6 shipment/3 location, 트럭 2대(용량 제한) → OPTIMAL/FEASIBLE, 모든 shipment route에 1회, 용량·window 준수, run 합계 = route 합
2. optional shipment + drop_penalty 작음 + 용량 부족 → unassigned에 기록, 비optional은 배정
3. vehicle_restriction으로 특정 차량 금지 → 그 차량 route에 해당 stop 없음
4. VEHICLE_COUNT 가중 100% vs DISTANCE 100% → 차량 수 ≤
5. 실 dev DB 시나리오(2026-09-25, 65 shipment) 스모크 (skip-if-no-db)

## 알려진 한계 (ponytail)
- 시간대 조정은 출발 시각 근사(정적 행렬). 시간 의존 행렬은 Phase 3 후속
- P&D(PICKUP_DELIVERY), multi-depot 미구현 → kind=DELIVERY만, 나머지는 unassigned 사유 `UNSUPPORTED_KIND`
