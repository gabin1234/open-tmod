# P06 — Product Frontend

상태: FROZEN (2026-09-12 승인)
버전: 1.0
`/product` 단일 페이지 (`web/product/index.html` + `app.js`), 빌드 없음, Leaflet CDN, `/api/v2`만 호출. 기존 `/`(LMD POC 화면)은 그대로.

## 화면 (스펙 §25)
| 탭 | 내용 |
|---|---|
| Scenarios | 목록(상태·shipment 수·run 수) · Create(code, name, plan_date, depot, provider, time limit) · 선택 시 편집: 제약 토글+params(jsonb 텍스트) · 목적함수 가중치(합 100 검증) · 차량 체크리스트 · 도로 조정 토글 · Copy · Delete · Populate · **Optimize**(job 폴링) · run 목록 → Result |
| Vehicles | vehicle_type / vehicle 표 + 인라인 편집(용량·비용·work/duty·shift) · soft delete |
| Shipments | 날짜 필터 표(customer, address, weight, volume, service, window, priority) · xlsx 업로드 · BY refresh |
| Map / Result | run 선택 → depot·stop 마커·차량별 route(실도로 geometry: `?detail=1`로 lazy route_detail)·stop 순서 번호 · 차량 클릭 시 stop 시퀀스 표(arrival/departure/service/distance) · unassigned 목록 |
| Road Weight | 지도 클릭 → 근처 segment 5개 → 선택 → 요일·시간대·factor·reason 저장 → 시나리오에 토글. segment 검색(도로명) |
| Compare | run A/B 선택 → 지표 delta 표 |

## API 추가 (P05 v1.1, additive)
- `GET /api/v2/runs/{id}?detail=1`: geometry 없는 leg는 시나리오 provider로 `route_detail` 호출(캐시 → 이후 즉시). provider 다운이면 직선

## 승인 기준
1. `/product` 200, `/static/product/app.js` 200 (테스트)
2. `runs/{id}?detail=1` 테스트: MANUAL provider(route None) → geometry null, 오류 없음
3. 브라우저: 시나리오 생성→Optimize→지도 실도로 route·stop 번호·시퀀스 표, Road Weight 저장, Compare 표 (스크린샷)

## 알려진 한계 (ponytail)
- 프레임워크 없음(약 500줄 JS). 화면이 더 늘면 컴포넌트화
- params 편집은 JSON 텍스트. 스키마 기반 폼은 후속
