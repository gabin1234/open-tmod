#!/usr/bin/env bash
# Restore a pg_dump custom-format file into the tmod database (drops and recreates schema tmod). Usage: ops/restore.sh data/backups/tmod-YYYYMMDD-HHMM.dump
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f ops/.env ] && source ops/.env; set +a
DSN="${TMOD_PG_DSN:-postgresql://tmod:tmod@localhost:5434/tmod}"
if command -v pg_restore >/dev/null; then pg_restore --clean --if-exists --no-owner -d "$DSN" "$1"
else docker exec -i "${TMOD_PG_CONTAINER:-tmod-postgres}" pg_restore --clean --if-exists --no-owner -U tmod -d tmod < "$1"; fi
echo "restored $1"
