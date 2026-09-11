#!/usr/bin/env bash
# Print current URLs (tunnel URL changes whenever the tunnel restarts).
cd "$(dirname "$0")/.."; set -a; source ops/.env; set +a
echo "LAN:    http://$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1):8090/?token=$TMOD_WEB_TOKEN"
echo "public: $(cat data/public_url.txt 2>/dev/null)/?token=$TMOD_WEB_TOKEN"
