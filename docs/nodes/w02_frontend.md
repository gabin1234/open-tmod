# W02 — Frontend

상태: FROZEN (2026-09-11 전체 사전 승인)
버전: 1.0
빌드 없음. `web/index.html` + `web/app.js` + Leaflet CDN. W01 API만 호출.

## 화면
- 좌측: 데이터셋 select(`/api/datasets`) · 시나리오 폼(LmdScenario 필드 전부, 기본값 `/api/scenarios/default`) · Valhalla 사용 체크(`/api/health`의 valhalla 상태로 기본값) · 실행 버튼 · 실행 이력(`/api/runs`, 3초 폴링, 상태 배지, 클릭 시 결과 로드, 삭제)
- 우측 상단: KPI 표 (baseline / scenario / delta / delta%). 게이트 미통과 시 delta 열 GATED
- 우측 중단: 지도. hub 마커, baseline 회색 halo, scenario 색상 polyline (legs.geometry 있으면 실도로, 없으면 직선), stop 원, 일자 select, baseline/scenario 토글, 초과 load 점선, hover 툴팁
- 우측 하단: scenario load 테이블 (load, day, truck, stops, miles, duty, late, over). 행 클릭 → 해당 load만 강조 + 지도 fit

## 계약
- 결과 JSON = W01 `run_to_json`. 프론트는 이 구조만 안다
- 상태 전이: queued → running → done | error. error면 이력에 빨간 배지 + 메시지

## 승인 기준
1. `/`가 index.html, `/static/app.js` 200 (테스트)
2. 브라우저: 데이터셋 로드 → 실행 → 이력에 running → done → KPI·지도·테이블 렌더 (스크린샷)
3. 일자 필터·토글·행 클릭 동작

## 알려진 한계 (ponytail)
- 프레임워크 없음. 화면이 3개 이상 늘면 그때 컴포넌트화
- 결과 JSON 수 MB(geometry). 지연 시 legs geometry를 별도 엔드포인트로 분리
