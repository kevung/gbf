#!/usr/bin/env bash
# Full BMAB pipeline: batched S0.1+S0.2, then S0.4→S3.6 sequentially.
#
# Designed for constrained disk (30 GB free): exports .xg files in batches
# of BATCH_SIZE, converts each batch to Parquet immediately, then deletes
# the intermediate JSONL before the next batch.
#
# Usage:
#   ./scripts/run_full_pipeline.sh [options]
#
# Options:
#   --xg-dir DIR      Source .xg directory (default: data/bmab-2025-06-23)
#   --parquet-dir DIR  Output Parquet directory (default: data/parquet)
#   --output-dir DIR   Analysis output base directory (default: data)
#   --batch-size N     Files per batch (default: 1000)
#   --chunk-rows N     Rows per Polars chunk in converter (default: 100000)
#   --skip-export      Skip S0.1+S0.2 (Parquet already exists)
#   --start-at STEP    Start at a specific step (e.g., S0.4, S1.3, S3.1)
#   --no-dedup-sources Skip source deduplication (process all files incl. duplicates)
#   --dry-run          Print commands without executing

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────
XG_DIR="data/bmab-2025-06-23"
PARQUET_DIR="data/parquet"
OUTPUT_DIR="data"
BATCH_SIZE=1000
CHUNK_ROWS=100000
SKIP_EXPORT=false
DEDUP_SOURCES=true
START_AT=""
DRY_RUN=false

# ── Parse arguments ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --xg-dir)           XG_DIR="$2"; shift 2 ;;
    --parquet-dir)      PARQUET_DIR="$2"; shift 2 ;;
    --chunk-rows)       CHUNK_ROWS="$2"; shift 2 ;;
    --output-dir)       OUTPUT_DIR="$2"; shift 2 ;;
    --batch-size)       BATCH_SIZE="$2"; shift 2 ;;
    --skip-export)      SKIP_EXPORT=true; shift ;;
    --no-dedup-sources) DEDUP_SOURCES=false; shift ;;
    --start-at)         START_AT="$2"; shift 2 ;;
    --dry-run)          DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

ENRICHED_DIR="${PARQUET_DIR}/positions_enriched"
CLUSTERS_DIR="${OUTPUT_DIR}/clusters"
PROFILES_DIR="${OUTPUT_DIR}/player_profiles"
STATS_DIR="${OUTPUT_DIR}/stats"
CUBE_DIR="${OUTPUT_DIR}/cube_analysis"

# ── Helpers ──────────────────────────────────────────────────────────
log() { echo "[pipeline] $(date '+%H:%M:%S') $*"; }
run() {
  log ">>> $*"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "(dry-run, skipping)"
  else
    "$@"
  fi
}

should_run() {
  # Returns 0 (true) if we should run this step given --start-at
  local step="$1"
  if [[ -z "$START_AT" ]]; then
    return 0
  fi
  # Simple ordering: compare step strings lexicographically
  [[ "$step" > "$START_AT" || "$step" == "$START_AT" ]]
}

disk_free() {
  df --output=avail -BG "$PARQUET_DIR" 2>/dev/null | tail -1 | tr -dc '0-9'
}

# ── Build Go exporter ────────────────────────────────────────────────
log "Building export-jsonl..."
run go build -o bin/export-jsonl ./cmd/export-jsonl/

