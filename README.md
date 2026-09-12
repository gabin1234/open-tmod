# Open T-Modeler

Graph Engineering으로 만든 개방형 Transportation Modeling Platform POC. 진행 규칙은 `CLAUDE.md`, 노드 계약은 `docs/nodes/`, 그래프는 `docs/MASTER_GRAPH.md` · `docs/LMD_TRACK.md` · `docs/WEBAPP_GRAPH.md`.

## 빠른 시작 (LMD 라우팅 웹앱)
```bash
uv sync --extra extract                                   # + oracledb (QA DB 추출용)
scripts/valhalla_up.sh data/private/valhalla              # 실도로 (docker, 최초 5~15분)
uv run --extra extract python scripts/extract_lmd.py      # QA DB LMD_SHIPMENT -> data/private/lmd_*  (또는 웹 UI Refresh)
ops/start.sh                                              # http://<이 맥 IP>:8090/?token=...
ops/tunnel.sh                                             # 외부 URL (Cloudflare quick tunnel)
```
CLI만: `uv run python -m tmod.lmd_poc data/private/lmd_lphb30260_demo data/scenarios/lmd_windows.json out.html --valhalla http://localhost:8002`

테스트: `uv run pytest -q`

## 운영 (P11)
| 작업 | 명령 |
|---|---|
| 이 맥 상시 기동 | `ops/install_launchd.sh` (web + Cloudflare 터널), `ops/com.lgcns.tmod-backup.plist` (매일 02:00 백업) |
| 현재 URL/토큰 | `ops/url.sh` |
| 접근 제어 | `ops/.env`: `TMOD_WEB_TOKEN`(API·공유 링크), `TMOD_USERS="alice:pw,bob:pw"`(브라우저 로그인), `TMOD_LAN_OPEN=1`(사설 IP 무인증) |
| 백업 / 복구 | `ops/backup.sh` → `data/backups/tmod-*.dump`, `data-*.tgz` (14일 보관) · `ops/restore.sh <dump>` |
| 헬스 | `GET /api/health` → version, db, valhalla, osrm, disk_free_gb |
| 서버(Docker) 배포 | 그래프 준비 후 `docker compose up -d` (postgres · osrm · valhalla · api), 공개 URL은 `--profile tunnel`. 환경: `PG_PASSWORD`, `TMOD_WEB_TOKEN`, `TMOD_USERS`, `OSRM_DIR`, `VALHALLA_DIR` |
| 재부팅 후 (맥) | Docker Desktop 자동 시작 → 컨테이너 restart 정책 → launchd가 web/터널 기동. 확인: `ops/url.sh`, `/api/health` |
