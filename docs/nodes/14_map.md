# Node 14 — Map

상태: FROZEN (2026-09-11 승인)
버전: 1.0

## 책임
Comparison 결과를 단일 HTML로 출력한다. 의존성 없음 (문자열 템플릿 + Leaflet CDN + OSM 타일).

- Lane 지도: Baseline O-D lane 회색, Scenario lane 파란색. 선 굵기 = shipment 건수. hover에 건수·중량 (비용은 게이트 통과 시만)
- Location 마커: origin/dest
- KPI 패널: `Comparison.summary()` 그대로 (GATED 마스킹 유지)
- Shipment 테이블: 시나리오 shipment별 members 수, carrier, miles. `gate_passed`일 때만 baseline/scenario/delta 비용 컬럼

## POC 통합 CLI (`tmod/poc.py`)
`uv run python -m tmod.poc <folder> <scenario.json> <out.html> [--real-data]`

순서 = Master Graph: prepare(01~05) → knobs(load 또는 calibrate) → Baseline evaluate(06~08) → apply(09) → optimize(10) → route + simulate(11) → rerate(12) → compare(13) → HTML(14).
`gate_passed = baseline.within_tolerance and --real-data`. 합성 샘플은 플래그 없이 실행 → GATED.

## Interface

```python
from tmod.map import render_html, write_html
from tmod.poc import run

def render_html(cmp: Comparison, ds_base: Dataset, ds_scen: Dataset, base_matrix: RouteMatrix, scen_matrix: RouteMatrix, scen: RerateResult, title: str = "Open T-Modeler POC") -> str
def write_html(path, *args, **kwargs) -> Path

def run(folder: str | Path, scenario_path: str | Path, out_html: str | Path, real_data: bool = False, capacity_lb: Decimal | None = None) -> tuple[Comparison, Path]
```

## 승인 기준 (테스트)
1. `render_html` 출력에 Leaflet script, KPI summary 텍스트, lane GeoJSON 좌표 포함
2. gate_passed False → HTML에 "GATED" 있고 비용 컬럼 없음. True → 비용 컬럼 있음
3. `run(data/sample, scenario_consolidation.json)` 끝까지 실행, HTML 파일 생성, Comparison.gate_passed False, scenario shipments < baseline shipments
4. 좌표 없는 Location은 lane에서 제외 (오류 없음)

## 알려진 한계 (ponytail)
- 경로는 직선(O-D). Valhalla Provider 사용 시 polyline 추가는 Route에 geometry 필드 확장 필요 (Node 06 contract 2.0).
- 인터랙션 최소. 필터/토글은 POC 피드백 후.
