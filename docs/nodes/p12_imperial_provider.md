# P12 — 임페리얼 단위 통일 · Provider 단일화(Valhalla) · UI 견고화

상태: REVIEW (승인 대기)
버전: 1.0 (P01 v2.0 컬럼 rename, P02~P06 동반 수정)

## 단위 (미국 표준)
| 항목 | 이전 | 이후 |
|---|---|---|
| 무게 | kg (`*_kg`) | **lb** (`weight_lb`, `capacity_lb`, `unit_weight_lb`, `override_capacity_lb`, `load_after_lb`) |
| 부피 | m³ (`*_m3`) | **cuft** (`volume_cuft`, `capacity_cuft`, `unit_volume_cuft`) |
| 거리 | m (`*_m`) | **mi** (`distance_mi`, `max_distance_mi`, `total_distance_mi`, `distance_from_previous_mi`, `length_mi`) |
| 비용 | $/km | **$/mi** (`cost_per_mi`) |
| 시간 | 초 | 초 (변경 없음) |
마이그레이션 `db/ddl/002_imperial.sql`: 컬럼 rename + 값 변환(kg×2.20462, m³×35.3147, m÷1609.344, $/km×1.609344). 신규 설치는 001에 이미 임페리얼. ETL 규칙: `lb_to_kg`/`cuft_to_m3` 제거 → `float`. OR-Tools 내부 정수 = 0.01 mi 단위.

## Provider
제품 UI에서 **Valhalla(truck)만** 사용. 근거: 26ft 박스트럭 costing(높이·중량 제한 반영), edge마다 OSM way_id → 도로 구간 가중치(스펙 §26) 완전 지원, PC*MILER 실측 대비 −3.3%(OSRM car는 way_id 없음·승용차 프로파일). OSRM은 코드에 남기되(행렬 속도 이점, 이력 프로파일 추정용) 시나리오 생성 기본값·UI 선택지에서 제거.

## UI 견고화
- 시나리오 code 필수·패턴 검증(API 422 + 인라인), name 비면 code 사용, 삭제/복사 방어, 가중치 합 100·차량 1대 이상 검증(저장 전)
- `alert()` 제거 → 인라인 메시지 (브라우저 모달이 화면을 멈추던 문제)
- 422 응답의 pydantic detail을 읽을 수 있는 문장으로 표시

## 승인 기준
1. 마이그레이션 후 dev DB: 컬럼 rename 확인, 기존 shipment 무게가 lb로 변환(예: 45.36kg → 100lb)
2. 전체 테스트 통과(단위 기대값 갱신)
3. UI 표시 lb / cuft / mi, provider 선택지 없음(Valhalla 고정)
