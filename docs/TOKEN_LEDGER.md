# Token Ledger

세션 총 상한 5-10M. Node별 추정치 기록. 수치는 세션 컨텍스트 기준 추정이며 정확한 청구 토큰이 아니다.

| NN | Node | 입력(추정) | 출력(추정) | 누적 | 비고 |
|----|------|-----------|-----------|------|------|
| 00 | Master Graph + 규칙 셋업 | ~60k | ~6k | ~66k | CLAUDE.md, MASTER_GRAPH.md |
| 01 | Ingestion | ~20k | ~8k | ~94k | contract + impl + test |
| 02 | Validation | ~25k | ~12k | ~131k | contract + impl + test (22 tests total) |
| 03 | Canonical Model | ~15k | ~9k | ~155k | contract + impl + test |
| 04 | Address | ~10k | ~7k | ~172k | zip-centric normalize |
| 05 | Geocoding | ~14k | ~9k | ~195k | ZCTA centroid provider + cache; data/zip_centroids.csv 945KB |
| 06 | Road Routing | ~12k | ~8k | ~215k | Provider protocol: Haversine(knobs), Valhalla(HTTP), matrix cache |
| 07 | Rating | ~10k | ~7k | ~232k | per_mile/per_cwt/flat, min_charge, fuel_pct |
| 08 | Baseline | ~22k | ~14k | ~268k | pipeline 01-07, gap, calibrate; scripts/make_sample.py, data/sample/ |
| 09 | Scenario | ~9k | ~6k | ~283k | CarrierSwitch 적용, ConsolidationWindow pending, JSON 로드 |
| 10 | Optimization | ~14k | ~9k | ~306k | CP-SAT bin packing consolidation; +ortools |
| 11 | Simulation (stub) | ~5k | ~3k | ~314k | deterministic transit days; SimPy 미도입 |
| 12 | Re-rating | ~6k | ~4k | ~324k | rate_all 재사용 + knobs 강제 + member map |
| 13 | Comparison | ~9k | ~6k | ~339k | KPI 7종, per-shipment delta, gate 마스킹 |
| 14 | Map + POC CLI | ~14k | ~9k | ~362k | Leaflet single HTML, tmod/poc.py end-to-end |
| 00 | BY TMS 탐색 + 추출 어댑터 | ~90k | ~25k | ~477k | scripts/ora.py, scripts/extract_bytms.py, 2022-03 TL 추출, 오프라인 feasibility |
| 00-LMD | LMD 탐색 + 어댑터 + 트랙 문서 | ~40k | ~14k | ~531k | scripts/extract_lmd.py, docs/LMD_TRACK.md |
| LMD-02/03 | schema + canonical | ~12k | ~9k | ~552k | tmod/lmd.py |
| LMD-06 | distance calibration + gate | ~14k | ~9k | ~575k | tmod/lmd_routing.py, scripts/extract_lmd_truth.py, held-out gap +0.76% |
| LMD-08 | baseline routes | ~12k | ~9k | ~596k | tmod/lmd_baseline.py; 68 loads 5,736 mi |
| LMD-09/10 | scenario + VRP | ~18k | ~11k | ~625k | tmod/lmd_optimize.py; real 68→55 loads |
| LMD-13/14 | compare + map + CLI | ~12k | ~9k | ~646k | tmod/lmd_compare.py, lmd_map.py, lmd_poc.py |
| LMD-road | Valhalla 실도로 + 시간창 | ~45k | ~20k | ~745k | Georgia OSM, Route.geometry, use_windows |
| W01 | Backend API | ~16k | ~12k | ~773k | tmod/web/{app,runs,serialize}.py, +fastapi/uvicorn |
| W02-04 | frontend, refresh/health, ops+tunnel+token | ~40k | ~22k | ~835k | web/, tmod/web/refresh.py, ops/ |
| W05 | xlsx upload | ~14k | ~10k | ~880k | tmod/web/upload.py |
| P01 | PostgreSQL schema | ~22k | ~16k | ~950k | db/ddl 27 tables, seed, ERD, docker-backed test |
| P02 | mapping + ETL | ~14k | ~11k | ~975k | tmod/product/etl.py, rule registry, xlsx mapping seed |
| P03 | routing data (OSRM/Valhalla, cache, segments, adjustments) | ~20k | ~14k | ~1.01M | tmod/product/routing.py; OSRM Georgia on :5001 (5000 = macOS AirPlay) |
| P04 | OR-Tools model builder + solve | ~30k | ~20k | ~1.06M | tmod/product/{model,solve}.py; real 65-shipment run OPTIMAL 20s |
| P05 | product API /api/v2 | ~24k | ~16k | ~1.10M | tmod/product/api.py mounted in web app |
| P06 | product frontend /product | ~26k | ~18k | ~1.15M | web/product/{index.html,app.js}; runs?detail=1 lazy geometry |
| P07 | Phase 2 pickup & delivery | ~16k | ~11k | ~1.19M | model/solve pairs, ETL pickup_location, stop_kind |
| P08 | Phase 2 multiple depot | ~10k | ~8k | ~1.21M | per-vehicle depots via RoutingIndexManager starts/ends |
| P09 | Phase 3 dynamic traffic + profile + priority | ~22k | ~14k | ~1.26M | traffic_profile, iterative re-timing, priority penalty; test hang fix (idle-in-transaction) |
| P10 | historical traffic_profile from Atlanta 1Y | ~14k | ~9k | ~1.28M | scripts/traffic_profile_from_history.py, tmod/product/history.py |
| P11 | ops: compose, Dockerfile, basic auth, backup, health | ~24k | ~16k | ~1.32M | docker-compose.yml, ops/backup.sh+plist, auth v1.1 |
