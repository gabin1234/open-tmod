# W04 — Ops

상태: FROZEN (2026-09-11 전체 사전 승인)
버전: 1.0

## 구성
| 항목 | 방법 |
|------|------|
| 앱 기동 | `ops/start.sh` — `ops/.env`의 `TMOD_WEB_TOKEN` 로드, uvicorn 0.0.0.0:8090 (8080은 다른 서비스 점유) |
| 상시 기동 | `ops/com.lgcns.tmod-web.plist` → `~/Library/LaunchAgents/` 로 복사 후 `launchctl load` |
| 외부 URL | `ops/tunnel.sh` — Cloudflare quick tunnel(cloudflared, 계정 불필요) → `https://<random>.trycloudflare.com/?token=…`. 토큰 없으면 401. **ngrok은 사내망에서 차단(outbound 000)**, Tailscale Funnel은 승인 대기로 보류 |
| Valhalla | `scripts/valhalla_up.sh <osm_dir>` (docker, 재부팅 후 `docker start valhalla`) |
| 로그 | `data/web.log`, `data/cloudflared.log` |
| 실행 결과 | `data/runs/*.json` (gitignore) |

## 접근 제어
- `TMOD_WEB_TOKEN` 설정 시 모든 요청에 `?token=` / `Authorization: Bearer` / 쿠키 필요. `/?token=…` 첫 접속 시 쿠키 발급(30일)
- 토큰 재발급 = `ops/.env` 수정 + `ops/start.sh`. quick tunnel URL은 재기동마다 바뀜(고정 도메인은 Cloudflare 계정 + named tunnel)
- 데이터 = 실 운영 shipment(zip·주소). 외부 URL은 팀 내부 공유 한정, 토큰 유출 시 즉시 재발급

## 승인 기준
1. `ops/start.sh` 후 `/api/health`가 토큰 없이 401, 토큰으로 200
2. `ops/tunnel.sh`가 public URL 출력, 외부에서 `/?token=` 접속 시 UI 로드
3. 전체 테스트 통과
