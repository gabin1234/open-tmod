# Node 04 — Address

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
`Dataset`의 모든 `Location`을 정규화해 새 `Dataset`을 만든다. zip 위주 데이터 가정.

- **zip**: 공백/구두점 제거. 미국 3-4자리 숫자는 앞에 0 채움 (Excel 선행 0 손실 복구). ZIP+4(`60601-1234`, `606011234`)는 5자리로 절단. 캐나다 형식(`K1A 0B1`)은 대문자 무공백 `K1A0B1`으로 유지하고 WARN. 그 외는 원문 유지 + INVALID_ZIP
- **state**: 대문자 2자리. 주 전체 이름은 약어로 변환. 인식 불가면 원문 유지 + UNKNOWN_STATE
- **city**: strip, 공백 축약, Title Case
- **address**: 대문자, 구두점 제거, 공백 축약, USPS 표준 접미사 약어 (STREET→ST, AVENUE→AVE, ROAD→RD, BOULEVARD→BLVD, DRIVE→DR, LANE→LN, COURT→CT, PLACE→PL, HIGHWAY→HWY, PARKWAY→PKWY, SUITE→STE, NORTH/SOUTH/EAST/WEST→N/S/E/W)
- lat/lon은 그대로 통과
- 정규화 후 `Location.key`가 바뀌므로 `Dataset.locations` 재중복제거

## 비책임
- 좌표 부여 → Node 05
- 주소 파싱(번지/도로명 분리), 국가 판별 → POC 외

## Interface

```python
from tmod.address import normalize, normalize_zip, normalize_state, normalize_address, AddressReport

def normalize_zip(s: str | None) -> tuple[str | None, str | None]     # (정규화 zip, issue code | None)
def normalize_state(s: str | None) -> tuple[str | None, str | None]
def normalize_address(s: str | None) -> str | None
def normalize_city(s: str | None) -> str | None
def normalize_location(loc: Location) -> tuple[Location, tuple[str, ...]]

@dataclass(frozen=True)
class AddressIssue:
    shipment_id: str
    side: str            # "origin" | "dest" | location_id (named_locations)
    code: str            # INVALID_ZIP | NON_US_ZIP | UNKNOWN_STATE
    value: str

@dataclass(frozen=True)
class AddressReport:
    issues: tuple[AddressIssue, ...]
    locations_before: int
    locations_after: int

def normalize(ds: Dataset) -> tuple[Dataset, AddressReport]
```

## 승인 기준 (테스트)
1. `"2101"` → `"02101"`, `"60601-1234"` → `"60601"`, `"606011234"` → `"60601"`, `" 60601 "` → `"60601"`
2. `"k1a 0b1"` → `"K1A0B1"` + NON_US_ZIP
3. `"ABCDE"` → 원문 유지 + INVALID_ZIP
4. `"illinois"` → `"IL"`, `" il "` → `"IL"`, `"Ontario"` → 원문 + UNKNOWN_STATE
5. `"123 Main Street, Suite 4"` → `"123 MAIN ST STE 4"`
6. `"  new   york "` → `"New York"`
7. `normalize(ds)`: `"60601"`과 `"60601-1234"` origin이 같은 Location key로 합쳐져 `locations_after < locations_before`
8. Shipment 다른 필드 불변, issues에 shipment_id/side 기록
9. lat/lon 통과

## 알려진 한계 (ponytail)
- 미국 기준. 캐나다는 형식만 보존. 다국가 지원은 country 필드가 Canonical contract 2.0에 추가될 때.
- 접미사 약어 14종만. 전체 USPS 표준은 필요 시 확장.
