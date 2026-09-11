# Node 05 — Geocoding

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
lat/lon이 없는 `Location`에 좌표를 부여한다. Provider 인터페이스 뒤에서 동작하며, 캐시를 통해 반복 호출을 막는다.

- lat/lon이 이미 있으면 pass-through (precision `"given"`)
- Provider를 순서대로 시도, 첫 성공 사용
- 기본 Provider: `ZipCentroidGeocoder` — 미국 ZCTA 중심점 테이블 (`data/zip_centroids.csv`, Census 2023 Gazetteer, public domain, 33,791 zip). 정확 매치 실패 시 3자리 prefix 평균 좌표로 fallback (precision `"zip3"`)
- 캐시: `dict[location.key, GeoResult]`. `load_cache/save_cache`로 JSON 영속화
- 실패는 UNGEOCODED issue. Location은 좌표 없이 유지 (Node 06이 거리 계산 불가로 처리)

## 비책임
- 도로 거리/시간 → Node 06
- 외부 HTTP geocoder (Nominatim, PC Miler) 구현 → Provider 프로토콜만 정의. POC는 zip centroid로 충분. 주소 위주 데이터 생기면 Provider 추가 (contract 변경 없음)

## Interface

```python
from tmod.geocoding import geocode, Geocoder, GeoResult, ZipCentroidGeocoder, load_cache, save_cache, GeocodeReport

@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    precision: str      # "given" | "zip" | "zip3" | Provider 정의 문자열

class Geocoder(Protocol):
    name: str
    def geocode(self, loc: Location) -> GeoResult | None: ...

class ZipCentroidGeocoder:
    def __init__(self, path: str | Path = "data/zip_centroids.csv") -> None
    name = "zip_centroid"

@dataclass(frozen=True)
class GeocodeReport:
    total: int                        # 고유 Location 수
    by_precision: dict[str, int]      # {"given": n, "zip": n, "zip3": n}
    ungeocoded: tuple[str, ...]       # Location.key 목록
    cache_hits: int

def geocode(ds: Dataset, providers: Sequence[Geocoder], cache: dict[str, GeoResult] | None = None) -> tuple[Dataset, GeocodeReport]
def load_cache(path) -> dict[str, GeoResult]     # 파일 없으면 {}
def save_cache(path, cache) -> None
```

`geocode`는 `ds.locations`(고유 Location) 기준으로 한 번씩만 조회하고, 결과를 shipments의 origin/dest와 named_locations에 반영한다. 좌표가 채워지면 `Location.key`가 `ll:`로 바뀌므로 `Dataset.locations`를 재구성한다.

## 승인 기준 (테스트)
1. lat/lon 있는 Location은 Provider 호출 없이 `given`
2. zip `60601` → ZCTA 중심점 (lat 41.8~41.9, lon -87.7~-87.6), precision `zip`
3. ZCTA에 없는 zip (예: `60699`) → 3자리 prefix 평균, precision `zip3`
4. 존재하지 않는 prefix (`00099`) → ungeocoded, Location 좌표 None 유지
5. 같은 key 두 번 → Provider 1회 호출, `cache_hits` 증가
6. `save_cache` → `load_cache` 왕복 동일
7. Provider 2개 순서: 첫 번째 None이면 두 번째 사용
8. 결과 Dataset에서 shipments origin/dest 좌표 반영, locations 재구성

## 알려진 한계 (ponytail)
- ZCTA ≠ USPS zip. PO Box 전용 zip은 zip3 fallback. 정밀 요율(zip-to-zip mileage) 검증 단계에서 Baseline ±2%에 영향 있으면 PC Miler zip DB로 Provider 교체.
- 테이블 전체(34k행) 메모리 로드, 약 3MB. 문제 없음.
