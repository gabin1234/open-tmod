# Product Track — Master Graph (2026-09-11)

입력: `docs/PRODUCT_SPEC_v1.md`. 목표: 재사용 가능한 운송 최적화 플랫폼. 원칙: 비즈니스 규칙은 DB, OR-Tools는 엔진, BY는 읽기 전용 외부 소스, TMS 교체 시 엔진 무변경. 기존 tmod 엔진(FROZEN)은 P04에서 model builder의 참조 구현으로 재사용.

| PN | Node | 책임 | 산출물 |
|----|------|------|--------|
| P01 | Schema | PostgreSQL DDL 27 테이블 6 도메인, ENUM, PK/FK/UNIQUE/INDEX, audit·effective·active, 샘플 마스터, docker-compose(postgres), ERD | `db/ddl/001_schema.sql`, `db/seed/002_sample.sql`, `db/docker-compose.yml`, `docs/ERD.md` |
| P02 | Source Mapping + ETL | `source_mapping_master` 규칙 엔진, BY(LMD_SHIPMENT·마스터) → shipment/location/customer 적재, xlsx 업로드 동일 경로 | `tmod/product/etl.py` |
| P03 | Routing Data | OSRM docker(Georgia), `distance_cache`, `road_segment`(OSM way→edge→segment_id) 적재, `road_adjustment` 적용기 | `tmod/product/routing.py`, compose osrm |
| P04 | Model Builder | DB 시나리오·제약·목적함수 → OR-Tools 모델 (Phase 1 → 2 → 3 순차 확장), 결과 → optimization_run/route | `tmod/product/model.py`, `solve.py` |
| P05 | API | Scenario CRUD/copy/run/compare, Master CRUD, Road weight, Result 조회 | `tmod/product/api.py` |
| P06 | Frontend | Master · Scenario · Map(segment 선택) · Optimization · Result Comparison | `web/product/` |

게이트: Node별 contract → 구현 → 테스트(docker postgres) → 승인 → FROZEN(tag `prod-PNN`). 데이터 원칙: BY Oracle DML 금지(테스트로 강제), 하드코딩 금지(파라미터는 전부 DB 행).
