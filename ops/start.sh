#!/usr/bin/env bash
# Start (or restart) the LMD web app on this Mac. Token from ops/.env (TMOD_WEB_TOKEN). Port 8090 (8080 is taken).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source ops/.env; set +a
pkill -f "uvicorn tmod.web.app" 2>/dev/null || true
nohup uv run uvicorn tmod.web.app:app --host 0.0.0.0 --port "${TMOD_WEB_PORT:-8090}" >> data/web.log 2>&1 &
sleep 3
curl -sf "http://127.0.0.1:${TMOD_WEB_PORT:-8090}/api/health?token=$TMOD_WEB_TOKEN" >/dev/null && echo "web up: http://$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1):${TMOD_WEB_PORT:-8090}/?token=$TMOD_WEB_TOKEN"
