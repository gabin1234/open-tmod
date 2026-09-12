# P03 — Routing Data (OSRM / Valhalla, distance cache, road segments, adjustments)

상태: FROZEN (2026-09-12 승인)
버전: 1.0

## 책임
- `RoadProvider` 프로토콜: `matrix(coords)` (거리 m·시간 s 행렬), `route(a, b)` (거리·시간·geometry·**edge 목록**)
- 구현 2종: `OSRMProvider` (스펙 기본, `/table` + `/route?steps=true`; OSRM은 way_id를 노출하지 않아 edge_ref=node쌍·도로명만), `ValhallaRoadProvider` (`/sources_to_targets` + `/route` + `/trace_attributes`, edge마다 **osm way_id**·edge id·길이·소요). 시나리오 `distance_provider`로 선택
- `fill_distance_cache(con, provider_code, provider, location_ids, profile)`: 누락 쌍만 행렬 조회(청크 ≤100) → `distance_cache`
- `route_detail(con, provider_code, provider, from_id, to_id)`: 경로 geometry + edge → `road_segment` upsert(osm_way_id 우선, 없으면 edge_ref; `segment_code=SEG-{id:06d}`) + 캐시 행에 `segment_ids`, `segment_durations_s`
- `adjusted_duration(con, from_id, to_id, provider, plan_date, depart_s, scenario_id=None)`: 캐시 segment별 소요에 `road_adjustment`(요일·시간대·factor, 시나리오 선택분) 적용. segment 정보 없으면 원 duration
- 사용자 노출: `road_segment.road_name` + `segment_code`. OSM/edge id는 내부

## Interface
```python
from tmod.product.routing import OSRMProvider, ValhallaRoadProvider, fill_distance_cache, route_detail, adjusted_duration, RouteDetail, Edge
```
CLI: `uv run python -m tmod.product.routing fill --provider VALHALLA|OSRM [--scenario SC-…]` (시나리오 shipment 위치 + depot)

## 승인 기준 (테스트, docker pg + mock provider)
1. 3 위치 → fill: 6쌍 캐시, 재실행 0 조회
2. route_detail: edge 2개 → road_segment 2행(재실행 시 중복 없음), segment_ids/segment_durations_s 저장
3. adjusted_duration: 07–09 ×1.5 조정이 걸린 segment만 가중, 09시 이후 출발은 원값, 시나리오 미선택 조정은 무시
4. Valhalla 실행 중이면 실제 hub→zip 1쌍 스모크 (skip-if-down)
5. OSRM 실행 중이면 `/table` 스모크 (skip-if-down)

## 알려진 한계 (ponytail)
- 행렬 캐시는 segment 정보 없음(빠름). 조정 반영은 `route_detail`을 거친 쌍만. P04에서 시나리오 쌍을 미리 route_detail로 채우는 옵션(`settings.detail_routes`)
- OSRM car 프로파일(:5001, 5000은 macOS AirPlay). truck 프로파일은 lua 커스텀 필요 → Valhalla truck이 기본 권장
- Valhalla 행렬은 50×50 truck에서 컨테이너가 죽음(재시작) → 블록 20(청크 10). 307 위치 = 약 950 호출, OSRM은 200 블록으로 11초
