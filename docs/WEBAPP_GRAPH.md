# Web App — Master Graph (2026-09-11)

결정: FastAPI + 순수 JS/Leaflet, MVP = 실행·조회, 데이터 = QA DB(AICTMSNQ) 읽기 전용 + 추출 캐시, 서비스 = 이 맥(LAN). 엔진(tmod/lmd_*)은 FROZEN 그대로 호출만 한다.

## Node 순서 (고정)
| WN | Node | 책임 | 산출물 |
|----|------|------|--------|
| W01 | Backend API | 데이터셋 목록, 시나리오 실행(백그라운드), 실행 이력·결과 JSON. 결과 직렬화 계약 | `tmod/web/app.py`, `serialize.py`, `runs.py` |
| W02 | Frontend | 단일 페이지: 데이터셋 선택 → 시나리오 폼 → 실행 → 이력 → KPI·지도·load 테이블 (실도로 polyline, 일자 필터) | `web/index.html`, `web/app.js` |
| W03 | Data Refresh + Health | QA DB 재추출 엔드포인트(crt_by 선택), Valhalla/DB 헬스, 추출 상태 | `tmod/web/refresh.py` |
| W04 | Ops | launchd 서비스(앱·Valhalla), 로그, README 운영 절차, e2e 스모크 테스트 | `ops/`, `README.md` |

게이트: 각 Node contract → 구현 → 테스트(`uv run pytest`) → 승인 → FROZEN(tag `web-WNN`).

## 비범위 (MVP)
- 인증(LAN 신뢰), Dispatch 편집, 다중 hub, DB 쓰기
