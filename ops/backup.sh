#!/usr/bin/env bash
# Nightly backup: pg_dump (custom format) + private data + runs. Keeps 14 days. Usage: ops/backup.sh [dest_dir]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f ops/.env ] && source ops/.env; set +a
DEST="${1:-data/backups}"; mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M)
DSN="${TMOD_PG_DSN:-postgresql://tmod:tmod@localhost:5434/tmod}"
if command -v pg_dump >/dev/null; then pg_dump -Fc "$DSN" > "$DEST/tmod-$STAMP.dump"
else docker exec "${TMOD_PG_CONTAINER:-tmod-postgres}" pg_dump -U tmod -Fc tmod > "$DEST/tmod-$STAMP.dump"; fi
tar -czf "$DEST/data-$STAMP.tgz" --exclude='*.pbf' --exclude='*.osrm*' -C data private runs 2>/dev/null || true
find "$DEST" -name 'tmod-*.dump' -mtime +14 -delete; find "$DEST" -name 'data-*.tgz' -mtime +14 -delete
echo "backup ok: $DEST/tmod-$STAMP.dump ($(du -h "$DEST/tmod-$STAMP.dump" | cut -f1)), data-$STAMP.tgz"
