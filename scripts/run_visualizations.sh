#!/usr/bin/env bash
# Run all visualization scripts to generate the complete viz suite.
#
# Usage:
#   ./scripts/run_visualizations.sh [options]
#
# Options:
#   --parquet-dir DIR   Parquet base directory (default: data/parquet)
#   --output-dir DIR    Viz output directory (default: viz)
#   --sample N          Sample size per script (default: 200000)
#   --interactive       Also generate Plotly HTML dashboards
#   --only STAGE        Run only one stage: themes|explorer|positions|stats
#   --themes LIST       Space-separated theme names for position review

set -euo pipefail

PYTHON="${PYTHON:-/home/unger/src/gbf/.venv/bin/python}"
PARQUET_DIR="data/parquet"
OUTPUT_DIR="viz"
SAMPLE=200000
INTERACTIVE=false
ONLY=""
REVIEW_THEMES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --parquet-dir)   PARQUET_DIR="$2"; shift 2 ;;
    --output-dir)    OUTPUT_DIR="$2"; shift 2 ;;
    --sample)        SAMPLE="$2"; shift 2 ;;
    --interactive)   INTERACTIVE=true; shift ;;
    --only)          ONLY="$2"; shift 2 ;;
    --themes)        shift; REVIEW_THEMES=""; while [[ $# -gt 0 && ! "$1" = --* ]]; do REVIEW_THEMES="$REVIEW_THEMES $1"; shift; done ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

ENRICHED="${PARQUET_DIR}/positions_enriched"
THEMES_DIR="${PARQUET_DIR}/position_themes"
CLUSTERS_DIR="data/clusters"
PROFILES_DIR="data/player_profiles"
STATS_DIR="data/stats"

log() { echo "[viz] $(date '+%H:%M:%S') $*"; }

should_run() {
  [[ -z "$ONLY" || "$ONLY" == "$1" ]]
}

# ═══════════════════════════════════════════════════════════════════════
# 1. Theme overview plots
# ═══════════════════════════════════════════════════════════════════════
if should_run "themes" && [[ -d "$THEMES_DIR" ]]; then
  log "=== Theme Visualizations ==="
  $PYTHON scripts/visualize_themes.py \
    --themes "$THEMES_DIR" \
    --enriched "$ENRICHED" \
    --clusters "$CLUSTERS_DIR" \
    --output "${OUTPUT_DIR}/themes" \
    --sample "$SAMPLE"
fi

# ═══════════════════════════════════════════════════════════════════════
# 2. Feature explorer (multiple views)
# ═══════════════════════════════════════════════════════════════════════
if should_run "explorer"; then
  log "=== Feature Explorer — by phase ==="
  $PYTHON scripts/visualize_explorer.py \
    --enriched "$ENRICHED" \
    ${THEMES_DIR:+--themes "$THEMES_DIR"} \
    --clusters "$CLUSTERS_DIR" \
    --output "${OUTPUT_DIR}/explorer/by_phase" \
    --color-by phase \
    --sample "$SAMPLE" \
    $( [[ "$INTERACTIVE" == "true" ]] && echo "--interactive" )

  if [[ -d "$THEMES_DIR" ]]; then
    log "=== Feature Explorer — by theme ==="
    $PYTHON scripts/visualize_explorer.py \
      --enriched "$ENRICHED" \
      --themes "$THEMES_DIR" \
      --clusters "$CLUSTERS_DIR" \
      --output "${OUTPUT_DIR}/explorer/by_theme" \
      --color-by theme \
      --sample "$SAMPLE" \
      $( [[ "$INTERACTIVE" == "true" ]] && echo "--interactive" )
  fi

  if [[ -d "$CLUSTERS_DIR" ]]; then
    log "=== Feature Explorer — by cluster ==="
    $PYTHON scripts/visualize_explorer.py \
      --enriched "$ENRICHED" \
      --clusters "$CLUSTERS_DIR" \
      --output "${OUTPUT_DIR}/explorer/by_cluster" \
      --color-by cluster \
      --sample "$SAMPLE" \
      $( [[ "$INTERACTIVE" == "true" ]] && echo "--interactive" )
  fi

  # Per-phase views.
  for PHASE in contact race bearoff; do
    log "=== Feature Explorer — $PHASE only ==="
    $PYTHON scripts/visualize_explorer.py \
      --enriched "$ENRICHED" \
      ${THEMES_DIR:+--themes "$THEMES_DIR"} \
      --output "${OUTPUT_DIR}/explorer/${PHASE}" \
      --filter-phase "$PHASE" \
      --color-by phase \
      --sample "$SAMPLE"
  done
fi

# ═══════════════════════════════════════════════════════════════════════
# 3. Position browser (per-theme review)
# ═══════════════════════════════════════════════════════════════════════
if should_run "positions" && [[ -d "$THEMES_DIR" ]]; then
  log "=== Position Browser ==="
  THEME_ARGS=""
  if [[ -n "$REVIEW_THEMES" ]]; then
    THEME_ARGS="--only-themes $REVIEW_THEMES"
  fi
  $PYTHON scripts/visualize_positions.py \
    --enriched "$ENRICHED" \
    --themes "$THEMES_DIR" \
    --output "${OUTPUT_DIR}/positions" \
    --sample "$SAMPLE" \
    --per-theme 30 \
    $THEME_ARGS
fi

# ═══════════════════════════════════════════════════════════════════════
# 4. Stats & cluster visualizations
# ═══════════════════════════════════════════════════════════════════════
if should_run "stats"; then
  log "=== Stats & Cluster Visualizations ==="
  $PYTHON scripts/visualize_stats.py \
    --enriched "$ENRICHED" \
    --clusters "$CLUSTERS_DIR" \
    --profiles "$PROFILES_DIR" \
    --stats "$STATS_DIR" \
    --output "${OUTPUT_DIR}/stats" \
    --sample "$SAMPLE"
fi

log "=== All visualizations complete ==="
log "Output tree:"
find "$OUTPUT_DIR" -name "*.png" -o -name "*.html" -o -name "*.csv" | sort | head -80
echo "..."
echo "Total files: $(find "$OUTPUT_DIR" -type f | wc -l)"
