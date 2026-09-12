# P11 — 운영 통합 (compose · 인증 · 백업 · 헬스)

상태: REVIEW (승인 대기)
버전: 1.0

## 구성
| 항목 | 산출물 | 내용 |
|---|---|---|
| 컨테이너 배포 | `Dockerfile`, `docker-compose.yml`(루트) | 서비스 5개: `postgres`(16, 볼륨), `osrm`(사전 빌드 그래프 마운트), `valhalla`(gis-ops, OSM 마운트), `api`(이 저장소, uvicorn :8090, `data/` 볼륨), `cloudflared`(profile `tunnel`, 선택). 서버(Linux/Windows Docker)로 옮길 때 `docker compose up -d` 한 줄. 이 맥은 기존 launchd 유지(둘 중 하나) |
| 인증 | `tmod/web/app.py` 미들웨어 v1.1 | `TMOD_USERS="user:pass,user2:pass"` 설정 시 HTTP Basic 로그인(브라우저 프롬프트, 성공 시 30일 쿠키). 토큰(`TMOD_WEB_TOKEN`)은 API 클라이언트용으로 병행. LAN 면제는 `TMOD_LAN_OPEN=1`일 때만(기본 off → 사내에서도 로그인) |
| 백업 | `ops/backup.sh`, `ops/com.lgcns.tmod-backup.plist` | 매일 02:00 `pg_dump`(custom format) + `data/private`·`data/runs` tar → `data/backups/`, 14일 보관. `ops/restore.sh <dump>` |
| 헬스 | `/api/health` v1.1 | `postgres`(제품 DB), `db`(Blue Yonder Oracle 소스), `valhalla`, `osrm`, `disk_free_gb`, `version`(git tag) |
| 문서 | `README.md` 운영 절차 | 기동·재기동·백업·복구·URL·토큰 교체 |

## 승인 기준 (테스트)
1. `docker compose config` 유효, `docker build` 성공, api 컨테이너 `/api/health` 200 (compose 스모크, docker 없으면 skip)
2. Basic auth: `TMOD_USERS` 설정 → 무인증 401(+`WWW-Authenticate`), 올바른 자격 200 + 쿠키, 잘못된 자격 401, 토큰 헤더도 200
3. `ops/backup.sh` 실행 → dump·tar 생성, `restore.sh`로 빈 DB 복원 후 테이블 수 일치 (docker pg)

## 알려진 한계 (ponytail)
- 사용자 목록은 env 평문(팀 ≤5명). SSO/OIDC는 요구 시
- compose의 valhalla/osrm은 그래프 빌드가 선행(README 절차). 이미지 크기·빌드 시간은 그대로
