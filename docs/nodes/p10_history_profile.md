# P10 — Historical Travel Time → traffic_profile

상태: FROZEN (2026-09-12 승인)
버전: 1.0 (P09 traffic_profile 적재 파이프라인)

## 데이터
Atlanta 1Y xlsx(raw): 16,281 shipment, `ROUTE_ID`(일별 트럭 경로), `END_DELIVERED`(배송 완료 시각, 로컬), `END_ZIP`. 같은 route-day 안에서 END_DELIVERED 순으로 연속 stop 쌍 5,563개.
`gap = t(k+1) − t(k) = travel(k→k+1) + service(k+1)`

## 추정 방법 (`scripts/traffic_profile_from_history.py`)
1. 연속 stop 쌍의 zip centroid 간 free-flow 시간 `f` = OSRM `/table`(car) — zip 쌍 캐시 `zip_freeflow_osrm.csv`
2. 서비스 시간 추정 `a` = 같은 zip(=travel≈0) 연속 쌍 gap의 중앙값
3. `f ≥ 5분`인 쌍에 대해 `factor_i = (gap_i − a) / f_i`, 출발 시각(t(k)) 시간대(hour)·평일/주말별 **중앙값**(이상치 강건), n ≥ 30 인 시간대만, **[1.0, 3.0] 클램프** (free-flow가 하한: 저녁 시간대 0.5~0.8은 서비스 시간 잡음이라 1.0으로 바닥)
4. 인접 시간대 factor 차이 < 0.05면 하나의 구간으로 병합 → `traffic_profile` 행 (`source='HISTORICAL'`, day_of_week = 평일 5행 복제 / 주말 2행)
5. `--apply`: SAMPLE 비활성화 후 HISTORICAL 삽입 (재실행 시 기존 HISTORICAL 교체)

## 한계 (정직하게)
- gap에 서비스 시간이 섞여 있고 서비스는 건마다 20~180분 편차 → 시간대 factor는 추세 수준. 이력 표본 없는 시간대(07시 이전·20시 이후 일부)는 행 없음 → factor 1.0
- zip centroid 간 거리라 실제 주소 간 거리와 다름(짧은 구간일수록 오차 큼 → `f ≥ 5분` 필터)
- 실제 텔레매틱스(출발/도착 이벤트) 확보 시 같은 스크립트에 컬럼만 바꿔 재적재

## Interface
```
uv run --with openpyxl python scripts/traffic_profile_from_history.py "<xlsx>" [--osrm http://localhost:5001] [--apply] [--out data/private/.../traffic_profile_history.csv]
tmod.product.history.estimate_factors(pairs: list[(depart_dt, gap_min, freeflow_min)]) -> dict[(daytype, hour) -> (factor, n)]
tmod.product.history.merge_hours(...) -> list[(daytype, from_h, to_h, factor, n)]
```

## 승인 기준 (테스트)
1. 합성 쌍(알려진 factor 1.4@08h, 1.0@11h, 서비스 30분, 노이즈) → estimate_factors가 ±0.1 내 복원, n<30 시간대 제외
2. merge_hours: 인접 동일 factor 병합
3. 실 xlsx 실행 → CSV + DB 적재, 시간대별 n·factor 보고 (skip-if-missing)

## 실행 결과 (2026-09-12, Atlanta 1Y, OSRM car 기준)
연속 쌍 3,676 (같은 zip 1,232 → 서비스 추정 41분), 사용 3,670. 평일: 09시 ×1.39 · 10시 ×1.23 · 11–13시 ×1.43 · 13시 ×1.66 · 14시 ×1.46 · 15시 ×1.21 · 16시 ×1.47 · 17시 ×1.08 · 18시 이후 1.0(바닥). 주말 14–16시 1.0. 07–09시·20시 이후는 표본 부족(n<30) → 행 없음.
