#!/usr/bin/env bash
# Public URL via Cloudflare quick tunnel (no account; ngrok is blocked on the corporate network). Prints the https URL.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source ops/.env; set +a
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup cloudflared tunnel --url "http://localhost:${TMOD_WEB_PORT:-8090}" --no-autoupdate >> data/cloudflared.log 2>&1 &
for i in $(seq 1 40); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' data/cloudflared.log | grep -v '^https://api\.' | tail -1 || true)
  [ -n "$URL" ] && { echo "public: $URL/?token=$TMOD_WEB_TOKEN"; exit 0; }
  sleep 1
done
echo "cloudflared did not come up; see data/cloudflared.log" >&2; exit 1
