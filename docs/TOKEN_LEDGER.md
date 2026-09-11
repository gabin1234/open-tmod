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
