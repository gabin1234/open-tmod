#!/usr/bin/env bash
# Start a local Valhalla (OSM road routing) for the LMD track. Georgia extract, truck costing.
# Usage: scripts/valhalla_up.sh [custom_files_dir]   -> http://localhost:8002
set -euo pipefail
DIR="${1:-${VALHALLA_DIR:-$PWD/data/private/valhalla}}"
mkdir -p "$DIR"
if [ ! -f "$DIR/georgia-latest.osm.pbf" ] && ! ls "$DIR"/*.pbf >/dev/null 2>&1; then
  curl -L -o "$DIR/georgia-latest.osm.pbf" https://download.geofabrik.de/north-america/us/georgia-latest.osm.pbf
fi
docker rm -f valhalla >/dev/null 2>&1 || true
docker run -d --name valhalla -p 8002:8002 -v "$DIR:/custom_files" \
  -e serve_tiles=True -e build_elevation=False -e build_admins=True -e build_time_zones=True \
  -e use_tiles_ignore_pbf=True -e force_rebuild=False \
  ghcr.io/gis-ops/docker-valhalla/valhalla:latest >/dev/null
echo "valhalla starting (tile build ~5-15 min on first run). Check: curl -s localhost:8002/status"
