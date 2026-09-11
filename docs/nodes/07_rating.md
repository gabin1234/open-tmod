# Node 07 — Rating

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
Shipment + Route + RateCard → 비용. Baseline(Node 08)과 Re-rating(Node 12)이 같은 함수를 쓴다.

요율 선택 (`select_rate`): 같은 carrier_id의 카드 중 `mode` 정확 일치 > `mode` 없는 카드 > 없음. 동순위 다수면 `source_row` 작은 것.

계산 (`rate_shipment`):
| rate_type | linehaul base |
|-----------|---------------|
| per_mile | rate × miles (Route 필수) |
| per_cwt | rate × (weight_lb / 100). `cwt_round_up=True`면 올림한 cwt 수 |
| flat | rate |

- `min_charge` 있으면 linehaul = max(base, min_charge), `min_applied` 기록
- `fuel_pct`는 백분율 값 (25 → 25%). fuel = linehaul × fuel_pct / 100
- total = linehaul + fuel. 모두 Decimal, 센트 단위 ROUND_HALF_UP

## 비책임
- 요율표 zone/lane 매칭, 할인율, accessorial → 실 rate 데이터 확인 후 contract 2.0
- 합계/비교 → Node 08, 13

## Interface

```python
from tmod.rating import rate_all, rate_shipment, select_rate, RatedCost, RatingReport

@dataclass(frozen=True)
class RatedCost:
    shipment_id: str
    carrier_id: str
    rate_type: str
    miles: float | None
    linehaul: Decimal
    fuel: Decimal
    total: Decimal
    min_applied: bool
    rate_card_row: int

@dataclass(frozen=True)
class RatingReport:
    rated: int
    unrated: tuple[tuple[str, str], ...]   # (shipment_id, "NO_RATE" | "NO_ROUTE")
    total: Decimal                         # rated 합계

def select_rate(cards: Sequence[RateCard], carrier_id: str, mode: str | None) -> RateCard | None
def rate_shipment(s: Shipment, route: Route | None, card: RateCard, cwt_round_up: bool = False) -> RatedCost   # per_mile인데 route None이면 ValueError
def rate_all(ds: Dataset, matrix: RouteMatrix, cwt_round_up: bool = False) -> tuple[tuple[RatedCost, ...], RatingReport]
```

## 승인 기준 (테스트)
1. per_mile: 2.5 × 100mi = 250.00, fuel 20% → 50.00, total 300.00
2. per_cwt: 12.5 × 1,250lb → 156.25; `cwt_round_up` → 13cwt × 12.5 = 162.50
3. flat 300, min_charge 150 → 300, min_applied False; base 80 < min 150 → 150, True
4. 반올림: 1.005 → 1.01 (HALF_UP)
5. select_rate: mode 일치 > mode None > None
6. rate_all: per_mile인데 route 없음 → NO_ROUTE, carrier 카드 없음 → NO_RATE, 나머지 rated + total 합계
7. per_mile + route None → ValueError

## 알려진 한계 (ponytail)
- 3가지 rate_type만. zone matrix, 중량 구간(tiered) 요율은 실 rates CSV 보고 추가.
- miles는 float, 비용은 Decimal. miles → Decimal 변환은 str 경유(부동소수 오차 차단).
