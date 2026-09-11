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
