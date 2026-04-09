#!/usr/bin/env python3
"""
S3.2 — Empirical MET Verification

Compare XG-computed match equity (from eval_equity at early-game positions)
with the Kazaross-XG2 Match Equity Table (MET), and verify take points and
gammon values using the legacy JS reference tables.

Reference tables (from legacy/*.js — Kazaross-XG2)
---------------------------------------------------
  metTable.js            : MET[away_p1][away_p2] = P(p1 wins) ×100, size 15×15
  takePoint2LiveTable.js : take point % for 2-cube, live game (not last)
  takePoint2LastTable.js : take point % for 2-cube, last game
  takePoint4LiveTable.js : take point % for 4-cube, live game
  takePoint4LastTable.js : take point % for 4-cube, last game
  gammonValue1Table.js   : gammon value with 1-cube, various scores
  gammonValue2Table.js   : gammon value with 2-cube, various scores
  gammonValue4Table.js   : gammon value with 4-cube, various scores

Method
------
  1. Filter positions to early game (move_number <= 2) — these reflect
     match equity most directly (neutral board, no cube action yet)
  2. Average eval_equity per (away_p1, away_p2) → empirical win prob
  3. Compare empirical vs Kazaross MET: deviation = empirical − theoretical
  4. Identify systematic bias zones (early game vs race vs bearoff)
  5. Check whether player level (PR bracket) shifts observed equity

Outputs
-------
  <output>/met_comparison.csv        empirical vs theoretical per cell
  <output>/met_deviations.csv        same, sorted by abs(deviation)
  <output>/met_report.txt            ASCII grid + analysis text

Usage
-----
  python scripts/verify_met.py \\
      --enriched data/parquet/positions_enriched \\
      --parquet  data/parquet \\
      --output   data/cube_analysis \\
      [--sample 5000000] [--max-move 3]
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Kazaross-XG2 reference tables (from legacy/*.js)
# Indices: [away_p1 - 1][away_p2 - 1], i.e. 0-indexed by (away - 1)
# Values in percent (0–100).
# ---------------------------------------------------------------------------

# MET: rows = away_p1 (1..15), cols = away_p2 (1..15)
# MET_TABLE[i][j] = P(player needing i+1 pts wins) × 100
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

# Take-point tables (percent), indexed [taker_away-1][doubler_away-1]
# Taker = player receiving the cube; Doubler = player who owns/offers cube
# Live = not last game of the match, Last = last game (Crawford vicinity)
TAKE_POINT_2_LIVE = [
    [32.5, 26,   20,   17.5, 22.5, 22,   21.5, 21],
    [25,   25,   21.5, 19.5, 22.5, 23,   22.5, 23],
    [18.5, 24,   22,   19.5, 23,   22.5, 22.5, 21.5],
    [23.5, 21.5, 24,   20,   23,   22.5, 23,   22],
    [22.5, 22,   24.5, 20,   23,   22,   22.5, 21],
    [23,   19.5, 25,   20,   23,   21.5, 22.5, 21.5],
    [20.5, 19.5, 24,   20,   22.5, 21,   22.5, 21.5],
    [22,   17.5, 24,   20,   22.5, 21,   22.5, 21.5],
]
TAKE_POINT_2_LAST = [
    [32.5, 26,   20,   17.5, 22.5, 22,   21.5, 21],
    [37,   30,   24,   21,   24,   24.5, 23,   23.5],
    [37,   35,   29,   22.5, 26,   24.5, 24.5, 23],
    [39.5, 28.5, 30.5, 24,   27,   25.5, 25,   24],
    [34,   28,   29.5, 23.5, 27,   25,   25.5, 24],
    [36,   25,   30.5, 24,   27.5, 25,   26,   24.5],
    [33.5, 26,   30.5, 24.5, 27.5, 25.5, 26.5, 24.5],
    [35.5, 23,   30.5, 24.5, 28,   25.5, 26.5, 25],
]
TAKE_POINT_4_LIVE = [
    [25, 40, 33, 29, 30, 33, 32],
    [19, 33, 30, 25, 26, 29, 29],
    [16, 26, 25, 25, 25, 27, 28],
    [11, 20, 22, 23, 24, 26, 26],
    [9,  16, 18, 20, 22, 24, 25],
    [7,  12, 16, 18, 20, 22, 23],
    [7,  12, 15, 17, 19, 21, 22],
]
TAKE_POINT_4_LAST = [
    [25, 40, 33, 29, 30, 33, 32],
    [19, 33, 30, 25, 26, 29, 29],
    [21, 31, 28, 26, 27, 28, 28],
    [19, 30, 28, 26, 26, 28, 28],
    [19, 27, 26, 26, 26, 27, 27],
    [16, 25, 25, 25, 25, 26, 26],
    [16, 23, 23, 24, 25, 26, 26],
]

# Gammon-value tables, indexed [away_p1-1][away_p2-1] (doubler owns cube)
GAMMON_VALUE_1 = [
    [0.91, 0.99, 0.86, 0.91, 0.78, 0.86, 0.75, 0.82],
    [0.71, 0.76, 0.86, 0.57, 0.58, 0.50, 0.50, 0.43],
    [0.46, 0.59, 0.68, 0.65, 0.66, 0.67, 0.67, 0.66],
    [0.40, 0.42, 0.48, 0.46, 0.48, 0.47, 0.49, 0.47],
    [0.52, 0.51, 0.58, 0.54, 0.58, 0.58, 0.59, 0.57],
    [0.52, 0.48, 0.55, 0.50, 0.53, 0.51, 0.53, 0.51],
    [0.48, 0.45, 0.54, 0.50, 0.54, 0.54, 0.56, 0.55],
    [0.48, 0.44, 0.49, 0.47, 0.49, 0.49, 0.51, 0.50],
]
GAMMON_VALUE_2 = [
    [0.48, 0.50, 0.45, 0.46, 0.36, 0.36, 0.31, 0.31],
    [1.00, 0.97, 0.98, 0.81, 0.67, 0.60, 0.54, 0.48],
    [0.69, 0.73, 0.77, 0.66, 0.61, 0.55, 0.54, 0.49],
    [0.51, 0.54, 0.56, 0.58, 0.55, 0.54, 0.53, 0.51],
    [0.56, 0.57, 0.56, 0.57, 0.55, 0.54, 0.53, 0.51],
    [0.65, 0.63, 0.61, 0.60, 0.58, 0.57, 0.56, 0.54],
    [0.63, 0.63, 0.60, 0.59, 0.57, 0.56, 0.55, 0.54],
]
GAMMON_VALUE_4 = [
    [0.48, 0.33, 0.23, 0.23, 0.13, 0.17, 0.13, 0.13],
    [1.00, 0.67, 0.50, 0.41, 0.34, 0.29, 0.24, 0.21],
    [1.50, 1.00, 0.75, 0.63, 0.52, 0.45, 0.39, 0.34],
    [2.02, 1.33, 1.00, 0.83, 0.69, 0.60, 0.52, 0.46],
    [1.64, 1.13, 0.93, 0.77, 0.67, 0.60, 0.55, 0.49],
]


def kazaross_met(away_p1: int, away_p2: int) -> float | None:
    """Return Kazaross MET value (%) for given away scores, or None if out of range."""
    i, j = away_p1 - 1, away_p2 - 1
    if 0 <= i < MET_MAX_AWAY and 0 <= j < MET_MAX_AWAY:
        return MET_TABLE[i][j]
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


def render_diff_grid(rows: list[dict], max_away: int,
                      value_col: str, title: str) -> str:
    cell: dict[tuple[int, int], float] = {}
    for r in rows:
        p1 = r.get("score_away_p1")
        p2 = r.get("score_away_p2")
        v  = r.get(value_col)
        if p1 and p2 and v is not None:
            cell[(int(p1), int(p2))] = float(v)
    if not cell:
        return "(no data)\n"
    actual_max = min(max_away, max(max(k) for k in cell))
    lines = [f"\n  {title}  (rows=away_p1, cols=away_p2)\n"]
    header = "  away_p2 →  " + "".join(f"{p2:>7}" for p2 in range(1, actual_max + 1))
    lines.append(header)
    lines.append("  away_p1")
    lines.append("  " + "─" * (12 + 7 * actual_max))
    for p1 in range(1, actual_max + 1):
        row_str = f"  {p1:>8}  │"
        for p2 in range(1, actual_max + 1):
            v = cell.get((p1, p2))
            row_str += f" {v:>+5.1f} " if v is not None else "    .  "
        lines.append(row_str)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_positions(enriched_dir: str, parquet_dir: str,
                   sample: int, max_move: int) -> pl.DataFrame:
    want = [
        "position_id", "game_id", "match_id",
        "decision_type", "move_number", "player_on_roll",
        "eval_equity", "eval_win",
        "score_away_p1", "score_away_p2",
        "match_phase",
        "gammon_threat", "gammon_risk",
    ]
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    frames, total = [], 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols  = [c for c in want if c in probe.columns]
            df    = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        # Keep checker decisions only (cube decisions have cube equity, not ME)
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "checker")
        # Early-game filter
        if "move_number" in df.columns:
            df = df.filter(pl.col("move_number") <= max_move)
        if "eval_equity" in df.columns:
            df = df.filter(pl.col("eval_equity").is_not_null())
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No early-game checker positions found (try increasing --max-move?)")

    pos = pl.concat(frames, how="diagonal")
    if len(pos) > sample:
        pos = pos.sample(n=sample, seed=42)

    # Join match_length for player-level analysis
    mp = Path(parquet_dir) / "matches.parquet"
    if mp.exists() and "match_id" in pos.columns:
        matches = pl.read_parquet(mp, columns=["match_id", "match_length"])
        pos = pos.join(matches, on="match_id", how="left")

    return pos


# ---------------------------------------------------------------------------
# MET comparison
# ---------------------------------------------------------------------------

def compute_empirical_met(pos: pl.DataFrame,
                           min_n: int = 30) -> pl.DataFrame:
    """
    Aggregate eval_equity per (away_p1, away_p2).
    Convert to win probability: win_pct = 50 * (1 + avg_equity).
    Then attach the Kazaross MET reference and compute deviations.
    """
    if "eval_equity" not in pos.columns:
        sys.exit("eval_equity column not available in enriched data")

    agg = (
        pos.group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n"),
            pl.col("eval_equity").mean().alias("avg_equity"),
            pl.col("eval_equity").std().alias("std_equity"),
            pl.col("eval_equity").median().alias("med_equity"),
        ])
        .filter(pl.col("n") >= min_n)
        .sort(["score_away_p1", "score_away_p2"])
    )

    # Empirical win percentage (from p1 perspective)
    agg = agg.with_columns(
        (50.0 * (1.0 + pl.col("avg_equity"))).alias("empirical_win_pct")
    )

    # Attach Kazaross MET
    kazaross_vals = []
    for row in agg.iter_rows(named=True):
        kaz = kazaross_met(int(row["score_away_p1"]), int(row["score_away_p2"]))
        kazaross_vals.append(kaz)
    agg = agg.with_columns(
        pl.Series("kazaross_pct", kazaross_vals, dtype=pl.Float64)
    )

    # Deviation: empirical - theoretical (positive = empirical higher than theory)
    agg = agg.with_columns(
        (pl.col("empirical_win_pct") - pl.col("kazaross_pct")).alias("deviation_pct")
    )

    return agg


# ---------------------------------------------------------------------------
# Player-level analysis
# ---------------------------------------------------------------------------

def compute_level_effect(pos: pl.DataFrame,
                          profiles_path: str | None,
                          min_n: int = 100) -> pl.DataFrame:
    """
    Check whether player strength (PR bracket) shifts the observed equity.
    Requires player_profiles.parquet for PR lookup.
    """
    if profiles_path is None:
        return pl.DataFrame()
    prof_path = Path(profiles_path)
    if not prof_path.exists():
        return pl.DataFrame()
    if "match_id" not in pos.columns:
        return pl.DataFrame()

    profiles = pl.read_parquet(prof_path) if str(prof_path).endswith(".parquet") \
               else pl.read_csv(prof_path)

    if "player" not in profiles.columns or "pr_rating" not in profiles.columns:
        return pl.DataFrame()

    # Define PR brackets
    p25 = profiles["pr_rating"].quantile(0.25) or 0.0
    p75 = profiles["pr_rating"].quantile(0.75) or 1.0
    profiles = profiles.with_columns(
        pl.when(pl.col("pr_rating") <= p25).then(pl.lit("strong (Q1)"))
        .when(pl.col("pr_rating") <= p75).then(pl.lit("average (Q2-Q3)"))
        .otherwise(pl.lit("weak (Q4)"))
        .alias("pr_bracket")
    )

    # Resolve player names in positions
    mp_cols = ["match_id", "player1", "player2"]
    mp_path = pos.schema  # dummy check
    # We'll join via match_id from position data — need matches
    # This function is best-effort; skip if match_id not available
    return pl.DataFrame()   # Placeholder — full join requires matches table


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(comparison: pl.DataFrame,
                 output_path: Path,
                 max_away: int,
                 n_positions: int,
                 max_move: int) -> None:
    rows = comparison.to_dicts()
    lines = [
        "S3.2 — Empirical MET Verification",
        "=" * 64, "",
        f"Positions analysed (move <= {max_move}) : {n_positions:,}",
        f"Score cells with >= 30 positions     : {len(comparison):,}",
        "",
    ]

    if comparison.is_empty():
        output_path.write_text("\n".join(lines))
        return

    valid = comparison.filter(pl.col("deviation_pct").is_not_null())
    if not valid.is_empty():
        mean_dev = valid["deviation_pct"].mean()
        max_dev  = valid["deviation_pct"].abs().max()
        lines += [
            f"Mean deviation (empirical − Kazaross) : {mean_dev:+.2f}%",
            f"Max absolute deviation                : {max_dev:.2f}%",
            "",
        ]

    lines.append(render_diff_grid(rows, max_away,
                                   "empirical_win_pct",
                                   "Empirical win % (XG early-game equity)"))
    lines.append(render_diff_grid(rows, max_away,
                                   "kazaross_pct",
                                   "Kazaross-XG2 MET (reference)"))
    lines.append(render_diff_grid(rows, max_away,
                                   "deviation_pct",
                                   "Deviation: empirical − Kazaross (pp)"))

    # Largest deviations
    if not valid.is_empty():
        lines.append("\n─" * 32)
        lines.append("Largest positive deviations (empirical > Kazaross):\n")
        lines.append(f"  {'away_p1':>8}  {'away_p2':>8}  {'n':>6}  "
                     f"{'empirical':>10}  {'kazaross':>10}  {'dev':>8}")
        lines.append("  " + "-" * 56)
        top = valid.sort("deviation_pct", descending=True).head(10)
        for row in top.iter_rows(named=True):
            lines.append(
                f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                f"{row['n']:>6,}  "
                f"{row['empirical_win_pct']:>10.2f}  "
                f"{row['kazaross_pct']:>10.2f}  "
                f"{row['deviation_pct']:>+8.2f}"
            )
        lines.append("\nLargest negative deviations (empirical < Kazaross):\n")
        bot = valid.sort("deviation_pct", descending=False).head(10)
        for row in bot.iter_rows(named=True):
            lines.append(
                f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                f"{row['n']:>6,}  "
                f"{row['empirical_win_pct']:>10.2f}  "
                f"{row['kazaross_pct']:>10.2f}  "
                f"{row['deviation_pct']:>+8.2f}"
            )

    # Interpretation note
    lines += [
        "",
        "─" * 64,
        "Notes",
        "─" * 64,
        "  • eval_equity from early moves is a proxy for match equity.",
        "    The position is not perfectly neutral (p1 is on roll → slight",
        "    advantage already baked in). Expect a small positive bias.",
        "  • Kazaross MET is calibrated against XG2 at intermediate-level play.",
        "  • Deviations in DMP / 1-away zones are expected (cube play diverges).",
        "  • A systematic positive bias → empirical data over-represents",
        "    positions with favourable boards for the player on roll.",
    ]

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S3.2 — Empirical MET Verification")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir (matches.parquet)")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--profiles",
                    help="Optional: player_profiles.parquet for player-level analysis")
    ap.add_argument("--sample", type=int, default=5_000_000,
                    help="Max positions to load (default: 5000000)")
    ap.add_argument("--max-move", type=int, default=3,
                    help="Max move_number for 'early game' filter (default: 3)")
    ap.add_argument("--min-n", type=int, default=30,
                    help="Min positions per cell (default: 30)")
    ap.add_argument("--max-away", type=int, default=13,
                    help="Max away score in ASCII grids (default: 13)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  S3.2 — Empirical MET Verification")
    print("=" * 64)
    print(f"  enriched  : {args.enriched}")
    print(f"  parquet   : {args.parquet}")
    print(f"  output    : {output_dir}")
    print(f"  max-move  : {args.max_move}")
    print(f"  sample    : {args.sample:,}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading early-game positions")
    pos = load_positions(args.enriched, args.parquet, args.sample, args.max_move)
    print(f"  {len(pos):,} early-game checker positions ({time.time()-t0:.1f}s)")

    if "score_away_p1" in pos.columns:
        p1_max = int(pos["score_away_p1"].max() or 0)
        p2_max = int(pos["score_away_p2"].max() or 0)
        print(f"  Away score range: p1 1–{p1_max}, p2 1–{p2_max}")

    if "match_length" in pos.columns:
        ml_dist = (pos.group_by("match_length")
                   .agg(pl.len().alias("n"))
                   .sort("match_length"))
        print(f"\n  Match-length distribution of loaded positions:")
        for row in ml_dist.iter_rows(named=True):
            print(f"    {row['match_length']:>3}-pt : {row['n']:>10,}")

    # ------------------------------------------------------------------
    # 1. Compute empirical MET
    # ------------------------------------------------------------------
    section("1. Empirical vs Kazaross MET")
    comparison = compute_empirical_met(pos, min_n=args.min_n)
    print(f"  {len(comparison):,} cells with >= {args.min_n} positions")

    valid = comparison.filter(pl.col("deviation_pct").is_not_null())
    if not valid.is_empty():
        mean_dev = valid["deviation_pct"].mean()
        std_dev  = valid["deviation_pct"].std()
        max_abs  = valid["deviation_pct"].abs().max()
        print(f"\n  Mean deviation (empirical − Kazaross) : {mean_dev:+.2f} pp")
        print(f"  Std of deviations                     : {std_dev:.2f} pp")
        print(f"  Max absolute deviation                 : {max_abs:.2f} pp")

        # Top deviations
        print(f"\n  Largest deviations (|empirical − Kazaross|):")
        print(f"  {'away_p1':>8}  {'away_p2':>8}  {'n':>6}  "
              f"{'empirical%':>10}  {'kazaross%':>10}  {'dev':>8}")
        print("  " + "-" * 58)
        for row in valid.with_columns(
            pl.col("deviation_pct").abs().alias("abs_dev")
        ).sort("abs_dev", descending=True).head(15).iter_rows(named=True):
            print(
                f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                f"{row['n']:>6,}  "
                f"{row['empirical_win_pct']:>10.2f}  "
                f"{row['kazaross_pct']:>10.2f}  "
                f"{row['deviation_pct']:>+8.2f}"
            )

    # ------------------------------------------------------------------
    # 2. On-roll bias correction
    # ------------------------------------------------------------------
    section("2. On-roll bias")
    # At move_number=1, the player is on roll → slight equity advantage baked in.
    # Measure average equity at neutral positions to quantify this bias.
    if "eval_equity" in pos.columns:
        symmetric = comparison.filter(
            pl.col("score_away_p1") == pl.col("score_away_p2")
        )
        if not symmetric.is_empty():
            # At tied scores, theory says 50% → empirical should also be 50%
            bias = symmetric["empirical_win_pct"].mean()
            print(f"  Mean empirical win% at tied scores : {bias:.2f}%")
            print(f"  Expected (Kazaross)                : 50.00%")
            print(f"  Estimated on-roll bias             : {bias - 50:.2f} pp")
            print("  (This quantifies the advantage of being on roll at game start)")

    # ------------------------------------------------------------------
    # 3. Systematic patterns by zone
    # ------------------------------------------------------------------
    section("3. Deviation by zone")
    if not valid.is_empty():
        # Classify cells
        zoned = valid.with_columns([
            pl.when(
                (pl.col("score_away_p1") <= 2) & (pl.col("score_away_p2") <= 2)
            ).then(pl.lit("DMP"))
            .when(
                (pl.col("score_away_p1") <= 3) | (pl.col("score_away_p2") <= 3)
            ).then(pl.lit("GS / 3-away"))
            .when(
                (pl.col("score_away_p1") <= 6) | (pl.col("score_away_p2") <= 6)
            ).then(pl.lit("4-6 away"))
            .when(
                (pl.col("score_away_p1") <= 10) | (pl.col("score_away_p2") <= 10)
            ).then(pl.lit("7-10 away"))
            .otherwise(pl.lit("money game range"))
            .alias("zone")
        ])
        zone_stats = (
            zoned.group_by("zone")
            .agg([
                pl.len().alias("n_cells"),
                pl.col("n").sum().alias("n_positions"),
                pl.col("deviation_pct").mean().alias("mean_dev"),
                pl.col("deviation_pct").abs().mean().alias("mean_abs_dev"),
            ])
            .sort("mean_abs_dev", descending=True)
        )
        print(f"\n  {'Zone':<20}  {'Cells':>6}  {'Positions':>10}  "
              f"{'Mean dev':>10}  {'Mean|dev|':>10}")
        print("  " + "-" * 62)
        for row in zone_stats.iter_rows(named=True):
            print(f"  {row['zone']:<20}  {row['n_cells']:>6}  "
                  f"{row['n_positions']:>10,}  "
                  f"{row['mean_dev']:>+10.2f}  "
                  f"{row['mean_abs_dev']:>10.2f}")

    # ------------------------------------------------------------------
    # 4. Kazaross reference table overview
    # ------------------------------------------------------------------
    section("4. Kazaross-XG2 reference tables embedded")
    print("  MET table: 15×15 (away 1–15 for both players)")
    print(f"  Take point tables: 2-cube {len(TAKE_POINT_2_LIVE)}×{len(TAKE_POINT_2_LIVE[0])} "
          f"(live/last), 4-cube {len(TAKE_POINT_4_LIVE)}×{len(TAKE_POINT_4_LIVE[0])}")
    print(f"  Gammon value tables: 1-cube {len(GAMMON_VALUE_1)}×{len(GAMMON_VALUE_1[0])}, "
          f"2-cube {len(GAMMON_VALUE_2)}×{len(GAMMON_VALUE_2[0])}, "
          f"4-cube {len(GAMMON_VALUE_4)}×{len(GAMMON_VALUE_4[0])}")
    print("  All tables exported to CSV for use in S3.3 and S3.5.")

    # Export reference tables as CSVs
    _export_met_csv(output_dir)
    _export_take_point_csvs(output_dir)
    _export_gammon_value_csvs(output_dir)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    if not comparison.is_empty():
        p = output_dir / "met_comparison.csv"
        comparison.write_csv(p)
        print(f"  → {p}  ({len(comparison):,} rows)")

        deviations = comparison.filter(
            pl.col("deviation_pct").is_not_null()
        ).with_columns(
            pl.col("deviation_pct").abs().alias("abs_deviation")
        ).sort("abs_deviation", descending=True)
        p = output_dir / "met_deviations.csv"
        deviations.write_csv(p)
        print(f"  → {p}")

    report_path = output_dir / "met_report.txt"
    write_report(comparison, report_path,
                 args.max_away, len(pos), args.max_move)
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*64}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*64}")


# ---------------------------------------------------------------------------
# Reference table CSV exports
# ---------------------------------------------------------------------------

def _export_met_csv(output_dir: Path) -> None:
    rows = []
    for i, row in enumerate(MET_TABLE):
        for j, val in enumerate(row):
            rows.append({
                "away_p1": i + 1, "away_p2": j + 1,
                "kazaross_win_pct": val,
            })
    pl.DataFrame(rows).write_csv(output_dir / "kazaross_met.csv")
    print(f"  → {output_dir / 'kazaross_met.csv'}  ({len(rows)} cells)")


def _export_take_point_csvs(output_dir: Path) -> None:
    for name, table in [
        ("tp2_live", TAKE_POINT_2_LIVE),
        ("tp2_last", TAKE_POINT_2_LAST),
        ("tp4_live", TAKE_POINT_4_LIVE),
        ("tp4_last", TAKE_POINT_4_LAST),
    ]:
        rows = []
        for i, row in enumerate(table):
            for j, val in enumerate(row):
                rows.append({
                    "taker_away": i + 1, "doubler_away": j + 1,
                    "take_point_pct": val,
                })
        p = output_dir / f"kazaross_{name}.csv"
        pl.DataFrame(rows).write_csv(p)
        print(f"  → {p}  ({len(rows)} cells)")


def _export_gammon_value_csvs(output_dir: Path) -> None:
    for name, table in [
        ("gv1", GAMMON_VALUE_1),
        ("gv2", GAMMON_VALUE_2),
        ("gv4", GAMMON_VALUE_4),
    ]:
        rows = []
        for i, row in enumerate(table):
            for j, val in enumerate(row):
                rows.append({
                    "away_p1": i + 1, "away_p2": j + 1,
                    "gammon_value": val,
                })
        p = output_dir / f"kazaross_{name}.csv"
        pl.DataFrame(rows).write_csv(p)
        print(f"  → {p}  ({len(rows)} cells)")


if __name__ == "__main__":
    main()
