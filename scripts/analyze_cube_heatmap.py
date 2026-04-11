#!/usr/bin/env python3
"""
S3.1 — Cube Error × Away Score Heatmap

Map the score zones where cube errors are maximal. Aggregates cube
decision errors per (away_p1, away_p2) pair and by error sub-type
(missed double, wrong take, wrong pass). Produces per-match-length
breakdowns and identifies "hot spots" — score pairs with above-average
error rates.

Analyses
--------
  1. Global error heatmap  : avg cube error per (away_p1, away_p2) cell
  2. Error-type breakdown  : missed_double / wrong_take / wrong_pass rates
  3. Per-match-length      : separate grids for 5/7/9/11/13-pt matches
  4. Hot spots             : cells where error > global_mean + 1 std
  5. Asymmetry check       : compare error when p1 vs p2 owns the cube

Outputs
-------
  <output>/cube_heatmap_global.csv        (away_p1, away_p2, n, avg_error, ...)
  <output>/cube_heatmap_by_length.csv     same, split by match_length
  <output>/cube_hotspots.csv              filtered to hot-spot cells only
  <output>/cube_error_types.csv           missed_double/wrong_take/wrong_pass rates
  <output>/cube_heatmap_report.txt        text report with ASCII grid

Usage
-----
  python scripts/analyze_cube_heatmap.py \\
      --enriched  data/parquet/positions_enriched \\
      --parquet   data/parquet \\
      --output    data/cube_analysis \\
      [--sample 2000000] [--max-away 15]
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_N_CELL = 20          # minimum cube decisions per cell to report it
HOTSPOT_Z  = 1.0         # hot spot: error > mean + hotspot_z * std


def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cube_positions(enriched_dir: str, parquet_dir: str,
                         sample: int) -> pl.DataFrame:
    """Load cube decisions from positions_enriched, joined with match_length."""
    want = [
        "position_id", "game_id", "match_id",
        "decision_type", "move_played_error",
        "eval_equity",
        "cube_action_played", "cube_action_optimal",
        "score_away_p1", "score_away_p2",
    ]

    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    frames, total = [], 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols = [c for c in want if c in probe.columns]
            df = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "cube")
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No cube decisions found in enriched data")

    cube = pl.concat(frames, how="diagonal")
    if len(cube) > sample:
        cube = cube.sample(n=sample, seed=42)

    # Join match_length from matches.parquet
    matches_path = Path(parquet_dir) / "matches.parquet"
    if matches_path.exists() and "match_id" in cube.columns:
        matches = pl.read_parquet(matches_path, columns=["match_id", "match_length"])
        cube = cube.join(matches, on="match_id", how="left")

    # Normalise cube action strings to lowercase
    for col in ["cube_action_played", "cube_action_optimal"]:
        if col in cube.columns:
            cube = cube.with_columns(
                pl.col(col).cast(pl.String).str.to_lowercase().alias(col)
            )

    return cube


# ---------------------------------------------------------------------------
# Error-type flags
# ---------------------------------------------------------------------------

def add_error_type_flags(df: pl.DataFrame) -> pl.DataFrame:
    """Add boolean columns for each cube error sub-type."""
    has_actions = ("cube_action_played" in df.columns and
                   "cube_action_optimal" in df.columns)
    if not has_actions:
        return df.with_columns([
            pl.lit(None).cast(pl.Boolean).alias("is_missed_double"),
            pl.lit(None).cast(pl.Boolean).alias("is_wrong_take"),
            pl.lit(None).cast(pl.Boolean).alias("is_wrong_pass"),
        ])

    played  = pl.col("cube_action_played")
    optimal = pl.col("cube_action_optimal")

    return df.with_columns([
        # Missed double: should have doubled but didn't
        (
            optimal.str.contains("double") & ~optimal.str.contains("no")
            & (played.str.contains("no_double") | played.str.contains("no double"))
        ).alias("is_missed_double"),
        # Wrong take: should have passed but took
        (
            (optimal == "pass") & (played == "take")
        ).alias("is_wrong_take"),
        # Wrong pass: should have taken but passed
        (
            (optimal == "take") & (played == "pass")
        ).alias("is_wrong_pass"),
    ])


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def agg_heatmap(df: pl.DataFrame, min_n: int = MIN_N_CELL) -> pl.DataFrame:
    """Aggregate cube metrics per (away_p1, away_p2) cell."""
    if "score_away_p1" not in df.columns or "score_away_p2" not in df.columns:
        return pl.DataFrame()

    agg_exprs = [
        pl.len().alias("n"),
        pl.col("move_played_error").mean().alias("avg_error"),
        pl.col("move_played_error").median().alias("median_error"),
        pl.col("move_played_error").std().alias("std_error"),
        (pl.col("move_played_error") > 0.080).mean().alias("blunder_rate"),
    ]
    if "eval_equity" in df.columns:
        agg_exprs.append(pl.col("eval_equity").mean().alias("avg_equity"))

    error_flags = [f for f in ["is_missed_double", "is_wrong_take", "is_wrong_pass"]
                   if f in df.columns]
    for flag in error_flags:
        col = flag.replace("is_", "") + "_rate"
        agg_exprs.append(pl.col(flag).cast(pl.Float32).mean().alias(col))

    # Cube error rate = any wrong action (fallback when move_played_error is null)
    if error_flags:
        agg_exprs.append(
            pl.any_horizontal([pl.col(f) for f in error_flags])
            .cast(pl.Float32).mean().alias("cube_error_rate")
        )

    result = (
        df.group_by(["score_away_p1", "score_away_p2"])
        .agg(agg_exprs)
        .filter(pl.col("n") >= min_n)
        .sort(["score_away_p1", "score_away_p2"])
    )
    return result


def add_hotspot_flag(heatmap: pl.DataFrame) -> pl.DataFrame:
    """Add is_hotspot column: True when avg_error > mean + HOTSPOT_Z * std."""
    if heatmap.is_empty() or "avg_error" not in heatmap.columns:
        return heatmap
    global_mean = heatmap["avg_error"].mean()
    global_std  = heatmap["avg_error"].std()
    if global_std is None or global_std == 0:
        return heatmap.with_columns(pl.lit(False).alias("is_hotspot"))
    threshold = global_mean + HOTSPOT_Z * global_std
    return heatmap.with_columns(
        (pl.col("avg_error") >= threshold).alias("is_hotspot")
    )


# ---------------------------------------------------------------------------
# ASCII grid rendering
# ---------------------------------------------------------------------------

def render_ascii_grid(heatmap: pl.DataFrame, max_away: int,
                       value_col: str = "avg_error",
                       title: str = "Avg cube error") -> str:
    """
    Render an (away_p1 × away_p2) grid as an ASCII table.
    Rows = away_p1 (1..max_away), columns = away_p2 (1..max_away).
    Cells with no data show '  .  '.
    """
    if heatmap.is_empty():
        return "(no data)\n"

    # Index by (p1, p2) → value
    cell: dict[tuple[int, int], float] = {}
    for row in heatmap.iter_rows(named=True):
        p1 = row.get("score_away_p1")
        p2 = row.get("score_away_p2")
        v  = row.get(value_col)
        if p1 is not None and p2 is not None and v is not None:
            cell[(int(p1), int(p2))] = float(v)

    if not cell:
        return "(no data)\n"

    actual_max = min(max_away, max(max(k) for k in cell))

    lines = [f"\n  {title}  (rows=away_p1, cols=away_p2, 1=best)\n"]
    # Header row
    header = "  away_p2 →  " + "".join(f"{p2:>7}" for p2 in range(1, actual_max + 1))
    lines.append(header)
    lines.append("  away_p1")
    lines.append("  " + "─" * (12 + 7 * actual_max))

    for p1 in range(1, actual_max + 1):
        row_str = f"  {p1:>8}  │"
        for p2 in range(1, actual_max + 1):
            v = cell.get((p1, p2))
            if v is None:
                row_str += "    .  "
            else:
                row_str += f" {v:>5.3f} "
        lines.append(row_str)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(heatmap: pl.DataFrame, hotspots: pl.DataFrame,
                  heatmap_by_length: pl.DataFrame,
                  error_types: pl.DataFrame,
                  max_away: int, output_path: Path,
                  n_total: int) -> None:
    lines = [
        "S3.1 — Cube Error × Away Score Heatmap",
        "=" * 64, "",
        f"Total cube decisions analysed : {n_total:,}",
        f"Cells with >= {MIN_N_CELL} decisions    : {len(heatmap):,}",
        "",
    ]

    # Global stats
    if not heatmap.is_empty():
        gmean = heatmap["avg_error"].mean()
        gmax  = heatmap["avg_error"].max()
        lines.append(f"Global avg cube error : {gmean:.4f}")
        lines.append(f"Max cell avg error    : {gmax:.4f}")
        lines.append("")

    # ASCII grid — global
    lines.append(render_ascii_grid(heatmap, max_away,
                                   value_col="avg_error",
                                   title="Avg cube error (global)"))

    # Hot spots
    if not hotspots.is_empty():
        lines.append("─" * 64)
        lines.append(f"Hot spots (error > mean + {HOTSPOT_Z}σ) — {len(hotspots)} cells\n")
        lines.append(f"  {'away_p1':>8}  {'away_p2':>8}  {'n':>8}  "
                     f"{'avg_err':>8}  {'blunder%':>9}")
        lines.append("  " + "-" * 46)
        for row in hotspots.sort("avg_error", descending=True).iter_rows(named=True):
            bl = (row.get("blunder_rate") or 0) * 100
            lines.append(f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                          f"{row['n']:>8,}  {row['avg_error']:>8.4f}  {bl:>8.1f}%")
        lines.append("")

    # Error types
    if not error_types.is_empty():
        lines.append("─" * 64)
        lines.append("Error-Type Breakdown per Score Cell\n")
        has_md = "missed_double_rate" in error_types.columns
        has_wt = "wrong_take_rate" in error_types.columns
        has_wp = "wrong_pass_rate" in error_types.columns

        if has_md:
            lines.append(render_ascii_grid(error_types, max_away,
                                           value_col="missed_double_rate",
                                           title="Missed double rate"))
        if has_wt:
            lines.append(render_ascii_grid(error_types, max_away,
                                           value_col="wrong_take_rate",
                                           title="Wrong take rate"))
        if has_wp:
            lines.append(render_ascii_grid(error_types, max_away,
                                           value_col="wrong_pass_rate",
                                           title="Wrong pass rate"))

    # Per-match-length summary
    if not heatmap_by_length.is_empty() and "match_length" in heatmap_by_length.columns:
        lines.append("─" * 64)
        lines.append("Per-Match-Length Summary\n")
        for ml in sorted(heatmap_by_length["match_length"].unique().to_list()):
            sub = heatmap_by_length.filter(pl.col("match_length") == ml)
            if sub.is_empty():
                continue
            mean_err = sub["avg_error"].mean()
            n_cells  = len(sub)
            n_pos    = sub["n"].sum()
            lines.append(f"  {ml:>2}-pt  cells={n_cells:>4}  "
                          f"positions={n_pos:>8,}  mean_error={mean_err:.4f}")

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="S3.1 — Cube Error × Away Score Heatmap")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir (matches.parquet)")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=2_000_000,
                    help="Max cube rows to load (default: 2000000)")
    ap.add_argument("--max-away", type=int, default=15,
                    help="Max away score to show in grids (default: 15)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  S3.1 — Cube Error × Away Score Heatmap")
    print("=" * 64)
    print(f"  enriched  : {args.enriched}")
    print(f"  parquet   : {args.parquet}")
    print(f"  output    : {output_dir}")
    print(f"  sample    : {args.sample:,}")
    print(f"  max-away  : {args.max_away}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading cube decisions")
    cube = load_cube_positions(args.enriched, args.parquet, args.sample)
    print(f"  {len(cube):,} cube decisions loaded ({time.time()-t0:.1f}s)")

    # Score range
    if "score_away_p1" in cube.columns:
        p1_max = int(cube["score_away_p1"].max() or 0)
        p2_max = int(cube["score_away_p2"].max() or 0)
        print(f"  Away score range: p1 1–{p1_max}, p2 1–{p2_max}")

    ml_dist = pl.DataFrame()
    if "match_length" in cube.columns:
        ml_dist = (cube.group_by("match_length")
                   .agg(pl.len().alias("n"))
                   .sort("match_length"))
        print(f"\n  Match-length distribution:")
        for row in ml_dist.iter_rows(named=True):
            print(f"    {row['match_length']:>3}-pt : {row['n']:>10,}")

    # Add error-type flags
    cube = add_error_type_flags(cube)

    # ------------------------------------------------------------------
    # 1. Global heatmap
    # ------------------------------------------------------------------
    section("1. Global error heatmap")
    heatmap = agg_heatmap(cube)
    # BMAB cube decisions have no numeric move_played_error — fall back to cube_error_rate
    if (not heatmap.is_empty()
            and "avg_error" in heatmap.columns
            and heatmap["avg_error"].null_count() == len(heatmap)
            and "cube_error_rate" in heatmap.columns):
        heatmap = heatmap.with_columns(pl.col("cube_error_rate").alias("avg_error"))
    heatmap = add_hotspot_flag(heatmap)
    print(f"  {len(heatmap):,} cells (away_p1 × away_p2) with >= {MIN_N_CELL} decisions")

    if not heatmap.is_empty():
        gmean = heatmap["avg_error"].mean()
        gmax  = heatmap["avg_error"].max()
        if gmean is not None:
            print(f"  Global mean cube error : {gmean:.4f}")
        if gmax is not None:
            print(f"  Max cell avg error     : {gmax:.4f}")

    # ------------------------------------------------------------------
    # 2. Hot spots
    # ------------------------------------------------------------------
    section("2. Hot spots")
    hotspots = heatmap.filter(pl.col("is_hotspot")) if not heatmap.is_empty() else pl.DataFrame()
    print(f"  {len(hotspots):,} hot-spot cells (error > mean + {HOTSPOT_Z}σ)")
    if not hotspots.is_empty():
        print(f"\n  {'away_p1':>8}  {'away_p2':>8}  {'n':>8}  "
              f"{'avg_err':>8}  {'blunder%':>9}")
        print("  " + "-" * 48)
        for row in hotspots.sort("avg_error", descending=True).head(15).iter_rows(named=True):
            bl = (row.get("blunder_rate") or 0) * 100
            print(f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                  f"{row['n']:>8,}  {row['avg_error']:>8.4f}  {bl:>8.1f}%")

    # ------------------------------------------------------------------
    # 3. Error-type breakdown (per cell)
    # ------------------------------------------------------------------
    section("3. Error-type breakdown")
    has_type_cols = any(c in cube.columns for c in
                        ["is_missed_double", "is_wrong_take", "is_wrong_pass"])
    error_types = pl.DataFrame()
    if has_type_cols:
        error_types = agg_heatmap(cube)
        type_cols = [c for c in ["missed_double_rate", "wrong_take_rate", "wrong_pass_rate"]
                     if c in error_types.columns]
        if type_cols:
            for col in type_cols:
                mean_val = error_types[col].drop_nulls().mean()
                if mean_val is not None:
                    print(f"  Population mean {col:<26} : {mean_val:.4f}")
        else:
            print("  [SKIP] cube_action_played/optimal columns not available")
    else:
        print("  [SKIP] cube_action_played/optimal columns not available")

    # ------------------------------------------------------------------
    # 4. Per-match-length breakdown
    # ------------------------------------------------------------------
    section("4. Per-match-length heatmaps")
    heatmap_by_length = pl.DataFrame()
    if "match_length" in cube.columns:
        frames = []
        for ml in sorted(cube["match_length"].drop_nulls().unique().to_list()):
            sub = cube.filter(pl.col("match_length") == ml)
            if len(sub) < MIN_N_CELL * 4:
                continue
            h = agg_heatmap(sub, min_n=10)
            if h.is_empty():
                continue
            h = h.with_columns(pl.lit(ml).cast(pl.Int16).alias("match_length"))
            frames.append(h)
            mean_e = h["avg_error"].mean()
            print(f"  {ml:>2}-pt : {len(h):>4} cells, mean error={mean_e:.4f}")
        if frames:
            heatmap_by_length = pl.concat(frames, how="diagonal")
    else:
        print("  [SKIP] match_length not available")

    # ------------------------------------------------------------------
    # 5. Asymmetry check (p1 cube owner vs p2 cube owner)
    # ------------------------------------------------------------------
    section("5. Score asymmetry (p1 side vs p2 side)")
    if not heatmap.is_empty():
        # Compare symmetric pairs: (p1=a, p2=b) vs (p1=b, p2=a)
        hm_dict = {(r["score_away_p1"], r["score_away_p2"]): r["avg_error"]
                   for r in heatmap.iter_rows(named=True)}
        diffs = []
        for (p1, p2), err in hm_dict.items():
            if p1 != p2:
                mirror = hm_dict.get((p2, p1))
                if mirror is not None:
                    diffs.append(abs(err - mirror))
        if diffs:
            import statistics
            print(f"  Mean |error(p1,p2) - error(p2,p1)| : {statistics.mean(diffs):.4f}")
            print(f"  Max asymmetry : {max(diffs):.4f}")
            print("  (Low values → error patterns are symmetric by score position)")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    if not heatmap.is_empty():
        p = output_dir / "cube_heatmap_global.csv"
        heatmap.write_csv(p)
        print(f"  → {p}  ({len(heatmap):,} rows)")

    if not hotspots.is_empty():
        p = output_dir / "cube_hotspots.csv"
        hotspots.write_csv(p)
        print(f"  → {p}  ({len(hotspots):,} rows)")

    if not error_types.is_empty():
        p = output_dir / "cube_error_types.csv"
        error_types.write_csv(p)
        print(f"  → {p}  ({len(error_types):,} rows)")

    if not heatmap_by_length.is_empty():
        p = output_dir / "cube_heatmap_by_length.csv"
        heatmap_by_length.write_csv(p)
        print(f"  → {p}  ({len(heatmap_by_length):,} rows)")

    report_path = output_dir / "cube_heatmap_report.txt"
    write_report(heatmap, hotspots, heatmap_by_length, error_types,
                 args.max_away, report_path, len(cube))
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*64}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
