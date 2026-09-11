#!/usr/bin/env bash
# Install/refresh launchd agents for the web app + tunnel, and make the Valhalla container auto-restart.
set -euo pipefail
cd "$(dirname "$0")/.."
pkill -f "uvicorn tmod.web.app" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
mkdir -p ~/Library/LaunchAgents data
for s in web tunnel; do
  launchctl bootout "gui/$(id -u)/com.lgcns.tmod-$s" 2>/dev/null || true
  cp "ops/com.lgcns.tmod-$s.plist" ~/Library/LaunchAgents/
  launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.lgcns.tmod-$s.plist
done
docker update --restart unless-stopped valhalla >/dev/null 2>&1 && echo "valhalla: restart=unless-stopped (needs Docker Desktop to start at login)"
set -a; source ops/.env; set +a
for i in $(seq 1 30); do curl -sf "http://127.0.0.1:8090/api/health?token=$TMOD_WEB_TOKEN" >/dev/null && break; sleep 1; done
for i in $(seq 1 40); do [ -s data/public_url.txt ] && break; sleep 1; done
echo "LAN:    http://$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1):8090/?token=$TMOD_WEB_TOKEN"
echo "public: $(cat data/public_url.txt 2>/dev/null || echo '(tunnel not up yet, see data/cloudflared.log)')/?token=$TMOD_WEB_TOKEN"
