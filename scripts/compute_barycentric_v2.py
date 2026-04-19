#!/usr/bin/env python3
"""
BE.1 — Perspective-Corrected Barycentric Coordinates + Trajectory Keys

Fixes the perspective bug in compute_barycentric.py (RG.1): that script
uses a=score_away_p1 / b=score_away_p2 as "our/opponent" but eval_win
is P(player_on_roll wins). When player_on_roll==2 the six-outcome weights
are applied to the wrong score axes, yielding a mis-oriented cubeless MWC
for ~50% of rows.

This script:
  1. Computes on-roll-POV barycenter (correct axis assignment).
  2. Publishes a canonical P1-POV block (flip axes + invert MWC when
     on_roll==2) so trajectories read smoothly across both players.
  3. Joins games.parquet to add match_id and game_number.
  4. Sorts output by (match_id, game_number, move_number) for efficient
     trajectory queries.

Outputs
-------
  <output>/barycentric_v2.parquet
  <output>/barycentric_v2_report.txt

Usage
-----
  python scripts/compute_barycentric_v2.py \\
      --enriched data/parquet/positions_enriched \\
      --games    data/parquet/games.parquet \\
      [--output  data/barycentric] \\
      [--away-max 15] \\
      [--limit-partitions N] \\
      [--sample N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import polars as pl


# ---------------------------------------------------------------------------
# Kazaross-XG2 MET (identical copy from compute_barycentric.py — scripts are
# kept independent by convention).
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
    """MET lookup: (dest_a, dest_b) → met_mwc, covering 0..15 × 0..15."""
    rows: list[dict] = []
    for i in range(MET_MAX_AWAY):
        for j in range(MET_MAX_AWAY):
            rows.append({"dest_a": i + 1, "dest_b": j + 1,
                         "met_mwc": MET_TABLE[i][j] / 100.0})
    for b in range(0, MET_MAX_AWAY + 1):
        rows.append({"dest_a": 0, "dest_b": b, "met_mwc": 1.0})
    for a in range(1, MET_MAX_AWAY + 1):
        rows.append({"dest_a": a, "dest_b": 0, "met_mwc": 0.0})
    return pl.DataFrame(rows).with_columns(
        pl.col("dest_a").cast(pl.Int16),
        pl.col("dest_b").cast(pl.Int16),
    )


# ---------------------------------------------------------------------------
# Column lists
# ---------------------------------------------------------------------------

REQUIRED_COLS = [
    "position_id", "game_id", "move_number", "player_on_roll",
    "eval_win", "eval_win_g", "eval_win_bg",
    "eval_lose_g", "eval_lose_bg",
    "eval_equity",
    "score_away_p1", "score_away_p2",
    "cube_value",
    "crawford", "is_post_crawford",
]
OPTIONAL_COLS = [
    "decision_type", "match_phase",
    "gammon_threat", "gammon_risk", "dgr",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_positions(enriched_dir: str, away_max: int,
                   limit_partitions: int | None,
                   sample: int | None) -> pl.DataFrame:
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")
    if limit_partitions:
        paths = paths[:limit_partitions]

    probe = pl.read_parquet(paths[0], n_rows=1)
    available = set(probe.columns)

    missing = [c for c in REQUIRED_COLS if c not in available]
    if missing:
        sys.exit(f"Missing required columns: {missing}")

    cols = REQUIRED_COLS + [c for c in OPTIONAL_COLS if c in available]

    frames = []
    for p in paths:
        try:
            df = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        df = df.filter(
            pl.col("eval_win").is_not_null()
            & pl.col("eval_equity").is_not_null()
            & pl.col("player_on_roll").is_in([1, 2])
            & (pl.col("score_away_p1") >= 1) & (pl.col("score_away_p1") <= away_max)
            & (pl.col("score_away_p2") >= 1) & (pl.col("score_away_p2") <= away_max)
        )
        if df.is_empty():
            continue
        frames.append(df)

    if not frames:
        sys.exit("No valid positions found")

    pos = pl.concat(frames, how="diagonal")
    if sample and len(pos) > sample:
        pos = pos.sample(n=sample, seed=42)
    return pos


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_barycentric_v2(pos: pl.DataFrame,
                           met: pl.DataFrame) -> pl.DataFrame:
    """Compute on-roll-POV and P1-POV barycentric columns."""

    cube_eff = pl.when(pl.col("cube_value") <= 0).then(pl.lit(1)).otherwise(
        pl.col("cube_value")
    ).alias("cube_eff")

    # Perspective-correct our/opp away
    our_away = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("score_away_p1"))
        .otherwise(pl.col("score_away_p2"))
        .alias("our_away")
    )
    opp_away = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("score_away_p2"))
        .otherwise(pl.col("score_away_p1"))
        .alias("opp_away")
    )

    df = pos.with_columns([cube_eff, our_away, opp_away])

    # Six outcome probabilities (from on-roll POV)
    p1 = pl.col("eval_win_bg")
    p2 = pl.col("eval_win_g") - pl.col("eval_win_bg")
    p3 = pl.col("eval_win") - pl.col("eval_win_g")
    p4 = (1.0 - pl.col("eval_win")) - pl.col("eval_lose_g")
    p5 = pl.col("eval_lose_g") - pl.col("eval_lose_bg")
    p6 = pl.col("eval_lose_bg")

    c = pl.col("cube_eff").cast(pl.Int32)
    our = pl.col("our_away").cast(pl.Int32)
    opp = pl.col("opp_away").cast(pl.Int32)

    # Six destination pairs in on-roll frame (our stays for wins, opp stays for losses)
    # Win outcomes: our unchanged, opp decreases
    da1 = our;                  db1 = (opp - 3 * c).clip(lower_bound=0)
    da2 = our;                  db2 = (opp - 2 * c).clip(lower_bound=0)
    da3 = our;                  db3 = (opp - 1 * c).clip(lower_bound=0)
    # Lose outcomes: opp unchanged, our decreases
    da4 = (our - 1 * c).clip(lower_bound=0); db4 = opp
    da5 = (our - 2 * c).clip(lower_bound=0); db5 = opp
    da6 = (our - 3 * c).clip(lower_bound=0); db6 = opp

    df = df.with_columns([
        p1.alias("p1"), p2.alias("p2"), p3.alias("p3"),
        p4.alias("p4"), p5.alias("p5"), p6.alias("p6"),
        da1.cast(pl.Int16).alias("da1"), db1.cast(pl.Int16).alias("db1"),
        da2.cast(pl.Int16).alias("da2"), db2.cast(pl.Int16).alias("db2"),
        da3.cast(pl.Int16).alias("da3"), db3.cast(pl.Int16).alias("db3"),
        da4.cast(pl.Int16).alias("da4"), db4.cast(pl.Int16).alias("db4"),
        da5.cast(pl.Int16).alias("da5"), db5.cast(pl.Int16).alias("db5"),
        da6.cast(pl.Int16).alias("da6"), db6.cast(pl.Int16).alias("db6"),
    ])

    # MET lookups for each destination
    for i in range(1, 7):
        da_col, db_col, met_col = f"da{i}", f"db{i}", f"met{i}"
        met_renamed = met.rename({"dest_a": da_col, "dest_b": db_col,
                                  "met_mwc": met_col})
        df = df.join(met_renamed, on=[da_col, db_col], how="left")

    # On-roll-POV barycenter
    bary_onroll_a = sum(pl.col(f"p{i}") * pl.col(f"da{i}").cast(pl.Float64)
                        for i in range(1, 7))
    bary_onroll_b = sum(pl.col(f"p{i}") * pl.col(f"db{i}").cast(pl.Float64)
                        for i in range(1, 7))
    mwc_onroll = sum(pl.col(f"p{i}") * pl.col(f"met{i}")
                     for i in range(1, 7))

    df = df.with_columns([
        bary_onroll_a.alias("bary_onroll_a"),
        bary_onroll_b.alias("bary_onroll_b"),
        mwc_onroll.alias("cubeless_mwc_onroll"),
        pl.col("eval_equity").alias("cubeful_equity_onroll"),
    ])
    df = df.with_columns([
        (pl.col("bary_onroll_a") - pl.col("our_away").cast(pl.Float64)).alias("disp_onroll_a"),
        (pl.col("bary_onroll_b") - pl.col("opp_away").cast(pl.Float64)).alias("disp_onroll_b"),
    ])

    # P1-POV projection
    # on_roll==1: P1 = on-roll, so P1-POV == on-roll-POV
    # on_roll==2: P1 = off-roll, so axes swap and MWC inverts
    bary_p1_a = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("bary_onroll_a"))
        .otherwise(pl.col("bary_onroll_b"))
    )
    bary_p1_b = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("bary_onroll_b"))
        .otherwise(pl.col("bary_onroll_a"))
    )
    mwc_p1 = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("cubeless_mwc_onroll"))
        .otherwise(1.0 - pl.col("cubeless_mwc_onroll"))
    )
    cubeful_p1 = (
        pl.when(pl.col("player_on_roll") == 1)
        .then(pl.col("eval_equity"))
        .otherwise(-pl.col("eval_equity"))
    )

    df = df.with_columns([
        bary_p1_a.alias("bary_p1_a"),
        bary_p1_b.alias("bary_p1_b"),
        mwc_p1.alias("cubeless_mwc_p1"),
        cubeful_p1.alias("cubeful_equity_p1"),
    ])
    df = df.with_columns([
        (pl.col("bary_p1_a") - pl.col("score_away_p1").cast(pl.Float64)).alias("disp_p1_a"),
        (pl.col("bary_p1_b") - pl.col("score_away_p2").cast(pl.Float64)).alias("disp_p1_b"),
        (2.0 * pl.col("cubeless_mwc_p1") - 1.0).alias("cubeless_equity_p1"),
    ])
    df = df.with_columns([
        (pl.col("disp_p1_a").pow(2) + pl.col("disp_p1_b").pow(2)).sqrt().alias("disp_magnitude_p1"),
        (pl.col("cubeful_equity_p1") - pl.col("cubeless_equity_p1")).alias("cube_gap_p1"),
    ])

    return df


# ---------------------------------------------------------------------------
# Select output columns
# ---------------------------------------------------------------------------

BASE_OUTPUT_COLS = [
    "position_id", "game_id", "move_number", "player_on_roll",
    "score_away_p1", "score_away_p2", "cube_value", "cube_eff",
    "crawford", "is_post_crawford",
    # on-roll block
    "bary_onroll_a", "bary_onroll_b", "disp_onroll_a", "disp_onroll_b",
    "cubeless_mwc_onroll", "cubeful_equity_onroll",
    # P1-POV block
    "bary_p1_a", "bary_p1_b", "disp_p1_a", "disp_p1_b",
    "disp_magnitude_p1", "cubeless_mwc_p1", "cubeless_equity_p1",
    "cubeful_equity_p1", "cube_gap_p1",
]
ANCILLARY_COLS = ["decision_type", "match_phase", "gammon_threat",
                  "gammon_risk", "dgr"]


# ---------------------------------------------------------------------------
# Sanity report
# ---------------------------------------------------------------------------

MET_TABLE_FOR_REPORT = MET_TABLE  # same object, for readability


def write_report(df: pl.DataFrame, output_path: Path,
                 n_positions: int, elapsed: float,
                 away_max: int) -> None:
    lines = [
        "BE.1 — Perspective-Corrected Barycentric Report",
        "=" * 60, "",
        f"Positions processed : {n_positions:,}",
        f"Away-max filter     : {away_max}",
        f"Elapsed             : {elapsed:.1f}s",
        "",
    ]

    # Player on roll distribution
    roll_dist = df.group_by("player_on_roll").agg(pl.len().alias("n")).sort("player_on_roll")
    lines.append("Player on roll distribution:")
    for row in roll_dist.iter_rows(named=True):
        pct = 100.0 * row["n"] / n_positions
        lines.append(f"  player_on_roll={row['player_on_roll']}: "
                     f"{row['n']:>10,}  ({pct:.1f}%)")
    lines.append("")

    # For on_roll==2 rows: check that v1 (if it existed without the fix) would differ
    # We approximate v1 error as |mwc_p1 - cubeless_mwc_onroll| for on_roll==2 rows
    # (because v1 would have used onroll_mwc as if it were P1-POV without flipping)
    roll2 = df.filter(pl.col("player_on_roll") == 2)
    if len(roll2) > 0:
        delta = (roll2["cubeless_mwc_p1"] - roll2["cubeless_mwc_onroll"]).abs()
        lines += [
            "Perspective correction (on_roll==2 rows):",
            f"  Mean |mwc_p1 - mwc_onroll|  : {delta.mean():.4f}",
            f"  Max  |mwc_p1 - mwc_onroll|  : {delta.max():.4f}",
            f"  Rows with |delta| > 0.001    : "
            f"{(delta > 0.001).sum():,}  "
            f"({100.0*(delta > 0.001).sum()/len(roll2):.1f}%)",
            "",
        ]

    # Mean mwc_p1 vs Kazaross MET per cell
    cell_agg = (
        df.group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n"),
            pl.col("cubeless_mwc_p1").mean().alias("mean_mwc_p1"),
        ])
        .sort(["score_away_p1", "score_away_p2"])
    )
    deviations = []
    for row in cell_agg.iter_rows(named=True):
        a, b = int(row["score_away_p1"]), int(row["score_away_p2"])
        if 1 <= a <= MET_MAX_AWAY and 1 <= b <= MET_MAX_AWAY:
            kaz = MET_TABLE_FOR_REPORT[a - 1][b - 1] / 100.0
            dev = row["mean_mwc_p1"] - kaz
            deviations.append((a, b, row["n"], row["mean_mwc_p1"], kaz, dev))

    if deviations:
        devs = [abs(d[5]) for d in deviations]
        mean_dev = sum(d[5] for d in deviations) / len(deviations)
        max_abs_dev = max(devs)
        lines += [
            "Cubeless MWC (P1-POV) vs Kazaross MET:",
            f"  Mean deviation     : {mean_dev:+.4f}",
            f"  Max |deviation|    : {max_abs_dev:.4f}",
            "",
        ]

        # Top 10 cells by abs deviation
        top = sorted(deviations, key=lambda x: abs(x[5]), reverse=True)[:10]
        lines.append("Top 10 cells by |deviation|:")
        lines.append(f"  {'a':>4}  {'b':>4}  {'n':>8}  "
                     f"{'mean_mwc':>10}  {'kazaross':>10}  {'dev':>8}")
        lines.append("  " + "-" * 50)
        for a, b, n, mwc, kaz, dev in top:
            lines.append(f"  {a:>4}  {b:>4}  {n:>8,}  "
                         f"{mwc:>10.4f}  {kaz:>10.4f}  {dev:>+8.4f}")

    output_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="BE.1 — Perspective-Corrected Barycentric + Trajectory Keys")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched parquet dir")
    ap.add_argument("--games", required=True,
                    help="Path to games.parquet")
    ap.add_argument("--output", default="data/barycentric",
                    help="Output directory (default: data/barycentric)")
    ap.add_argument("--away-max", type=int, default=15,
                    help="Max away score to include (default: 15)")
    ap.add_argument("--limit-partitions", type=int, default=None,
                    help="Process only the first N partition files (for testing)")
    ap.add_argument("--sample", type=int, default=None,
                    help="Sub-sample N rows after loading (for quick iteration)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  BE.1 — Perspective-Corrected Barycentric v2")
    print("=" * 60)
    print(f"  enriched  : {args.enriched}")
    print(f"  games     : {args.games}")
    print(f"  output    : {output_dir}")
    print(f"  away-max  : {args.away_max}")
    if args.limit_partitions:
        print(f"  limit-partitions: {args.limit_partitions}")
    if args.sample:
        print(f"  sample    : {args.sample:,}")

    t0 = time.time()

    # 1. MET lookup
    met = build_met_lookup()
    print(f"\n  MET lookup: {len(met)} rows")

    # 2. Load positions
    print("\n  Loading positions...")
    pos = load_positions(args.enriched, args.away_max,
                         args.limit_partitions, args.sample)
    n_positions = len(pos)
    print(f"  {n_positions:,} positions loaded ({time.time()-t0:.1f}s)")

    # 3. Compute barycentric coordinates
    print("\n  Computing barycentric coordinates...")
    df = compute_barycentric_v2(pos, met)
    t_compute = time.time() - t0
    print(f"  Done ({t_compute:.1f}s)")

    # 4. Select output columns
    avail = set(df.columns)
    out_cols = BASE_OUTPUT_COLS + [c for c in ANCILLARY_COLS if c in avail]
    df = df.select(out_cols)

    # 5. Join match_id and game_number from games.parquet
    print("\n  Joining match_id from games.parquet...")
    games = pl.read_parquet(args.games,
                            columns=["game_id", "match_id", "game_number"])
    df = df.join(games, on="game_id", how="left")

    # 6. Sort for efficient trajectory queries
    null_match = df["match_id"].is_null().sum()
    if null_match > 0:
        print(f"  [WARN] {null_match:,} rows with missing match_id "
              "(game_id not found in games.parquet)")

    df = df.sort(["match_id", "game_number", "move_number"],
                 nulls_last=True)

    # 7. Reorder columns: keys first, then match_id / game_number
    key_cols = ["position_id", "game_id", "match_id", "game_number",
                "move_number", "player_on_roll"]
    rest = [c for c in df.columns if c not in key_cols]
    df = df.select(key_cols + rest)

    # 8. Write parquet
    print("\n  Writing output...")
    out_parquet = output_dir / "barycentric_v2.parquet"
    df.write_parquet(out_parquet)
    print(f"    -> {out_parquet} ({len(df):,} rows, "
          f"{out_parquet.stat().st_size / 1e6:.1f} MB)")

    # 9. Sanity report
    elapsed = time.time() - t0
    report_path = output_dir / "barycentric_v2_report.txt"
    write_report(df, report_path, n_positions, elapsed, args.away_max)
    print(f"    -> {report_path}")

    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
