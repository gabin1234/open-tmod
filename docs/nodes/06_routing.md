# Node 06 — Road Routing

상태: FROZEN (2026-09-10 승인)
버전: 1.0

## 책임
O-D Location 쌍의 도로 거리(miles)와 시간(minutes)을 계산한다. **Provider 책임**: 구현체는 교체 가능하고 상위 Node는 `Route`만 본다. OR-Tools는 사용하지 않는다.

- Provider 순서대로 시도, 첫 성공 사용 (예: Valhalla → Haversine fallback)
- 고유 (origin.key, dest.key) 쌍당 1회 호출. 캐시 우선, JSON 영속화
- 좌표 없는 Location이 포함된 쌍은 `unrouted`

## Provider
| Provider | 소스 | 비고 |
|----------|------|------|
| `HaversineProvider(circuity=1.2, mph=50)` | 계산 | 오프라인 기본값. 대권거리 × circuity. **circuity와 mph는 Baseline 캘리브레이션 knob** |
| `ValhallaProvider(base_url, costing="truck", timeout=10)` | HTTP `POST {base_url}/route` | stdlib urllib. 네트워크/HTTP 오류 시 None 반환 → 다음 Provider |
| PC Miler | — | API key 확보 시 같은 프로토콜로 추가. contract 변경 없음 |

## Interface

```python
from tmod.routing import route_matrix, Route, RoutingProvider, HaversineProvider, ValhallaProvider, RoutingReport, load_cache, save_cache, haversine_miles

@dataclass(frozen=True)
class Route:
    miles: float
    minutes: float
    provider: str

class RoutingProvider(Protocol):
    name: str
    def route(self, o: Location, d: Location) -> Route | None: ...

@dataclass(frozen=True)
class RoutingReport:
    pairs: int                       # 고유 O-D 쌍 수
    by_provider: dict[str, int]
    unrouted: tuple[tuple[str, str], ...]   # (origin.key, dest.key)
    cache_hits: int

RouteMatrix = dict[tuple[str, str], Route]   # (origin.key, dest.key) -> Route

def route_matrix(ds: Dataset, providers: Sequence[RoutingProvider], cache: RouteMatrix | None = None) -> tuple[RouteMatrix, RoutingReport]
def haversine_miles(lat1, lon1, lat2, lon2) -> float
def load_cache(path) -> RouteMatrix
def save_cache(path, cache) -> None
```

같은 Location 쌍(o.key == d.key)은 `Route(0, 0, "same")`.

## 승인 기준 (테스트)
1. `haversine_miles(Chicago, NYC)` ≈ 711 (±5)
2. `HaversineProvider(circuity=1.2)` → 711×1.2, minutes = miles/50×60
3. Provider 순서: 첫 번째 None → 두 번째 사용, `by_provider` 집계
4. 좌표 없는 쌍 → `unrouted`, matrix에 없음
5. 중복 쌍 → Provider 1회, 두 번째 실행 시 `cache_hits`
6. 캐시 save/load 왕복
7. ValhallaProvider: 응답 JSON `trip.summary.length/time` 파싱 (urlopen 대체), 오류 시 None
8. 동일 Location → `Route(0,0,"same")`

## 알려진 한계 (ponytail)
- 좌표 기반만. zip-to-zip 요율표 기반 mileage(PC Miler zip DB)는 Provider로 추가.
- 캐시 key는 `Location.key` 문자열. Provider 바뀌면 캐시 파일 별도 관리 (파일명에 provider 포함 권장).
