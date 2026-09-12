# Open T-Modeler 제품화 스펙 v1 (사용자 제시, 2026-09-11)

원문 요지 보존. 다음 Graph 트랙("Product Track") 계약의 입력.

## 기능 Phase
- Phase 1: VRP — Capacity, Distance, Travel Time, Service Time, Time Window, Multi Stop
- Phase 2: Pickup & Delivery, Vehicle Compatibility, Max Route Duration, Max Distance, Multiple Depot, Optional Shipment, Penalty
- Phase 3: Dynamic Traffic, Historical Travel Time, Soft Time Window, Priority, Cost Optimization, Multi Objective, Scenario Comparison

## 최적화 처리 흐름 (17단계)
1 Scenario 생성 → 2 BY Shipment 조회 → 3 Location Mapping → 4 Vehicle Mapping → 5 Shipment→Stop → 6 OSRM Distance/Time → 7 Travel Adjustment → 8 Service Time → 9 Time Window → 10 Capacity → 11 Vehicle Constraint → 12 Objective Function → 13 OR-Tools Solve → 14 Route Sequence → 15 Arrival/Departure → 16 Cost → 17 Result 저장

## 결과 테이블
- optimization_run: run_id PK, scenario_id FK, start/end_time, solver_status, objective_value, vehicle_count, total_distance, total_drive_time, total_service_time, total_route_time, total_cost, created_at
- optimization_route: route_id PK, run_id FK, vehicle_id FK, route_sequence, stop_id FK, arrival_time, departure_time, service_time, distance_from_previous, travel_time_from_previous

## 필수 UI
A Scenario(create/copy/delete/run/compare) · B Vehicle(list, capacity, available time, depot, cost, type) · C Shipment(list, customer, address, weight, volume, service time, window, priority) · D Map(depot, customer, shipment, route, stop seq, OSM road, selected segment) · E Road Weight(segment 선택 → road name/segment id → day of week → time window → factor → reason → save)

## Road Segment 원칙
사용자에겐 도로명("Silver Avenue"). 내부: OSM Way → OSRM Edge → Open T-Modeler Segment ID. 사용자는 OSM/OSRM ID를 몰라도 됨.

## Blue Yonder 연동
READ ONLY. 우선 매핑: Vehicle, Shipment, Order, Location, Load, Stop, Customer, Delivery Window, Product, Quantity, Weight, Volume.
`source_mapping_master(mapping_id PK, source_system, source_table, source_column, target_table, target_column, transformation_rule, active_flag)`

## DB/배포
POC: Docker + PostgreSQL. docker-compose: PostgreSQL · Open T-Modeler API · OSRM · Frontend. OR-Tools는 API 레이어에서 실행, 전용 DB 없음.

## 개발 원칙
금지: BY Oracle INSERT/UPDATE/DELETE · OR-Tools 내부 비즈니스 마스터 하드코딩 · 도로 가중치/Service Time/Vehicle Capacity/Objective Weight 코드 하드코딩
DB/설정 관리: Vehicle Capacity, Service Time, Time Window, Road Adjustment, Vehicle Restriction, Constraint, Objective Weight, Scenario

## 최종 사용 시나리오
Scenario 2026-09-15: Shipment 100, Vehicle 20. Objective Cost 50% / Travel Time 30% / Vehicle Count 20%. Constraints Capacity·Time Window·Service Time·Max Route Time ON. Road Adjustment Silver Avenue 07:00-09:00 ×1.50 → [OPTIMIZE] → Vehicle별 Depot→Stop…→Depot, Distance/Drive/Service/Total/Cost.

## 산출물 요구
PostgreSQL DDL, ERD, 샘플 마스터, BY 매핑 구조, OSRM 연동, OR-Tools model builder, Scenario 관리, 최적화 실행 API, 결과 테이블, Frontend(Master/Scenario/Map/Optimization/Result Comparison). 도메인 분리(마스터·제약·목적함수·시나리오·라우팅·결과) 유지. TMS 교체 시 엔진 무변경.

## 다음 단계 (사용자 예고)
스펙을 한 번 더 발전시켜 PostgreSQL CREATE TABLE 실행 가능 수준(20~30 테이블, PK/FK/INDEX/ENUM/샘플)까지 정의 후 개발 착수.
