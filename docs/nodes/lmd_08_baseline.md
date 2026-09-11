# LMD Node 08 — Baseline Routes (`tmod/lmd_baseline.py`)

상태: FROZEN (2026-09-11 승인)
버전: 1.1 (keep_order 추가, 2026-09-11)

## 책임
LMD_SHIPMENT의 확정 load(`LOAD_ID`) 구성을 **그대로** 받아 Provider 거리·시간으로 평가한다. load 구성은 바꾸지 않는다. 시나리오(Node 09/10)도 같은 `evaluate_loads`로 평가해 비교 규칙을 통일한다.

- `prepare_lmd(folder)`: ingest → validate(LMD_SCHEMAS) → build_lmd → Node 04/05 (to_dataset/apply_geocoded) → Provider 체인 [TruthProvider, AffineHaversine(calibration.json)]. calibration.json 없으면 `calibrate` 실행 후 저장
- stop 방문 순서: STOP_SEQ 없음 → **최근접 이웃**(hub 출발, 미방문 중 가장 가까운 stop, 마지막 hub 복귀). Baseline·Scenario 동일 규칙
- 좌표 없는 stop은 제외하고 `skipped`에 기록
- 트럭 마스터 외 truck_id(pool `'1'`) → `pool=True`, 용량은 params TRUCK_WORK_MIN/TRUCK_DUTY_MIN 적용

## Interface
```python
from tmod.lmd_baseline import prepare_lmd, evaluate_loads, baseline, RoutePlan, RouteKPI, BaselineRoutes

@dataclass(frozen=True)
class RoutePlan:
    load_id: str
    day: date | None
    truck_id: str | None
    pool: bool
    stops: tuple[Stop, ...]          # 방문 순서
    legs: tuple[Route, ...]          # hub→s1 … sn→hub, len = n+1
    miles: float
    hub_miles: float                 # 첫·마지막 leg 합
    drive_min: float
    service_min: int                 # Σ stop.service_min
    duty_min: float                  # drive + service
    over_work: bool                  # service_min > work_min
    over_duty: bool                  # duty_min > duty_min 한도

@dataclass(frozen=True)
class RouteKPI:
    loads: int; stops: int; shipments: int
    miles: float; hub_miles: float; inter_stop_miles: float
    drive_min: float; service_min: int; duty_min: float
    over_work: int; over_duty: int; pool_loads: int
    avg_stops_per_load: float; avg_duty_min: float
    days: int; max_trucks_per_day: int
    by_provider_miles: dict[str, float]      # "truth" vs "affine_haversine" 비중
    def summary(self) -> str

@dataclass(frozen=True)
class BaselineRoutes:
    plans: tuple[RoutePlan, ...]
    kpi: RouteKPI
    skipped: tuple[tuple[str, str], ...]     # (stop id, reason)

def prepare_lmd(folder) -> tuple[LmdDataset, list[RoutingProvider], Calibration]
def evaluate_loads(lmd, loads: dict[str, Sequence[Stop]], providers, truck_of: dict[str, Truck] | None = None, keep_order: bool = False) -> BaselineRoutes
# keep_order=True: 주어진 순서 그대로 (Node 10 최적화 결과). False: 최근접 (Baseline, STOP_SEQ 없음)  — v1.1
def baseline(lmd, providers) -> BaselineRoutes            # loads = lmd.baseline_loads()
```
CLI: `uv run python -m tmod.lmd_baseline data/private/lmd_lphb30260_demo` → KPI summary + 일별 트럭 수.

## 승인 기준 (테스트)
1. 합성 lmd(hub + stop 3개, 고정 거리 Provider): 최근접 순서 정확, legs n+1, miles/duty 합 정확, over_work/over_duty 판정
2. 좌표 없는 stop → skipped, 나머지 정상
3. pool 트럭 → pool=True, params 한도 적용
4. 실 데이터(skip-if-missing): load 68, KPI 출력, hub_miles ≤ miles, by_provider에 truth 포함

## 알려진 한계 (ponytail)
- 최근접 순서는 실제 기사 순서와 다를 수 있음. 실 STOP_SEQ 들어오면 `sequence` 함수 교체 지점 하나
- 시간창(08–12 등) 미반영. 모두 동일 window라 POC 영향 없음
