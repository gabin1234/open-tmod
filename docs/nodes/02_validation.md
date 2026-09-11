# Node 02 — Validation

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
Node 01의 `RawTable`들을 스키마에 대해 검사하고 `ValidationReport`를 만든다. 데이터를 변환하거나 버리지 않는다. 어떤 행이 거절(ERROR)되었는지만 알려주고, 실제 필터링/변환은 Node 03이 한다.

- 테이블 존재, 필수 컬럼 존재 (alias 허용)
- 셀 단위: 필수값, 타입 파싱 가능성, 범위, enum
- 행 단위: 위치 정보 any_of (zip 또는 address 또는 lat+lon)
- 테이블 단위: unique key, foreign key (shipments.carrier_id ∈ rates.carrier_id)
- Node 01 Issue를 WARN으로 승격 전달
- 스키마에 없는 컬럼은 WARN (헤더 매핑 실수 조기 발견)

## 비책임
- 값 변환 및 도메인 객체 생성 → Node 03. 단, 파서 함수(`parse_date`, `parse_decimal`, `parse_int`)는 이 모듈이 소유하고 Node 03이 재사용한다 (파싱 규칙 단일화).
- 주소 정규화, 지오코딩 → Node 04, 05

## POC 표준 스키마 (실 TMS 샘플 확보 시 alias만 추가)

**shipments** (필수 테이블)
| 컬럼 | 타입 | 필수 | 비고 |
|------|------|------|------|
| shipment_id | str | O | unique |
| ship_date | date | O | ISO, MM/DD/YYYY, YYYYMMDD 허용 |
| carrier_id | str | O | FK → rates.carrier_id |
| weight_lb | decimal ≥0 | O | |
| actual_cost | decimal ≥0 | O | Baseline ±2% 기준값 |
| origin_zip / origin_address / origin_lat+origin_lon | | any_of | 하나 이상 |
| dest_zip / dest_address / dest_lat+dest_lon | | any_of | 하나 이상 |
| mode, service_level, pieces(int≥0), pallets(int≥0), deliver_date(date), origin_city/state, dest_city/state | | 선택 | |

**rates** (필수 테이블)
| 컬럼 | 타입 | 필수 | 비고 |
|------|------|------|------|
| carrier_id | str | O | |
| rate_type | enum | O | per_mile, per_cwt, flat |
| rate | decimal ≥0 | O | |
| min_charge, fuel_pct | decimal ≥0 | 선택 | |
| mode | str | 선택 | |

**locations** (선택 테이블): location_id(str, unique), address / lat+lon any_of, city, state, zip.

alias 기본값: `origin_postal_code→origin_zip`, `dest_postal_code→dest_zip`, `destination_zip→dest_zip`, `weight→weight_lb`, `cost→actual_cost`, `carrier→carrier_id`, `scac→carrier_id`.

## Interface

```python
from tmod.validation import validate, ValidationReport, Finding, SCHEMAS, parse_date, parse_decimal, parse_int

@dataclass(frozen=True)
class Finding:
    severity: str        # "ERROR" | "WARN"
    table: str
    row: int | None      # RawTable의 _row, 테이블 수준이면 None
    column: str | None
    code: str            # MISSING_TABLE | MISSING_COLUMN | UNKNOWN_COLUMN | MISSING_VALUE | BAD_TYPE
                         # | OUT_OF_RANGE | BAD_ENUM | MISSING_LOCATION | DUPLICATE_KEY | UNKNOWN_REF | INGEST_ISSUE
    detail: str

@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[Finding, ...]
    mapping: dict[str, dict[str, str]]        # table -> {schema_col: raw_col}  (alias 해소 결과)
    rejected: dict[str, frozenset[int]]        # table -> ERROR가 있는 _row 집합
    row_counts: dict[str, tuple[int, int]]     # table -> (전체, 통과)
    ok: bool                                   # ERROR 없음
    def summary(self) -> str

def validate(tables: dict[str, RawTable], schemas=SCHEMAS) -> ValidationReport
```

파서 (빈 문자열은 None 반환, 파싱 실패는 ValueError):
- `parse_decimal("$1,234.50") -> Decimal("1234.50")`
- `parse_int("12") -> 12`
- `parse_date("01/15/2024") -> date(2024,1,15)` — 허용 포맷: `%Y-%m-%d`, `%m/%d/%Y`, `%Y/%m/%d`, `%Y%m%d`, `%m/%d/%y`, 뒤에 시간(`T` 또는 공백 구분) 붙어 있으면 잘라냄

## 심각도 규칙
- 테이블 누락, 필수 컬럼 누락 → ERROR, 해당 테이블 전 행 rejected
- 필수값 누락, 타입 오류, 범위 오류, enum 오류, any_of 실패, unique 위반(두 번째 이후 행), FK 미존재 → 해당 행 ERROR
- 선택 컬럼의 타입/범위 오류 → 해당 행 ERROR (값이 있으면 맞아야 함)
- UNKNOWN_COLUMN, INGEST_ISSUE → WARN

## 승인 기준 (테스트)
1. 정상 shipments + rates → ok=True, rejected 비어 있음
2. rates 테이블 없음 → MISSING_TABLE ERROR, ok=False
3. 필수 컬럼 누락 → MISSING_COLUMN, 전 행 rejected
4. alias(`origin_postal_code`) → mapping에 `origin_zip` 해소, 오류 없음
5. weight_lb="abc" → BAD_TYPE, 해당 행만 rejected
6. weight_lb="-5" → OUT_OF_RANGE
7. rate_type="per_ton" → BAD_ENUM
8. origin 정보 전부 빈 행 → MISSING_LOCATION
9. shipment_id 중복 → 두 번째 행 DUPLICATE_KEY
10. carrier_id가 rates에 없음 → UNKNOWN_REF
11. Node 01 RAGGED_ROW → INGEST_ISSUE WARN, 행은 통과
12. 파서: `$1,234.50`, `01/15/2024`, `2024-01-15 08:30`, 빈 문자열 None

## 알려진 한계 (ponytail)
- 스키마는 코드 상수. 외부 YAML 로딩은 실 고객 스키마 2개 이상 생기면 추가.
- 날짜 포맷 5종 고정. 모호한 `DD/MM/YYYY`는 지원하지 않음 (미국 TMS 기준).
