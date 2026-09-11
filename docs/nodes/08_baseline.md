# Node 08 — Baseline

상태: FROZEN (2026-09-10 승인)
버전: 1.0
게이트: **실 TMS 데이터 미확보. 합성 샘플로 파이프라인 검증만 완료. ±2% 게이트 판정은 실 데이터 투입 시.**

## 책임
Node 01~07을 연결해 실제 이력 shipment를 그대로 rating하고, 모델 비용 합계를 `actual_cost` 합계와 비교한다. gap이 ±2% 이내여야 Node 09 이후 시나리오 수치 논의가 허용된다.

- `prepare(files)`: ingest → validate → build → address → geocode. knob 무관, 1회 실행
- `evaluate(ds, knobs, providers=None)`: route(Haversine(knobs) 또는 주어진 Provider) → rate → gap 계산
- `calibrate(ds, grid)`: knob 후보 중 **carrier별 |model − actual| 합(`carrier_abs_error`)** 최소 선택. 총 gap 최소화는 carrier 간 오차가 상쇄되어 잘못된 knob을 고를 수 있음 (합성 샘플에서 실제 발생: cwt_round_up 오선택)
- gap은 **rated shipment만** 대상. unrated(NO_RATE/NO_ROUTE)는 별도 보고. unrated 비율이 크면 gap 수치 자체가 무의미하므로 `unrated_pct`도 함께 보고
- carrier별 gap 보고 (요율 유형별 오차 분리)
- 확정 knob은 JSON으로 저장/로드. Node 09~13은 같은 knob을 사용해야 함

## Knobs (캘리브레이션 대상)
| knob | 기본 | 의미 |
|------|------|------|
| circuity | 1.2 | 대권거리 → 도로거리 보정 (Haversine Provider일 때만) |
| mph | 50 | 시간 추정 (비용 무관, 서비스 KPI용) |
| cwt_round_up | False | per_cwt 올림 규칙 |

## Interface

```python
from tmod.baseline import prepare, evaluate, calibrate, run_baseline, Knobs, BaselineResult, DEFAULT_GRID, save_knobs, load_knobs

@dataclass(frozen=True)
class Knobs:
    circuity: float = 1.2
    mph: float = 50.0
    cwt_round_up: bool = False

@dataclass(frozen=True)
class BaselineResult:
    knobs: Knobs
    rated: tuple[RatedCost, ...]
    matrix: RouteMatrix
    total_model: Decimal
    total_actual: Decimal            # rated shipment의 actual_cost 합
    gap_pct: float                   # (model - actual) / actual × 100
    by_carrier: dict[str, tuple[Decimal, Decimal, float]]   # carrier -> (model, actual, gap_pct)
    unrated: tuple[tuple[str, str], ...]
    unrated_pct: float               # unrated 건수 / 전체 건수 × 100
    within_tolerance: bool           # |gap_pct| <= tolerance
    carrier_abs_error: Decimal       # property, 캘리브레이션 목적함수

def prepare(files: dict[str, str | Path]) -> tuple[Dataset, dict[str, str]]     # (Dataset, {"validation": summary, "address": ..., "geocode": ...})
def evaluate(ds: Dataset, knobs: Knobs = Knobs(), providers: Sequence[RoutingProvider] | None = None, tolerance: float = 2.0) -> BaselineResult
def calibrate(ds: Dataset, grid: Iterable[Knobs] = DEFAULT_GRID, tolerance: float = 2.0) -> BaselineResult
def run_baseline(files, knobs: Knobs | None = None, tolerance: float = 2.0) -> tuple[BaselineResult, dict[str, str]]   # knobs None이면 calibrate
def save_knobs(path, knobs) -> None
def load_knobs(path) -> Knobs
```

CLI: `uv run python -m tmod.baseline data/sample [--knobs baseline_knobs.json]` — 요약 출력, knobs 파일 없으면 calibrate 후 저장.

DEFAULT_GRID: circuity ∈ {1.10, 1.15, …, 1.40} × cwt_round_up ∈ {False, True}. 14 조합.

## 합성 샘플 (`data/sample/`, `scripts/make_sample.py`)
200건 + 오염 2건. 정답: circuity 1.25, 비용 노이즈 σ=2%. 캘리브레이션이 1.25를 찾고 |gap| < 2%면 파이프라인 정상. **이 결과는 게이트 통과가 아니다.**

## 승인 기준 (테스트)
1. 합성 샘플 `prepare`: 오염 2건 rejected, 200건 빌드, ungeocoded 0
2. `calibrate` → circuity 1.25, cwt_round_up False 선택 (정답 일치), `within_tolerance` True
3. circuity 1.10 강제 시 gap 음수(과소), 1.40 시 양수(과대)
4. by_carrier 3개, 각 gap 유한
5. knobs save/load 왕복
6. 단위: evaluate gap 계산 — 알려진 2건으로 정확 값 검증

## 알려진 한계 (ponytail)
- 그리드 탐색. knob 3개, 14조합이라 충분. knob이 늘면 scipy 없이 coordinate descent로 확장.
- 캐시 없음. Haversine은 즉시 계산이고 zip 테이블은 로컬. Valhalla/PC Miler 붙일 때 Node 05/06의 load/save_cache 연결.
