# Node 01 — Ingestion

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
CSV 파일 bytes를 읽어 문자열 행 테이블(RawTable)로 만든다. 의미를 해석하지 않는다.

- 인코딩 판별: utf-8-sig → cp949 → latin-1 순으로 시도
- 구분자 판별: `, ; \t |` 중 sniff, 실패 시 `,`
- 헤더 정규화: strip, lowercase, 비단어 문자(`\W`, 공백/괄호/기호)는 `_`로 치환, 양끝 `_` 제거. 한글 등 유니코드 문자는 보존
- 행 단위 provenance: 각 행에 예약 키 `_row` (원본 파일의 물리적 줄 번호, 헤더=1)
- 파일 sha256 기록 (재현성)
- 구조적 이상은 Issue로 기록하되 행을 버리지 않는다

## 비책임 (다음 Node로 넘김)
- 필수 컬럼 존재 여부, 타입 변환, 범위 검사 → Node 02 Validation
- 컬럼 → 도메인 필드 매핑 → Node 03 Canonical Model

## Interface

```python
from tmod.ingestion import ingest_csv, ingest, RawTable, Issue

@dataclass(frozen=True)
class Issue:
    code: str          # EMPTY_HEADER | DUPLICATE_COLUMN | RAGGED_ROW | BLANK_ROW
    row: int | None    # 물리적 줄 번호, 헤더 관련이면 None
    detail: str

@dataclass(frozen=True)
class RawTable:
    name: str                        # 논리 테이블명 ("shipments", "rates", ...)
    source: str                      # 파일 경로
    sha256: str
    encoding: str
    delimiter: str
    columns: tuple[str, ...]         # 정규화된 헤더
    raw_columns: tuple[str, ...]     # 원본 헤더
    rows: tuple[dict[str, str], ...] # 정규화 컬럼 → 문자열 값, + "_row": int
    issues: tuple[Issue, ...]

def ingest_csv(path, name=None) -> RawTable      # name 생략 시 파일 stem
def ingest(files: dict[str, str | Path]) -> dict[str, RawTable]
```

## 오류 처리
| 상황 | 처리 |
|------|------|
| 빈 파일 / 공백만 | `ValueError` |
| 헤더 셀 비어 있음 | 컬럼명 `col_{i}` 부여, Issue EMPTY_HEADER |
| 정규화 후 헤더 중복 | `_2`, `_3` 접미사, Issue DUPLICATE_COLUMN |
| 행 필드 수 < 헤더 | 빈 문자열로 채움, Issue RAGGED_ROW |
| 행 필드 수 > 헤더 | 초과분 버림, Issue RAGGED_ROW (버린 값 detail에 기록) |
| 완전 빈 행 | 건너뜀, Issue BLANK_ROW |

## 승인 기준 (테스트로 검증)
1. utf-8-sig BOM 파일: 첫 컬럼명에 BOM 없음
2. cp949 파일(한글): 깨짐 없이 디코딩, encoding == "cp949"
3. 세미콜론 구분 파일 자동 감지
4. 헤더 정규화: `" Ship Date "` → `ship_date`, `"Weight (lb)"` → `weight_lb`
5. ragged row 두 방향 모두 Issue 기록, 행 유지
6. `_row`가 물리적 줄 번호와 일치 (멀티라인 quoted 필드 포함)
7. 같은 파일 두 번 ingest → 동일 sha256, 동일 rows
8. 빈 파일 → ValueError
9. `ingest()`가 논리명 키로 dict 반환

## 알려진 한계 (ponytail)
- 파일 전체를 메모리에 올린다. POC 규모(수십만 행 이하)에서는 충분. 스트리밍은 필요 시 추가.
- Excel(xlsx) 미지원. CSV만.
