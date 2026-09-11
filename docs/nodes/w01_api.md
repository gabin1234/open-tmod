# W01 — Backend API

상태: FROZEN (2026-09-11 승인)
버전: 1.0
의존성 추가: fastapi, uvicorn (dev: httpx)

## 책임
- 데이터셋 = `data/private/lmd_*` 폴더 (Node 00 추출 결과). 목록·메타(행 수, 추출일, distance_truth·calibration 유무)
- 실행 = (dataset, LmdScenario, valhalla_url) → 백그라운드 스레드에서 `tmod.lmd_poc` 순서 실행 → 결과 JSON을 `data/runs/<run_id>.json`에 저장. 상태 queued/running/done/error
- 결과 직렬화 계약 (`serialize.run_to_json`): 프론트가 지도·KPI·테이블을 그리는 데 필요한 전부. 엔진 dataclass를 직접 노출하지 않음
- 데이터셋별 `prepare_lmd` 결과를 프로세스 내 캐시 (재실행 시 geocoding·calibration 생략)

## Interface (HTTP)
| Method | Path | 요청 | 응답 |
|--------|------|------|------|
| GET | `/api/health` | | `{status, valhalla: bool, datasets: n}` |
| GET | `/api/datasets` | | `[{id, path, shipments, trucks, extracted_at, has_truth, has_calibration}]` |
| GET | `/api/scenarios/default` | | `LmdScenario` 기본값 JSON |
| POST | `/api/runs` | `{dataset, scenario: {...LmdScenario}, valhalla_url?: str}` | `{run_id, status}` 202 |
| GET | `/api/runs` | | `[{run_id, dataset, scenario_name, status, created_at, kpi_summary?}]` 최신순 |
| GET | `/api/runs/{id}` | | 결과 JSON (아래) 또는 `{status, error}` |
| DELETE | `/api/runs/{id}` | | 204 |
| GET | `/` , `/static/*` | | W02 프론트 (W01에서는 placeholder) |

## 결과 JSON (`run_to_json`)
```json
{"run_id": "...", "dataset": "...", "scenario": {...}, "created_at": "...", "status": "done",
 "gate": {"passed": true, "test_gap_pct": 0.76, "a": 8.62, "b": 1.142},
 "optimize": {"days": 27, "stops": 175, "routed": 175, "loads": 51, "unrouted": []},
 "hub": {"lat":..,"lon":..,"zip":"30260"},
 "kpi": {"baseline": {...RouteKPI}, "scenario": {...}, "delta": {...}, "delta_pct": {...}, "summary": "text"},
 "plans": {"baseline": [Plan], "scenario": [Plan]}}
Plan = {"load_id","day","truck_id","pool","miles","hub_miles","drive_min","service_min","duty_min","over_work","over_duty","late_stops","wait_min",
        "stops":[{"id","ship_to_id","zone","lat","lon","service_min","window","shipments":[...]}],
        "legs":[{"miles","minutes","provider","geometry":[[lat,lon],...]|null}]}
```

## 승인 기준 (테스트, TestClient)
1. `/api/health` 200, `/api/datasets`가 fixture 폴더를 인식
2. `POST /api/runs` 202 → 폴링으로 done → 결과 JSON에 kpi.baseline.loads, plans.scenario[0].legs[0].miles 존재 (합성 소형 데이터셋, Valhalla 없음)
3. 잘못된 dataset → 404, 잘못된 scenario 필드 → 422
4. `GET /api/runs` 최신순, DELETE 후 404
5. 실 데이터셋 있으면 스모크(skip-if-missing)

## 알려진 한계 (ponytail)
- 실행 큐 = ThreadPoolExecutor(1). 동시 실행 1건, 나머지 대기. 팀 규모(≤5명)에 충분
- 인증 없음 (LAN)
