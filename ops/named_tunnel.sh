#!/usr/bin/env bash
# Fixed public URL via a Cloudflare NAMED tunnel (survives restarts, unlike the quick tunnel).
#
# One-time prerequisites (you must do these yourself — they need your Cloudflare account):
#   1. Free Cloudflare account, with a domain added as a zone.
#   2. cloudflared tunnel login      <- opens a browser, pick the zone, writes ~/.cloudflared/cert.pem
# Then:
#   ops/named_tunnel.sh tmod.yourdomain.com
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source ops/.env; set +a

HOST="${1:-}"
NAME="${TUNNEL_NAME:-tmod}"
PORT="${TMOD_WEB_PORT:-8090}"
CFDIR="$HOME/.cloudflared"
BIN="$(command -v cloudflared)"

[ -n "$HOST" ] || { echo "usage: ops/named_tunnel.sh <hostname, e.g. tmod.yourdomain.com>" >&2; exit 2; }
[ -f "$CFDIR/cert.pem" ] || { cat >&2 <<'MSG'
Not logged in to Cloudflare. Run this yourself first (it opens a browser):

    cloudflared tunnel login

Pick the domain you want to use. It writes ~/.cloudflared/cert.pem, then re-run this script.
MSG
exit 3; }

# 1. tunnel (idempotent)
if UUID=$("$BIN" tunnel list --output json 2>/dev/null | python3 -c "import json,sys;print(next((t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'),''))"); [ -n "$UUID" ]; then
  echo "tunnel '$NAME' exists: $UUID"
else
  "$BIN" tunnel create "$NAME"
  UUID=$("$BIN" tunnel list --output json | python3 -c "import json,sys;print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'))")
  echo "tunnel '$NAME' created: $UUID"
fi

# 2. config
cat > "$CFDIR/config.yml" <<CFG
tunnel: $UUID
credentials-file: $CFDIR/$UUID.json
protocol: http2
ingress:
  - hostname: $HOST
    service: http://localhost:$PORT
  - service: http_status:404
CFG
echo "wrote $CFDIR/config.yml"

# 3. DNS record (idempotent; --overwrite-dns replaces a stale one pointing at an old tunnel)
"$BIN" tunnel route dns --overwrite-dns "$NAME" "$HOST"

# 4. swap launchd: stop the quick tunnel, run the named one
PLIST="$HOME/Library/LaunchAgents/com.lgcns.tmod-tunnel.plist"
launchctl unload "$PLIST" 2>/dev/null || true
sed -e "s|@BIN@|$BIN|g" -e "s|@CFDIR@|$CFDIR|g" -e "s|@NAME@|$NAME|g" -e "s|@PWD@|$PWD|g" \
    ops/com.lgcns.tmod-tunnel-named.plist > "$PLIST"
launchctl load "$PLIST"

echo "https://$HOST" > data/public_url.txt
echo
echo "fixed URL: https://$HOST/product?token=$TMOD_WEB_TOKEN"
echo "(DNS + first connection take ~30s; check with: bash ops/url.sh)"