# ═══════════════════════════════════════════════════════════════════════
# S0.1 + S0.2 — Batched JSONL Export + Parquet Conversion
# ═══════════════════════════════════════════════════════════════════════
if [[ "$SKIP_EXPORT" == "false" ]] && should_run "S0.1"; then
  log "=== S0.1 + S0.2: Batched export .xg → JSONL → Parquet ==="

  FILE_LIST=$(mktemp)

  if [[ "$DEDUP_SOURCES" == "true" ]]; then
    # Build source manifest: hash all .xg files, keep one canonical per duplicate group.
    # For BMAB this reduces 166K → 33K files (5× speedup, no post-export dedup needed).
    MANIFEST="${PARQUET_DIR}/.source_manifest.txt"
    if [[ ! -f "$MANIFEST" ]]; then
      log "Building source manifest (xxhash64 dedup) ..."
      run python scripts/build_source_manifest.py \
        --xg-dir "$XG_DIR" \
        --output "$MANIFEST" \
        --workers "$(nproc)"
    else
      log "Reusing existing manifest: $MANIFEST"
    fi
    cp "$MANIFEST" "$FILE_LIST"
  else
    find "$XG_DIR" -name '*.xg' -type f | sort > "$FILE_LIST"
  fi

  TOTAL_FILES=$(wc -l < "$FILE_LIST")
  log "Exporting $TOTAL_FILES .xg files"

  # Calculate number of batches
  NUM_BATCHES=$(( (TOTAL_FILES + BATCH_SIZE - 1) / BATCH_SIZE ))
  log "Processing in $NUM_BATCHES batches of $BATCH_SIZE files"

  mkdir -p "$PARQUET_DIR"
  JOURNAL="$PARQUET_DIR/.batch_journal"
  touch "$JOURNAL"

  for (( BATCH=0; BATCH < NUM_BATCHES; BATCH++ )); do
    # Skip already-completed batches (journal-based resume)
    if grep -qx "$BATCH" "$JOURNAL" 2>/dev/null; then
      log "Batch $BATCH already done (journal), skipping"
      continue
    fi

    SKIP=$(( BATCH * BATCH_SIZE ))
    log "--- Batch $BATCH/$((NUM_BATCHES-1)) (files $SKIP..$(( SKIP + BATCH_SIZE - 1 ))) ---"
    log "Disk free: $(disk_free) GB"

    # Create temp directory with symlinks to this batch's files
    BATCH_DIR=$(mktemp -d)
    JSONL_DIR=$(mktemp -d)

    while IFS= read -r f; do
      ln -s "$(realpath "$f")" "$BATCH_DIR/$(basename "$f")"
    done < <(sed -n "$((SKIP+1)),$((SKIP+BATCH_SIZE))p" "$FILE_LIST")

    # S0.1: Export this batch to JSONL
    run ./bin/export-jsonl -outdir "$JSONL_DIR" "$BATCH_DIR"

    # S0.2: Convert JSONL → Parquet (append mode, unique part naming)
    run python scripts/convert_jsonl_to_parquet.py \
      --jsonl-dir "$JSONL_DIR" \
      --parquet-dir "$PARQUET_DIR" \
      --batch-id "$BATCH" \
      --chunk-rows "$CHUNK_ROWS" \
      --append \
      --skip-verify

    # Clean up JSONL and temp dir immediately
    rm -rf "$JSONL_DIR" "$BATCH_DIR"

    # Record success in journal
    echo "$BATCH" >> "$JOURNAL"
    log "Batch $BATCH done. Disk free: $(disk_free) GB"
  done

  rm -f "$FILE_LIST"

  # Verify final Parquet counts
  log "=== Verifying Parquet output ==="
  POS_COUNT=$(python -c "
import pyarrow.parquet as pq
from pathlib import Path
files = sorted(Path('$PARQUET_DIR/positions').glob('part-*.parquet'))
total = sum(pq.read_metadata(str(f)).num_rows for f in files)
print(f'{total:,} positions across {len(files)} part files')
")
  log "Positions: $POS_COUNT"
fi

# S0.2b — Deduplication is only needed when --no-dedup-sources was used
# (i.e. all 166K BMAB files were exported instead of the 33K canonical ones).
if [[ "$DEDUP_SOURCES" == "false" ]] && should_run "S0.2b"; then
  log "=== S0.2b: Deduplication (--no-dedup-sources mode) ==="
  run python scripts/deduplicate_parquet.py \
    --parquet-dir "$PARQUET_DIR" \
    --chunk-rows 200000
fi

# ═══════════════════════════════════════════════════════════════════════
# S0.4 — Feature Engineering (on deduplicated positions)
# ═══════════════════════════════════════════════════════════════════════
if should_run "S0.4"; then
  log "=== S0.4: Feature Engineering ==="
  # Use positions_dedup if available (after S0.2b), else fall back to positions
  if [[ -d "$PARQUET_DIR/positions_dedup" ]]; then
    POSITIONS_DIR="$PARQUET_DIR/positions_dedup"
  else
    POSITIONS_DIR="$PARQUET_DIR/positions"
  fi
  run python scripts/compute_features.py \
    --parquet-dir "$PARQUET_DIR" \
    --output "$ENRICHED_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S0.5 — Data Validation
# ═══════════════════════════════════════════════════════════════════════
if should_run "S0.5"; then
  log "=== S0.5: Data Validation ==="
  run python scripts/validate_data.py \
    --parquet-dir "$PARQUET_DIR" \
    --enriched "$ENRICHED_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S0.6 — Position Hashing
# ═══════════════════════════════════════════════════════════════════════
if should_run "S0.6"; then
  log "=== S0.6: Position Hashing ==="
  run python scripts/compute_position_hashes.py \
    --parquet-dir "$PARQUET_DIR" \
    --output "$PARQUET_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S0.7 — Trajectory Graph
# ═══════════════════════════════════════════════════════════════════════
if should_run "S0.7"; then
  log "=== S0.7: Trajectory Graph ==="
  run python scripts/build_trajectory_graph.py \
    --parquet-dir "$PARQUET_DIR" \
    --output "$PARQUET_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.1 — Descriptive Statistics
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.1"; then
  log "=== S1.1: Descriptive Statistics ==="
  run python scripts/descriptive_stats.py \
    --parquet-dir "$PARQUET_DIR" \
    --enriched "$ENRICHED_DIR" \
    --output "$STATS_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.2 — Feature-Error Correlation
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.2"; then
  log "=== S1.2: Correlation Analysis ==="
  run python scripts/correlation_analysis.py \
    --enriched "$ENRICHED_DIR" \
    --parquet-dir "$PARQUET_DIR" \
    --output "$STATS_DIR" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.3 — Position Clustering
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.3"; then
  log "=== S1.3: Position Clustering ==="
  run python scripts/cluster_positions.py \
    --enriched "$ENRICHED_DIR" \
    --output "$CLUSTERS_DIR" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.4 — Anomaly Detection
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.4"; then
  log "=== S1.4: Anomaly Detection ==="
  run python scripts/detect_anomalies.py \
    --enriched "$ENRICHED_DIR" \
    --clusters "$CLUSTERS_DIR" \
    --output "${OUTPUT_DIR}/anomalies" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.5 — Volatility Analysis
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.5"; then
  log "=== S1.5: Volatility Analysis ==="
  run python scripts/analyze_volatility.py \
    --enriched "$ENRICHED_DIR" \
    --output "${OUTPUT_DIR}/volatility" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.6 — Dice Analysis
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.6"; then
  log "=== S1.6: Dice Analysis ==="
  run python scripts/analyze_dice.py \
    --enriched "$ENRICHED_DIR" \
    --output "${OUTPUT_DIR}/dice" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.7 — Temporal Analysis
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.7"; then
  log "=== S1.7: Temporal Analysis ==="
  run python scripts/analyze_temporal.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "${OUTPUT_DIR}/temporal" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# S1.8 — Graph Topology
# ═══════════════════════════════════════════════════════════════════════
if should_run "S1.8"; then
  log "=== S1.8: Graph Topology ==="
  run python scripts/analyze_graph_topology.py \
    --graph-dir "$PARQUET_DIR" \
    --parquet-dir "$PARQUET_DIR" \
    --clusters-dir "$CLUSTERS_DIR" \
    --output "${OUTPUT_DIR}/graph_topology"
fi

# ═══════════════════════════════════════════════════════════════════════
# S2.1 — Player Profiles
# ═══════════════════════════════════════════════════════════════════════
if should_run "S2.1"; then
  log "=== S2.1: Player Profiles ==="
  run python scripts/analyze_player_profiles.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "$PROFILES_DIR" \
    --sample 10000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S2.2 — Player Clustering
# ═══════════════════════════════════════════════════════════════════════
if should_run "S2.2"; then
  log "=== S2.2: Player Clustering ==="
  run python scripts/cluster_players.py \
    --profiles "${PROFILES_DIR}/player_profiles.parquet" \
    --output "$PROFILES_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S2.3 — Player Ranking
# ═══════════════════════════════════════════════════════════════════════
if should_run "S2.3"; then
  log "=== S2.3: Player Ranking ==="
  run python scripts/rank_players.py \
    --profiles "${PROFILES_DIR}/player_profiles.parquet" \
    --parquet "$PARQUET_DIR" \
    --output "$PROFILES_DIR"
fi

# ═══════════════════════════════════════════════════════════════════════
# S2.4 — Strengths/Weaknesses
# ═══════════════════════════════════════════════════════════════════════
if should_run "S2.4"; then
  log "=== S2.4: Strengths & Weaknesses ==="
  run python scripts/analyze_strengths_weaknesses.py \
    --enriched "$ENRICHED_DIR" \
    --clusters "${CLUSTERS_DIR}/clusters_checker.parquet" \
    --parquet "$PARQUET_DIR" \
    --profiles "${PROFILES_DIR}/player_profiles.parquet" \
    --output "$PROFILES_DIR" \
    --sample 5000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.1 — Cube Error Heatmap
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.1"; then
  log "=== S3.1: Cube Error Heatmap ==="
  run python scripts/analyze_cube_heatmap.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "$CUBE_DIR" \
    --sample 2000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.2 — MET Verification
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.2"; then
  log "=== S3.2: MET Verification ==="
  run python scripts/verify_met.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "$CUBE_DIR" \
    --sample 5000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.3 — Cube Equity Thresholds
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.3"; then
  log "=== S3.3: Cube Equity Thresholds ==="
  run python scripts/compute_cube_thresholds.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "$CUBE_DIR" \
    --sample 2000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.4 — Position Heuristics
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.4"; then
  log "=== S3.4: Position Heuristics ==="
  run python scripts/extract_heuristics.py \
    --enriched "$ENRICHED_DIR" \
    --clusters "${CLUSTERS_DIR}/clusters_checker.parquet" \
    --output "$CUBE_DIR" \
    --sample 1000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.5 — Gammon Impact
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.5"; then
  log "=== S3.5: Gammon Impact ==="
  run python scripts/analyze_gammon_impact.py \
    --enriched "$ENRICHED_DIR" \
    --parquet "$PARQUET_DIR" \
    --output "$CUBE_DIR" \
    --sample 3000000
fi

# ═══════════════════════════════════════════════════════════════════════
# S3.6 — Cube Predictive Model
# ═══════════════════════════════════════════════════════════════════════
if should_run "S3.6"; then
  log "=== S3.6: Cube Predictive Model ==="
  run python scripts/train_cube_model.py \
    --enriched "$ENRICHED_DIR" \
    --output "$CUBE_DIR" \
    --thresholds "${CUBE_DIR}/cube_thresholds.csv" \
    --sample 500000
fi

# ═══════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════
log "=== Pipeline complete ==="
log "Disk free: $(disk_free) GB"
log "Output summary:"
du -sh "$PARQUET_DIR" "$ENRICHED_DIR" "$CLUSTERS_DIR" "$PROFILES_DIR" \
      "$STATS_DIR" "$CUBE_DIR" "${OUTPUT_DIR}/anomalies" \
      "${OUTPUT_DIR}/volatility" "${OUTPUT_DIR}/dice" \
      "${OUTPUT_DIR}/temporal" "${OUTPUT_DIR}/graph_topology" 2>/dev/null || true
