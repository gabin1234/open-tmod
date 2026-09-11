# Node 13 — Comparison

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
Baseline(Node 08)과 Scenario(Node 12) 결과를 같은 KPI 정의로 계산하고 차이를 낸다. **게이트 플래그를 받아, 미통과 시 비용 절감 수치를 요약 출력에서 가린다.**

KPI (`kpi`):
| 항목 | 정의 |
|------|------|
| shipments | rated shipment 수 |
| total_cost | rated total 합 (모델 비용) |
| total_miles | rated shipment의 route miles 합 |
| avg_weight_lb | 평균 중량 |
| avg_utilization_pct | `capacity_lb` 주어지면 평균(weight/capacity), 아니면 None |
| avg_transit_days | deliver_date − ship_date 평균 (deliver_date 있는 shipment만), 없으면 None |
| by_carrier | carrier → 비용 합 |

Comparison:
- delta_cost = scenario.total_cost − baseline.total_cost, delta_pct 기준은 baseline
- per_shipment: 시나리오 shipment별 (id, members, baseline_cost = 멤버 Baseline 모델 비용 합, scenario_cost, delta). Baseline unrated 멤버 포함 시 baseline_cost None
- `gate_passed`: 호출자가 `baseline.within_tolerance and real_data`로 결정해 전달. Node 08 합성 샘플은 False

## 비책임
- 시각화 → Node 14
- 게이트 판정 자체 → Node 08 + 사용자

## Interface

```python
from tmod.comparison import kpi, compare, KPI, Comparison, ShipmentDelta

@dataclass(frozen=True)
class KPI:
    shipments: int
    total_cost: Decimal
    total_miles: float
    avg_weight_lb: Decimal
    avg_utilization_pct: float | None
    avg_transit_days: float | None
    by_carrier: dict[str, Decimal]

@dataclass(frozen=True)
class ShipmentDelta:
    scenario_id: str
    members: tuple[str, ...]
    baseline_cost: Decimal | None
    scenario_cost: Decimal
    delta: Decimal | None

@dataclass(frozen=True)
class Comparison:
    scenario_name: str
    baseline: KPI
    scenario: KPI
    delta_cost: Decimal
    delta_pct: float
    per_shipment: tuple[ShipmentDelta, ...]
    gate_passed: bool
    def summary(self) -> str    # gate_passed False면 비용/절감 수치를 "GATED" 로 표기, 건수·miles·transit은 표시

def kpi(ds: Dataset, rated: Sequence[RatedCost], matrix: RouteMatrix, capacity_lb: Decimal | None = None) -> KPI
def compare(name: str, ds_base: Dataset, base: BaselineResult, ds_scen: Dataset, scen: RerateResult,
            gate_passed: bool, capacity_lb: Decimal | None = None) -> Comparison
```

## 승인 기준 (테스트)
1. kpi: 건수, 비용 합, miles 합, 평균 중량, utilization(capacity 44000), transit days 정확
2. compare 동일 Dataset → delta 0, per_shipment 모두 delta 0
3. 통합 시나리오: CONS shipment의 baseline_cost = 멤버 합, delta 부호 정확
4. Baseline unrated 멤버 → baseline_cost None, delta None
5. `summary(gate_passed=False)` 에 "GATED" 포함되고 비용 숫자 미포함; True면 숫자 포함

## 알려진 한계 (ponytail)
- KPI 7종 고정. 서비스 KPI(정시율)는 Node 11 실 구현 후.
