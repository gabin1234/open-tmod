# Node 12 — Re-rating

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
시나리오 Dataset(Node 09 → 10 → 11 결과)을 **Baseline과 동일한 knobs, 동일한 Node 06/07 함수**로 재요율한다. Baseline과 다른 요율 로직이 끼어들 수 없도록 `knobs`는 필수 인자.

- route_matrix(Haversine(knobs) 또는 주어진 Provider) → rate_all(knobs.cwt_round_up)
- 시나리오 shipment → Baseline shipment 대응표 유지. 통합 shipment(`CONS-*`)는 Node 10 `bins`로 멤버 목록 복원, 나머지는 자기 자신
- 모든 Baseline shipment id가 대응표에 정확히 1회 나타나는지 검증 (누락/중복 시 ValueError)

## 비책임
- KPI 계산, 절감 수치 → Node 13
- knob 결정 → Node 08

## Interface

```python
from tmod.rerating import rerate, RerateResult

@dataclass(frozen=True)
class RerateResult:
    knobs: Knobs
    rated: tuple[RatedCost, ...]
    matrix: RouteMatrix
    total: Decimal
    unrated: tuple[tuple[str, str], ...]
    members: dict[str, tuple[str, ...]]     # scenario shipment id -> baseline shipment ids

def rerate(ds: Dataset, knobs: Knobs, bins: Sequence[tuple[str, tuple[str, ...]]] = (),
           baseline_ids: Collection[str] | None = None, providers: Sequence[RoutingProvider] | None = None) -> RerateResult
```

`baseline_ids`가 주어지면 대응표 커버리지 검증. None이면 생략.

## 승인 기준 (테스트)
1. 시나리오 = Baseline 그대로면 `rerate(...).total == evaluate(...).total_model`
2. CarrierSwitch 적용 후 rerate → 해당 shipment의 carrier_id 요율로 계산
3. 통합 shipment members 복원, 나머지 self-map, 커버리지 검증 통과
4. baseline_ids 누락/중복 → ValueError
5. cwt_round_up knob 반영

## 알려진 한계 (ponytail)
- 없음. 얇은 조합 Node.
