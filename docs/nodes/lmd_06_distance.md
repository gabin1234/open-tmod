# LMD Node 06 — Distance Calibration + Gate (`tmod/lmd_routing.py`)

상태: FROZEN (2026-09-11 승인, 게이트 PASS test gap +0.76%)
버전: 1.0
Node 06 Routing(FROZEN)의 Provider 프로토콜 위에 LMD용 Provider 2종과 캘리브레이션을 추가한다. **LMD 트랙의 ±2% 게이트가 여기서 판정된다.**

## 실측 근거 (Atlanta 1Y, 7,971 LM loads, 331 zip)
- `LM_MILE_DISTANCE`는 hub→zip **zip-to-zip 상수** (같은 zip 내 편차 0) → 결정적 마일리지 테이블. `distance_truth.csv`(집계, PII 없음)로 추출
- 대권거리 대비 circuity가 거리에 반비례: <10mi 1.77, 10–25 1.62, 25–50 1.39, 50–100 1.28, 100+ 1.20. 상수 circuity는 held-out 총거리 gap −2.65% (게이트 실패)
- **affine 모델 miles = a + b·gc** 채택: held-out 총거리 gap +0.76%, MAPE 10.1%. 0–10mi 밴드는 +27% 과대 (zip 8개, 물량 비중 작음) — Baseline hub↔stop 구간은 truth 테이블을 직접 쓰므로 실제 영향은 stop↔stop 구간에 한정

## Interface
```python
from tmod.lmd_routing import AffineHaversineProvider, TruthProvider, load_truth, calibrate, Calibration, save_calibration, load_calibration

class AffineHaversineProvider:            # name "affine_haversine"
    def __init__(self, a: float, b: float, mph: float = 30.0)   # miles = max(a + b*gc, 0.5), minutes = miles/mph*60

class TruthProvider:                      # name "truth"
    def __init__(self, truth: dict[tuple[str, str], float], mph: float = 30.0)   # key (hub_zip, zip), 양방향 매칭. 없으면 None → 다음 Provider

def load_truth(path) -> dict[tuple[str, str], float]      # distance_truth.csv → {(hub_zip, zip): median_miles}

@dataclass(frozen=True)
class Calibration:
    a: float; b: float; mph: float
    n_zips: int
    train_gap_pct: float; test_gap_pct: float          # held-out = 정렬된 zip의 홀수 인덱스
    test_mape_pct: float
    band_gap_pct: dict[str, float]                     # "0-10","10-25","25-50","50-100","100+"
    within_tolerance: bool                             # |test_gap_pct| <= tolerance

def calibrate(hub: Location, truth: dict, geocoder=None, tolerance: float = 2.0, mph: float = 30.0) -> Calibration
def save_calibration(path, cal) / load_calibration(path) -> Calibration
```

Provider 체인 권장: `[TruthProvider(truth), AffineHaversineProvider(cal.a, cal.b)]` — hub↔stop은 실측, stop↔stop은 보정 모델.

## 게이트
`Calibration.within_tolerance` (held-out 총거리 gap ±2%) = LMD 트랙 Baseline 게이트. 실 결과는 승인 요청에 기록. mph(주행속도)는 실적 없음 → 30mph 가정, Node 08에서 duty 분 비교 시 재검토.

## 승인 기준 (테스트)
1. 합성 truth(a=5, b=1.3, 노이즈 3%) → calibrate가 a,b를 ±10% 내 복원, within_tolerance True
2. TruthProvider: (hub,zip) 양방향 매칭, 미등록 쌍 None
3. AffineHaversineProvider: 거리·시간 공식, 최소 0.5mi
4. save/load 왕복
5. 실 truth 파일 있으면 calibrate 실행 → `within_tolerance` True, 결과 출력 (skip-if-missing)

## 알려진 한계 (ponytail)
- 시간(minutes)은 mph 상수. 실적 주행시간 없음
- affine은 hub 기준 fit. stop↔stop 짧은 구간(<10mi)은 과대 가능 → Node 08 KPI에서 stop↔stop 비중 보고
