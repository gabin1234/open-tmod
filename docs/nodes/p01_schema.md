# P01 — PostgreSQL Schema

상태: FROZEN (2026-09-11 승인)
버전: 1.3 (P03 segment_durations_s; P07 stop_kind; P09 traffic_profile 테이블 — 모두 additive, 28 테이블)
의존성: psycopg[binary] (테스트·ETL), Docker(postgres:16)

## 도메인 / 테이블 (27)
| 도메인 | 테이블 | 핵심 |
|--------|--------|------|
| master | depot, vehicle_type, vehicle, vehicle_availability, customer, location, product, service_time_rule | 모든 마스터에 effective_from/to, active_flag, audit 4컬럼 |
| source | source_system, source_mapping_master, shipment, shipment_item | shipment은 소스 무관 표준형. source_system+source_ref UNIQUE로 재적재 멱등 |
| constraint | constraint_def, objective_def, vehicle_restriction | 제약·목적함수는 **정의 테이블** + 시나리오별 파라미터(jsonb) |
| scenario | scenario, scenario_shipment, scenario_vehicle, scenario_constraint, scenario_objective_weight, scenario_road_adjustment | copy = 6 테이블 복제. objective weight 합 100 체크는 API |
| routing | road_segment, road_adjustment, distance_cache | segment_id ← osm_way_id(+osrm edge) 매핑. adjustment = 요일·시간대·factor·reason |
| result | optimization_run, optimization_route, optimization_unassigned | 스펙 그대로 + 미배정(optional/penalty) |

ENUM: `shipment_kind`(DELIVERY, PICKUP, PICKUP_DELIVERY), `day_of_week`, `solver_status`(QUEUED, RUNNING, OPTIMAL, FEASIBLE, INFEASIBLE, ERROR, CANCELLED), `constraint_type`(HARD, SOFT), `scenario_status`(DRAFT, READY, RUNNING, DONE, ARCHIVED), `distance_provider`(OSRM, VALHALLA, PCMILER, HAVERSINE, MANUAL)

## 규칙
- PK = identity bigint, 자연키는 UNIQUE(code) 별도. FK 전부 명시, ON DELETE는 결과·시나리오 자식만 CASCADE
- 시간 = timestamptz, 거리 m, 시간 s, 무게 kg, 부피 m³ (변환은 ETL) — 단위 혼용 금지
- 하드코딩 금지 원칙의 DB 표현: `constraint_def.param_schema`(jsonb)로 파라미터 형태를 선언, `scenario_constraint.params`가 값
- 샘플: LPHB-30260 depot, LMD 트럭 10대(BOX26 2MAN 500/600분), constraint 8종, objective 3종, Silver Avenue 예시 segment·adjustment, 시나리오 1개

## Interface
```
db/docker-compose.yml        postgres:16, port 5434, volume, POSTGRES_DB=tmod
db/ddl/001_schema.sql        idempotent (DROP SCHEMA tmod CASCADE 옵션 주석), search_path tmod
db/seed/002_sample.sql       마스터·제약·목적·시나리오 샘플
uv run python -m tmod.product.db init [--seed]   DSN env TMOD_PG_DSN (기본 postgresql://tmod:tmod@localhost:5434/tmod)
```

## 승인 기준 (테스트, docker 없으면 skip)
1. 빈 DB에 DDL 적용 → 27 테이블, ENUM 6, FK ≥ 30
2. seed 적용 → vehicle 10, constraint_def 8, scenario 1, road_adjustment 1
3. FK 위반 INSERT 실패, UNIQUE(source_system, source_ref) 중복 실패
4. DDL 두 번 적용해도 오류 없음(idempotent)
