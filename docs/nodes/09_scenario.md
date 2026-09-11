# Node 09 — Scenario

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
Baseline `Dataset` 위에 변경 규칙을 적용해 새 `Dataset`을 만든다. 순수 함수, 원본 불변. 즉시 적용 가능한 규칙은 여기서 적용하고, 최적화가 필요한 규칙은 파라미터만 검증해 Node 10으로 넘긴다.

POC 규칙:
| 규칙 | 적용 위치 | 의미 |
|------|-----------|------|
| `CarrierSwitch(from_carrier, to_carrier, to_mode=None, lanes=None)` | Node 09 | from_carrier shipment를 to_carrier로 교체. `to_mode` 있으면 mode도 교체 (요율 선택에 필요). `lanes`는 (origin_zip, dest_zip) 집합, None이면 전체 |
| `ConsolidationWindow(days, max_weight_lb)` | Node 10 | 같은 lane, `days` 이내 shipment를 `max_weight_lb` 한도로 통합. Node 09는 검증 후 `pending`으로 전달 |

## 비책임
- 통합/적재/배정 최적화 실행 → Node 10
- 재요율, 비교 → Node 12, 13
- 시나리오 절감 수치 보고 → Node 08 게이트 통과 전 금지

## Interface

```python
from tmod.scenario import Scenario, CarrierSwitch, ConsolidationWindow, apply, load_scenario, ApplyReport

@dataclass(frozen=True)
class CarrierSwitch:
    from_carrier: str
    to_carrier: str
    to_mode: str | None = None
    lanes: frozenset[tuple[str, str]] | None = None     # (origin.zip, dest.zip)

@dataclass(frozen=True)
class ConsolidationWindow:
    days: int
    max_weight_lb: Decimal

Rule = CarrierSwitch | ConsolidationWindow

@dataclass(frozen=True)
class Scenario:
    name: str
    rules: tuple[Rule, ...]

@dataclass(frozen=True)
class ApplyReport:
    changed: tuple[tuple[str, str], ...]     # (shipment_id, "C1->C2")
    pending: tuple[Rule, ...]                # Node 10으로 넘기는 규칙

def apply(ds: Dataset, scenario: Scenario) -> tuple[Dataset, ApplyReport]
def load_scenario(path) -> Scenario     # JSON
```

JSON 형식:
```json
{"name": "switch-C1-to-C2",
 "rules": [
   {"type": "carrier_switch", "from_carrier": "C1", "to_carrier": "C2", "to_mode": "LTL", "lanes": [["60601", "10001"]]},
   {"type": "consolidation_window", "days": 3, "max_weight_lb": 44000}
 ]}
```

## 오류 처리
- `to_carrier`가 `ds.rates`에 없음 → `ValueError`
- `days < 1` 또는 `max_weight_lb <= 0` → `ValueError`
- 알 수 없는 rule type (JSON) → `ValueError`

## 승인 기준 (테스트)
1. 전체 lane CarrierSwitch: from_carrier shipment 전부 교체, 나머지 불변, `changed` 목록 일치
2. lanes 제한: 해당 lane만 교체
3. `to_mode` 지정 시 mode 교체, 미지정 시 유지
4. 원본 Dataset 불변 (rates, locations 동일 객체)
5. ConsolidationWindow → `pending`, shipments 불변
6. 없는 to_carrier → ValueError
7. `load_scenario` JSON 왕복

## 알려진 한계 (ponytail)
- 규칙 2종. 거점 변경(origin 교체), 요율 변경은 실 시나리오 요구 나오면 추가. 각 규칙은 dataclass 하나 + apply 분기 하나.
