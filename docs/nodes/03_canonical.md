# Node 03 — Canonical Model

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
`RawTable` + `ValidationReport`를 받아 타입이 확정된 도메인 객체(`Dataset`)를 만든다. 이후 모든 Node는 RawTable을 보지 않고 `Dataset`만 본다.

- `report.mapping`으로 컬럼 해소, `report.rejected` 행 제외
- Node 02 파서 재사용 (파싱 규칙 단일화)
- Location 추출 및 중복 제거 (`Location.key` 기준)
- 각 객체에 `source_row` 유지 (provenance)

## 비책임
- 주소 문자열 정규화 → Node 04 (여기서는 strip만)
- 좌표 부여 → Node 05
- 검증 → Node 02. 이 Node는 Node 02가 통과시킨 행이 파싱된다고 가정한다.

## Interface

```python
from tmod.canonical import build, Dataset, Shipment, RateCard, Location

@dataclass(frozen=True)
class Location:
    zip: str | None
    address: str | None
    city: str | None
    state: str | None
    lat: float | None
    lon: float | None
    @property key(self) -> str   # "ll:{lat:.5f},{lon:.5f}" > "zip:{zip}" > "addr:{address.lower()}" 우선순위

@dataclass(frozen=True)
class Shipment:
    id: str
    ship_date: date
    carrier_id: str
    weight_lb: Decimal
    actual_cost: Decimal
    origin: Location
    dest: Location
    mode: str | None
    service_level: str | None
    deliver_date: date | None
    pieces: int | None
    pallets: int | None
    source_row: int

@dataclass(frozen=True)
class RateCard:
    carrier_id: str
    rate_type: str            # per_mile | per_cwt | flat
    rate: Decimal
    min_charge: Decimal | None
    fuel_pct: Decimal | None
    mode: str | None
    source_row: int

@dataclass(frozen=True)
class Dataset:
    shipments: tuple[Shipment, ...]
    rates: tuple[RateCard, ...]
    locations: tuple[Location, ...]          # shipments에서 참조된 고유 Location (key 기준)
    named_locations: dict[str, Location]     # locations 테이블: location_id -> Location
    @property total_actual_cost -> Decimal

def build(tables: dict[str, RawTable], report: ValidationReport) -> Dataset
```

## 오류 처리
| 상황 | 처리 |
|------|------|
| shipments 또는 rates에 MISSING_TABLE / MISSING_COLUMN ERROR | `ValueError` (부분 빌드 불가) |
| 행 단위 ERROR | 해당 행 제외, 나머지로 빌드 |
| 필터 후 shipments 또는 rates 비어 있음 | `ValueError` |
| 통과 행 파싱 실패 | 발생하면 Node 02 버그. 그대로 예외 전파 |

## 승인 기준 (테스트)
1. 정상 입력 → Shipment/RateCard 타입 확정 (Decimal, date, float lat/lon)
2. rejected 행 제외, `source_row` 보존
3. alias 컬럼(`scac`) → `carrier_id` 매핑
4. 같은 zip 두 shipment → `locations`에 1개
5. lat/lon 있으면 key는 `ll:`, 없으면 `zip:`, 둘 다 없으면 `addr:`
6. locations 테이블 → `named_locations`
7. MISSING_COLUMN → ValueError
8. `total_actual_cost` 합계 일치

## 알려진 한계 (ponytail)
- Location key에 주소는 lower+strip만. 정규화된 주소 키는 Node 04가 제공.
- Stop(다중 하차) 없음. 단일 O-D shipment만. 다중 stop은 실 데이터에 나타나면 contract 2.0.
