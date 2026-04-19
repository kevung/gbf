#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Build derived parquet files (idempotent: skips if already present).

if [[ ! -f data/barycentric/barycentric_v2.parquet ]]; then
  echo "==> Computing barycentric_v2.parquet…"
  python scripts/compute_barycentric_v2.py \
    --enriched data/parquet/positions_enriched \
    --games    data/parquet/games.parquet \
    --output   data/barycentric
fi

if [[ ! -f data/barycentric/cell_keys.parquet ]]; then
  echo "==> Computing cell_keys.parquet…"
  python scripts/compute_cell_keys.py \
    --input  data/barycentric/barycentric_v2.parquet \
    --output data/barycentric/cell_keys.parquet \
    --audit  data/barycentric/crawford_audit.txt
fi

if [[ ! -f data/barycentric/bootstrap_cells.parquet ]]; then
  echo "==> Computing bootstrap_cells.parquet…"
  python scripts/bootstrap_cells.py \
    --input     data/barycentric/barycentric_v2.parquet \
    --output    data/barycentric/bootstrap_cells.parquet \
    --report    data/barycentric/bootstrap_report.txt \
    --k 50 --draw-size 500000
fi

# 2. Launch barycentric service in the background.
echo "==> Starting barycentric service on :8100…"
python scripts/barycentric_service.py \
  --bary     data/barycentric/barycentric_v2.parquet \
  --cells    data/barycentric/cell_keys.parquet \
  --boot     data/barycentric/bootstrap_cells.parquet \
  --enriched data/parquet/positions_enriched \
  --games    data/parquet/games.parquet \
  --matches  data/parquet/matches.parquet \
  --port     8100 &
SERVICE_PID=$!

# Wait until the service is ready (up to 15 s).
echo "==> Waiting for service…"
for i in $(seq 1 15); do
  if curl -sf http://localhost:8100/api/bary/health > /dev/null 2>&1; then
    echo "==> Service ready."
    break
  fi
  sleep 1
done

# 3. Frontend dev server (foreground).
echo "==> Starting explorer dev server…"
(cd explorer && npm install --silent && npm run dev)

# Cleanup on exit.
kill "$SERVICE_PID" 2>/dev/null || true
