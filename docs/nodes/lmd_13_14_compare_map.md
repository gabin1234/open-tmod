# LMD Node 13/14 — Route Comparison + Map (`tmod/lmd_compare.py`, `tmod/lmd_map.py`, `tmod/lmd_poc.py`)

상태: FROZEN (2026-09-11 사전 승인)
버전: 1.0

## Node 13 — 비교
Baseline(Node 08)과 Scenario(Node 10 → `evaluate_loads(keep_order=True)`)의 `RouteKPI`를 같은 항목으로 나란히 놓고 delta를 낸다. 게이트는 Node 06 `Calibration.within_tolerance`; 미통과면 delta를 GATED로 가린다.

```python
@dataclass(frozen=True)
class RouteComparison:
    scenario_name: str
    baseline: RouteKPI; scenario: RouteKPI
    delta: dict[str, float]          # loads, stops, miles, hub_miles, inter_stop_miles, drive_min, service_min, duty_min, over_work, over_duty, max_trucks_per_day
    delta_pct: dict[str, float]      # baseline 기준 %
    unrouted: tuple[str, ...]        # Scenario에서 drop된 stop
    gate_passed: bool
    def summary(self) -> str

def compare_routes(name, base: BaselineRoutes, scen: BaselineRoutes, unrouted, gate_passed) -> RouteComparison
```

## Node 14 — 지도
단일 HTML (Leaflet CDN). hub 마커, stop 마커, load별 polyline (baseline 회색 halo, scenario 색상), 일자 선택 드롭다운, KPI 패널(`summary()`), load 테이블. Node 14(FROZEN) 스타일 재사용.

```python
def render_lmd_html(cmp: RouteComparison, base: BaselineRoutes, scen: BaselineRoutes, hub: Location, title="Open T-Modeler LMD") -> str
def write_lmd_html(path, ...) -> Path
```

## POC CLI (`tmod/lmd_poc.py`)
`uv run python -m tmod.lmd_poc <folder> [scenario.json] [out.html]` — prepare_lmd → baseline → optimize → evaluate(keep_order) → compare → HTML. 순서 = Master Graph.

## 승인 기준 (테스트)
1. compare_routes: delta·delta_pct 계산, gate False면 summary에 GATED, True면 숫자
2. render_lmd_html: leaflet, hub 좌표, 일자 옵션, GATED 토글
3. 실 데이터 end-to-end (skip-if-missing): HTML 생성, scenario loads < baseline loads
