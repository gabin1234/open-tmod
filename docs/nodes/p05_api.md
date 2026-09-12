# P05 — Product API

상태: REVIEW (승인 대기)
버전: 1.0
기존 W01 앱(`tmod/web/app.py`)에 `/api/v2/*` 라우터로 마운트. DB = PostgreSQL(P01), 실행 = P04. 연결은 요청마다 psycopg 커넥션(`TMOD_PG_DSN`), DB 불가 시 503.

## 엔드포인트
| 영역 | Method Path | 비고 |
|---|---|---|
| Master | GET/POST `/api/v2/master/{table}` · PUT/DELETE `/api/v2/master/{table}/{code}` | table ∈ vehicle_type, vehicle, depot, customer, location, product, service_time_rule. 허용 컬럼 화이트리스트, code = 자연키. DELETE = active_flag=false (soft) |
| Shipment | GET `/api/v2/shipments?date=&limit=` · POST `/api/v2/shipments/upload` (xlsx → P02 ETL) · POST `/api/v2/shipments/refresh` (BY → P02, job) | |
| Scenario | GET `/api/v2/scenarios` · POST (code,name,plan_date,depot_code,provider,time_limit_s; 차량 전부·제약 phase1 기본·가중치 50/30/20 자동) · GET `/{code}` (제약·가중치·차량·shipment 수·조정) · PUT `/{code}` (constraints/weights/vehicles/settings/time_limit) · POST `/{code}/copy` (6 테이블 복제, 새 code) · DELETE · POST `/{code}/populate` · POST `/{code}/run` (job, `?wait=1`이면 동기) · GET `/{code}/runs` | |
| Result | GET `/api/v2/runs/{id}` (run + vehicle별 route: stops·시각·거리·leg geometry) · GET `/api/v2/compare?a=&b=` (두 run 지표 delta) | geometry는 distance_cache에 있으면 첨부 |
| Road | GET `/api/v2/segments?q=` (도로명 검색) · GET `/api/v2/segments/near?lat&lon` (가장 가까운 등록 segment 5개) · POST `/api/v2/segments/{code}/adjustments` (day_of_week, time_from, time_to, factor, reason) · GET/DELETE adjustments · POST `/api/v2/scenarios/{code}/adjustments/{id}?enabled=` | 사용자는 segment_code·road_name만 |
| Jobs | GET `/api/v2/jobs/{id}` | queued/running/done/error |

## 승인 기준 (테스트, pg fixture + TestClient)
1. master vehicle_type 생성/수정/soft delete, 화이트리스트 밖 컬럼 422
2. scenario 생성 → populate → run?wait=1 → runs 목록 → result에 route·stops, compare(a,b) delta
3. copy → 새 code, 제약·가중치·차량 수 동일, 원본 불변
4. segment 검색·adjustment 등록·시나리오 토글
5. DB 없이 앱 기동 → `/api/v2/scenarios` 503, 기존 `/api/health` 200

## 알려진 한계 (ponytail)
- 인증 없음(W04 토큰 미들웨어 공유). 실행 큐 1 워커
- 페이징 없음(limit만). 팀 규모 데이터엔 충분
