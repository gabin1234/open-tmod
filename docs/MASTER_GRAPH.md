# Open T-Modeler — Master Graph

## 목적
CSV 원본 데이터에서 시작해 Baseline 재현 → Scenario 최적화 → Baseline vs Scenario 비교 → 비용/서비스 영향 분석까지 수행하는 개방형 Transportation Modeling Platform.

## 진행 방식 (Graph Engineering)
각 Node는 다음 게이트를 순서대로 통과한다. 게이트를 건너뛰지 않는다.

1. **Contract** — `docs/nodes/NN_name.md` 작성 (Input, Output, 책임, 비책임, 오류, 승인 기준)
2. **Implement** — `tmod/NN_name.py` 한 모듈
3. **Test** — `tests/test_NN_name.py`, `uv run pytest -q` 통과
4. **Approve** — 사용자 승인
5. **Freeze** — 상태를 FROZEN으로 변경, git tag `node-NN`. 이후 재생성 금지. 변경은 새 contract 버전 + 재승인.

토큰 절약: FROZEN Node는 코드 전체를 다시 읽지 않고 contract의 Interface 섹션만 참조한다.

## Node 순서 (고정)

| NN | Node | 책임 | 핵심 라이브러리 | POC |
|----|------|------|----------------|-----|
| 01 | Ingestion | CSV bytes → RawTable (문자열 행 + provenance). 의미 해석 없음 | stdlib csv | 필수 |
| 02 | Validation | 필수 컬럼, 타입, 범위, 참조 무결성 검사. 오류 리포트 | stdlib | 필수 |
| 03 | Canonical Model | RawTable → Shipment, Stop, Carrier, RateCard 등 정규 도메인 객체 | dataclasses | 필수 |
| 04 | Address | 주소 문자열 정규화, 구성요소 분해, 중복 제거 | stdlib re | 필수 |
| 05 | Geocoding | 주소 → lat/lon. Provider 인터페이스 + 캐시. CSV에 좌표 있으면 pass-through | Provider (Nominatim/PC Miler) | 필수 (좌표 pass-through 우선) |
| 06 | Road Routing | O-D → 거리/시간. **Provider 책임**: PC Miler, Valhalla, haversine fallback. OR-Tools 사용 금지 | Provider adapter | 필수 (haversine fallback으로 시작) |
| 07 | Rating | Shipment + 거리 + RateCard → 비용. 요율 유형별 계산 (per-mile, flat, tiered, fuel) | stdlib decimal | 필수 |
| 08 | Baseline | 실제 이력 그대로 Rating 적용. **TMS 실적 대비 ±2% 이내 게이트** | — | 필수 |
| 09 | Scenario | Baseline 위에 변경 규칙 적용 (carrier 교체, 통합 윈도우, 거점 변경) | — | 필수 (1개 시나리오) |
| 10 | Optimization | Shipment Consolidation, Load Building, Carrier Assignment | OR-Tools (운영), Pyomo+HiGHS (네트워크 설계, POC 외) | 필수 (consolidation 1종) |
| 11 | Simulation | 동적 이벤트 시뮬레이션 (도착 변동, 용량 제약) | SimPy | POC 외 (pass-through stub) |
| 12 | Re-rating | Scenario 결과에 Node 07 재적용 | Node 07 재사용 | 필수 |
| 13 | Comparison | Baseline vs Scenario KPI: 총비용, 건수, 거리, 적재율, 서비스(리드타임) | stdlib | 필수 |
| 14 | Map | O-D 및 경로 시각화, KPI 카드 | folium 또는 단일 HTML | 필수 (간단) |

## 절대 규칙
- **Baseline ±2% 달성 전 시나리오 절감 수치 논의 금지.** Node 08 승인 전 Node 09~13은 구현은 가능하나 결과 수치는 보고하지 않는다.
- Routing은 Provider 인터페이스 뒤에 둔다. Provider 교체가 상위 Node에 영향을 주지 않아야 한다.
- OR-Tools는 Node 10 운영 최적화에만 사용한다.

## POC 범위
- 입력: CSV 업로드 (shipments, rates, 선택적으로 locations)
- 출력: Baseline vs One Scenario 비교 KPI + Map (HTML 1개)
- 기간: 5-8 작업일
- 토큰: 총 5-10M, Node별 추적 (docs/TOKEN_LEDGER.md)

## 일정 초안
| Day | Nodes |
|-----|-------|
| 1 | 01 Ingestion, 02 Validation |
| 2 | 03 Canonical, 04 Address, 05 Geocoding |
| 3 | 06 Routing (haversine → Valhalla), 07 Rating |
| 4 | 08 Baseline + ±2% 캘리브레이션 |
| 5 | 09 Scenario, 10 Optimization (consolidation) |
| 6 | 11 Simulation stub, 12 Re-rating, 13 Comparison |
| 7 | 14 Map + KPI |
| 8 | 버퍼 / 통합 테스트 |

## Node 상태
| NN | 상태 | 승인일 | tag |
|----|------|--------|-----|
| 01 | FROZEN | 2026-09-10 | node-01 |
| 02 | FROZEN | 2026-09-10 | node-02 |
| 03 | FROZEN | 2026-09-10 | node-03 |
| 04 | FROZEN | 2026-09-10 | node-04 |
| 05 | FROZEN | 2026-09-10 | node-05 |
| 06 | FROZEN | 2026-09-10 | node-06 |
| 07 | FROZEN | 2026-09-10 | node-07 |
| 08 | FROZEN (게이트: 실 데이터 대기) | 2026-09-10 | node-08 |
| 09 | FROZEN | 2026-09-10 | node-09 |
| 10 | FROZEN | 2026-09-10 | node-10 |
| 11 | FROZEN (stub) | 2026-09-10 | node-11 |
| 12 | FROZEN | 2026-09-10 | node-12 |
| 13 | FROZEN | 2026-09-10 | node-13 |
| 14 | FROZEN | 2026-09-11 | node-14 |

## POC v0.1 (2026-09-11, tag `poc-v0.1`)
14 Node 전부 FROZEN. 실행: `uv run python -m tmod.poc <folder> <scenario.json> <out.html> [--real-data]`
미완: Node 08 ±2% 게이트는 실 TMS 데이터 대기. 게이트 통과 전 비용 수치는 GATED.

## LMD Routing Track (2026-09-11~)
방향 전환: TL 비용 → LMD 라우팅 최적화. 매핑과 게이트 재정의는 [docs/LMD_TRACK.md](LMD_TRACK.md).
| Node | 상태 | 승인일 | tag |
|------|------|--------|-----|
| 00 Extract (LMD adapter) | FROZEN | 2026-09-11 | lmd-00 |
| 02/03 LMD schema + canonical | FROZEN | 2026-09-11 | lmd-0203 |
| 06 LMD distance calibration + gate | REVIEW | — | — |
