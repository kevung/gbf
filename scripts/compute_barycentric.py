#!/usr/bin/env python3
"""
RG.1 — Compute Barycentric Coordinates in MWC Space

For each position in the enriched Parquet data, compute the score-space
barycenter of the six possible match outcomes (win/gammon/backgammon,
lose/gammon-loss/backgammon-loss), weighted by XG outcome probabilities.
Each destination score maps through the Kazaross-XG2 MET to produce
a cubeless MWC.  The cubeful-cubeless gap is derived from eval_equity.

See docs/tasks/reverse-gammon.md for the mathematical framework.

Outputs
-------
  <output>/barycentric.parquet        per-position barycentric coordinates
  <output>/barycentric_aggregates.csv per-score-cell aggregated statistics
  <output>/barycentric_report.txt     summary report

Usage
-----
  python scripts/compute_barycentric.py \\
      --enriched data/parquet/positions_enriched \\
      --output data/barycentric \\
      [--sample 5000000] [--away-max 15]
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Kazaross-XG2 Match Equity Table (from scripts/verify_met.py)
# MET_TABLE[i][j] = P(player needing i+1 pts wins) * 100
# ---------------------------------------------------------------------------

MET_TABLE = [
    [50,   67.7, 75.1, 81.4, 84.2, 88.7, 90.7, 93.3, 94.4, 95.9, 96.6, 97.6, 98,   98.5, 98.8],
    [32.3, 50,   59.9, 66.9, 74.4, 79.9, 84.2, 87.5, 90.2, 92.3, 93.9, 95.2, 96.2, 97.1, 97.7],
    [24.9, 40.1, 50,   57.6, 64.8, 71.1, 76.2, 80.5, 84,   87.1, 89.4, 91.5, 93.1, 94.4, 95.5],
    [18.6, 33.1, 42.9, 50,   57.7, 64.3, 69.9, 74.6, 78.8, 82.4, 85.4, 87.9, 90,   91.8, 93.3],
    [15.8, 25.6, 35.2, 42.3, 50,   56.6, 62.6, 67.8, 72.5, 76.7, 80.3, 83.4, 86,   88.3, 90.2],
    [11.3, 20.1, 28.9, 35.7, 43.4, 50,   56.3, 61.6, 66.8, 71.3, 75.3, 78.9, 82,   84.7, 87.0],
    [9.3,  15.8, 23.8, 30.1, 37.4, 43.7, 50,   55.5, 60.8, 65.6, 70.0, 73.9, 77.4, 80.5, 83.3],
    [6.8,  12.5, 19.5, 25.4, 32.2, 38.4, 44.5, 50,   55.4, 60.4, 65.0, 69.1, 72.9, 76.4, 79.4],
    [5.6,  9.8,  16.0, 21.2, 27.5, 33.2, 39.1, 44.6, 50,   55.0, 59.8, 64.1, 68.2, 71.9, 75.3],
    [4.1,  7.7,  12.9, 17.6, 23.3, 28.7, 34.4, 39.6, 45.0, 50,   54.9, 59.3, 63.6, 67.5, 71.1],
    [3.4,  6.1,  10.6, 14.6, 19.7, 24.7, 30.0, 35.0, 40.2, 45.1, 50,   54.6, 58.9, 63.0, 66.8],
    [2.4,  4.8,  8.5,  12.1, 16.6, 21.1, 26.1, 30.9, 35.9, 40.7, 45.4, 50,   54.4, 58.6, 62.5],
    [2.0,  3.8,  6.9,  10.0, 14.0, 18.0, 22.6, 27.1, 31.8, 36.4, 41.1, 45.6, 50,   54.2, 58.3],
    [1.5,  2.9,  5.6,  8.2,  11.7, 15.3, 19.5, 23.6, 28.1, 32.5, 37.0, 41.4, 45.8, 50,   54.1],
    [1.2,  2.3,  4.5,  6.7,  9.8,  13.0, 16.7, 20.6, 24.7, 28.9, 33.2, 37.5, 41.7, 45.9, 50],
]
MET_MAX_AWAY = len(MET_TABLE)  # 15


def build_met_lookup() -> pl.DataFrame:
    """Build a MET lookup DataFrame covering away 0..15 for both players.

    Convention: MET(0, b) = 100% (match won), MET(a, 0) = 0% (match lost),
    MET(0, 0) = 50% (degenerate).
    """
    rows: list[dict] = []
    # Standard 15x15 grid
    for i in range(MET_MAX_AWAY):
        for j in range(MET_MAX_AWAY):
            rows.append({
                "dest_a": i + 1, "dest_b": j + 1,
                "met_mwc": MET_TABLE[i][j] / 100.0,
            })
    # Edge: a = 0 (we won the match) for all b
    for b in range(0, MET_MAX_AWAY + 1):
        rows.append({"dest_a": 0, "dest_b": b, "met_mwc": 1.0})
    # Edge: b = 0 (opponent won the match) for a >= 1
    for a in range(1, MET_MAX_AWAY + 1):
        rows.append({"dest_a": a, "dest_b": 0, "met_mwc": 0.0})
    return pl.DataFrame(rows).with_columns(
        pl.col("dest_a").cast(pl.Int16),
        pl.col("dest_b").cast(pl.Int16),
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

REQUIRED_COLS = [
    "position_id",
    "eval_win", "eval_win_g", "eval_win_bg",
    "eval_lose_g", "eval_lose_bg",
    "eval_equity",
    "score_away_p1", "score_away_p2",
    "cube_value",
]
OPTIONAL_COLS = [
    "crawford", "match_phase", "gammon_threat", "gammon_risk",
    "decision_type",
]


def load_positions(enriched_dir: str, sample: int,
                   away_max: int) -> pl.DataFrame:
    """Load enriched parquet, filter to valid rows within MET range."""
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    # Probe columns available
    probe = pl.read_parquet(paths[0], n_rows=1)
    available = set(probe.columns)

    missing = [c for c in REQUIRED_COLS if c not in available]
    if missing:
        sys.exit(f"Missing required columns: {missing}")

    cols = REQUIRED_COLS + [c for c in OPTIONAL_COLS if c in available]

    frames, total = [], 0
    for p in paths:
        try:
            df = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        # Filter: valid eval data and away scores within MET range
        df = df.filter(
            pl.col("eval_win").is_not_null()
            & pl.col("eval_equity").is_not_null()
            & (pl.col("score_away_p1") >= 1)
            & (pl.col("score_away_p1") <= away_max)
            & (pl.col("score_away_p2") >= 1)
            & (pl.col("score_away_p2") <= away_max)
        )
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No valid positions found")

    pos = pl.concat(frames, how="diagonal")
    if len(pos) > sample:
        pos = pos.sample(n=sample, seed=42)
    return pos


# ---------------------------------------------------------------------------
# Barycentric computation
# ---------------------------------------------------------------------------

def compute_barycentric(pos: pl.DataFrame,
                        met: pl.DataFrame) -> pl.DataFrame:
    """Compute barycentric coordinates and cubeless MWC for each position.

    Returns a DataFrame with original identifiers plus computed columns.
    """
    # Cube value: treat 0 (centered) as C=1
    cube = pl.when(pl.col("cube_value") <= 0).then(1).otherwise(pl.col("cube_value"))

    a = pl.col("score_away_p1")
    b = pl.col("score_away_p2")

    # --- 6 outcome probabilities ---
    p_wbg = pl.col("eval_win_bg")
    p_wg  = pl.col("eval_win_g") - pl.col("eval_win_bg")
    p_ws  = pl.col("eval_win") - pl.col("eval_win_g")
    p_ls  = (1.0 - pl.col("eval_win")) - pl.col("eval_lose_g")
    p_lg  = pl.col("eval_lose_g") - pl.col("eval_lose_bg")
    p_lbg = pl.col("eval_lose_bg")

    # --- 6 destination scores (clamped at 0) ---
    # Wins: our away unchanged, opponent away decreases
    dest_a_1 = a;  dest_b_1 = (b - 3 * cube).clip(lower_bound=0)
    dest_a_2 = a;  dest_b_2 = (b - 2 * cube).clip(lower_bound=0)
    dest_a_3 = a;  dest_b_3 = (b - 1 * cube).clip(lower_bound=0)
    # Losses: opponent away unchanged, our away decreases
    dest_a_4 = (a - 1 * cube).clip(lower_bound=0);  dest_b_4 = b
    dest_a_5 = (a - 2 * cube).clip(lower_bound=0);  dest_b_5 = b
    dest_a_6 = (a - 3 * cube).clip(lower_bound=0);  dest_b_6 = b

    # Add destination columns
    df = pos.with_columns([
        cube.alias("cube_eff"),
        # Probabilities
        p_wbg.alias("p1"), p_wg.alias("p2"), p_ws.alias("p3"),
        p_ls.alias("p4"),  p_lg.alias("p5"), p_lbg.alias("p6"),
        # Destination a
        dest_a_1.cast(pl.Int16).alias("da1"), dest_a_2.cast(pl.Int16).alias("da2"),
        dest_a_3.cast(pl.Int16).alias("da3"), dest_a_4.cast(pl.Int16).alias("da4"),
        dest_a_5.cast(pl.Int16).alias("da5"), dest_a_6.cast(pl.Int16).alias("da6"),
        # Destination b
        dest_b_1.cast(pl.Int16).alias("db1"), dest_b_2.cast(pl.Int16).alias("db2"),
        dest_b_3.cast(pl.Int16).alias("db3"), dest_b_4.cast(pl.Int16).alias("db4"),
        dest_b_5.cast(pl.Int16).alias("db5"), dest_b_6.cast(pl.Int16).alias("db6"),
    ])

    # --- MET lookups via joins ---
    for i in range(1, 7):
        da_col, db_col = f"da{i}", f"db{i}"
        met_col = f"met{i}"
        met_renamed = met.rename({
            "dest_a": da_col, "dest_b": db_col, "met_mwc": met_col,
        })
        df = df.join(met_renamed, on=[da_col, db_col], how="left")

    # --- Compute barycenter and MWC ---
    bary_a = sum(pl.col(f"p{i}") * pl.col(f"da{i}").cast(pl.Float64) for i in range(1, 7))
    bary_b = sum(pl.col(f"p{i}") * pl.col(f"db{i}").cast(pl.Float64) for i in range(1, 7))
    cubeless_mwc = sum(pl.col(f"p{i}") * pl.col(f"met{i}") for i in range(1, 7))

    df = df.with_columns([
        bary_a.alias("bary_a"),
        bary_b.alias("bary_b"),
        (bary_a - pl.col("score_away_p1").cast(pl.Float64)).alias("disp_a"),
        (bary_b - pl.col("score_away_p2").cast(pl.Float64)).alias("disp_b"),
        cubeless_mwc.alias("cubeless_mwc"),
        (2.0 * cubeless_mwc - 1.0).alias("cubeless_equity"),
        pl.col("eval_equity").alias("cubeful_equity"),
    ])

    df = df.with_columns([
        (pl.col("eval_equity") - pl.col("cubeless_equity")).alias("cube_gap"),
        (pl.col("disp_a").pow(2) + pl.col("disp_b").pow(2)).sqrt().alias("disp_magnitude"),
    ])

    # Select output columns
    output_cols = [
        "position_id", "score_away_p1", "score_away_p2", "cube_eff",
        "bary_a", "bary_b", "disp_a", "disp_b", "disp_magnitude",
        "cubeless_mwc", "cubeless_equity", "cubeful_equity", "cube_gap",
    ]
    for c in ["crawford", "match_phase", "gammon_threat", "gammon_risk",
              "decision_type"]:
        if c in df.columns:
            output_cols.append(c)

    return df.select(output_cols)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_per_cell(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate barycentric statistics per (away_p1, away_p2) score cell."""
    agg = (
        df.group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n"),
            pl.col("bary_a").mean().alias("mean_bary_a"),
            pl.col("bary_b").mean().alias("mean_bary_b"),
            pl.col("bary_a").std().alias("std_bary_a"),
            pl.col("bary_b").std().alias("std_bary_b"),
            pl.col("disp_a").mean().alias("mean_disp_a"),
            pl.col("disp_b").mean().alias("mean_disp_b"),
            pl.col("disp_magnitude").mean().alias("mean_disp_magnitude"),
            pl.col("disp_magnitude").std().alias("std_disp_magnitude"),
            pl.col("cubeless_mwc").mean().alias("mean_cubeless_mwc"),
            pl.col("cubeless_mwc").std().alias("std_cubeless_mwc"),
            pl.col("cube_gap").mean().alias("mean_cube_gap"),
            pl.col("cube_gap").std().alias("std_cube_gap"),
            pl.col("cubeful_equity").mean().alias("mean_cubeful_equity"),
        ])
        .sort(["score_away_p1", "score_away_p2"])
    )

    # Attach Kazaross reference
    kazaross_vals = []
    for row in agg.iter_rows(named=True):
        a, b = int(row["score_away_p1"]), int(row["score_away_p2"])
        if 1 <= a <= MET_MAX_AWAY and 1 <= b <= MET_MAX_AWAY:
            kazaross_vals.append(MET_TABLE[a - 1][b - 1] / 100.0)
        else:
            kazaross_vals.append(None)
    agg = agg.with_columns(
        pl.Series("kazaross_mwc", kazaross_vals, dtype=pl.Float64)
    )
    return agg


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(agg: pl.DataFrame, output_path: Path,
                 n_positions: int, elapsed: float) -> None:
    """Write a text report summarizing the barycentric computation."""
    lines = [
        "RG.1 — Barycentric Coordinates Report",
        "=" * 60, "",
        f"Positions processed : {n_positions:,}",
        f"Score cells         : {len(agg):,}",
        f"Elapsed             : {elapsed:.1f}s",
        "",
    ]

    if agg.is_empty():
        output_path.write_text("\n".join(lines))
        return

    # Global stats
    lines += [
        "Global displacement statistics:",
        f"  Mean |D|           : {agg['mean_disp_magnitude'].mean():.4f}",
        f"  Mean cube gap      : {agg['mean_cube_gap'].mean():+.4f}",
        "",
    ]

    # Cubeless MWC vs Kazaross
    valid = agg.filter(pl.col("kazaross_mwc").is_not_null())
    if not valid.is_empty():
        dev = (valid["mean_cubeless_mwc"] - valid["kazaross_mwc"])
        lines += [
            "Cubeless MWC vs Kazaross MET:",
            f"  Mean deviation     : {dev.mean():+.4f}",
            f"  Max |deviation|    : {dev.abs().max():.4f}",
            "",
        ]

    # Top displacement cells
    top = agg.sort("mean_disp_magnitude", descending=True).head(10)
    lines += ["Top 10 cells by displacement magnitude:", ""]
    lines.append(f"  {'away_p1':>8}  {'away_p2':>8}  {'|D|':>8}  "
                 f"{'disp_a':>8}  {'disp_b':>8}  {'MWC':>8}  {'gap':>8}  {'n':>8}")
    lines.append("  " + "-" * 72)
    for row in top.iter_rows(named=True):
        lines.append(
            f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
            f"{row['mean_disp_magnitude']:>8.3f}  "
            f"{row['mean_disp_a']:>+8.3f}  {row['mean_disp_b']:>+8.3f}  "
            f"{row['mean_cubeless_mwc']:>8.3f}  "
            f"{row['mean_cube_gap']:>+8.4f}  "
            f"{row['n']:>8,}"
        )

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="RG.1 — Compute Barycentric Coordinates in MWC Space")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir")
    ap.add_argument("--output", default="data/barycentric",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=5_000_000,
                    help="Max positions to load (default: 5000000)")
    ap.add_argument("--away-max", type=int, default=15,
                    help="Max away score to include (default: 15)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  RG.1 — Barycentric Coordinates in MWC Space")
    print("=" * 60)
    print(f"  enriched : {args.enriched}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,}")
    print(f"  away-max : {args.away_max}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # 1. Build MET lookup
    # ------------------------------------------------------------------
    met = build_met_lookup()
    print(f"\n  MET lookup: {len(met)} rows")

    # ------------------------------------------------------------------
    # 2. Load positions
    # ------------------------------------------------------------------
    print("\n  Loading positions...")
    pos = load_positions(args.enriched, args.sample, args.away_max)
    print(f"  {len(pos):,} positions loaded ({time.time()-t0:.1f}s)")

    # Score distribution
    score_dist = (
        pos.group_by(["score_away_p1", "score_away_p2"])
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
    )
    print(f"  {len(score_dist):,} distinct score cells")

    # ------------------------------------------------------------------
    # 3. Compute barycentric coordinates
    # ------------------------------------------------------------------
    print("\n  Computing barycentric coordinates...")
    result = compute_barycentric(pos, met)
    t_compute = time.time() - t0
    print(f"  Done ({t_compute:.1f}s)")

    # Quick sanity
    print(f"\n  Sanity checks:")
    print(f"    bary_a range : [{result['bary_a'].min():.3f}, {result['bary_a'].max():.3f}]")
    print(f"    bary_b range : [{result['bary_b'].min():.3f}, {result['bary_b'].max():.3f}]")
    print(f"    MWC range    : [{result['cubeless_mwc'].min():.4f}, {result['cubeless_mwc'].max():.4f}]")
    print(f"    cube_gap mean: {result['cube_gap'].mean():+.4f}")

    # ------------------------------------------------------------------
    # 4. Aggregate per score cell
    # ------------------------------------------------------------------
    print("\n  Aggregating per score cell...")
    agg = aggregate_per_cell(result)

    # ------------------------------------------------------------------
    # 5. Save outputs
    # ------------------------------------------------------------------
    print("\n  Saving outputs...")

    p = output_dir / "barycentric.parquet"
    result.write_parquet(p)
    print(f"    -> {p} ({len(result):,} rows)")

    p = output_dir / "barycentric_aggregates.csv"
    agg.write_csv(p)
    print(f"    -> {p} ({len(agg):,} cells)")

    elapsed = time.time() - t0
    report_path = output_dir / "barycentric_report.txt"
    write_report(agg, report_path, len(result), elapsed)
    print(f"    -> {report_path}")

    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
