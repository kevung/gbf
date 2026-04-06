#!/usr/bin/env python3
"""
S1.6 — Dice Structure Analysis
Explore the relationship between dice rolled, position structure,
and decision quality.

Analyses:
  1. Mean error per dice combination (21 unordered pairs)
  2. Doubles vs non-doubles: error and candidate count
  3. Dice × game phase interaction
  4. Dice × structure: error by dice on high-gammon vs low-gammon positions
  5. High-pip vs low-pip dice combos (movement potential)
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

PHASE_LABELS = {0: "contact", 1: "race", 2: "bearoff"}


def dice_combo(dice: list | None) -> str | None:
    """Return canonical unordered dice label, e.g. [6,1] → '61'."""
    if dice is None or len(dice) != 2:
        return None
    a, b = sorted([int(dice[0]), int(dice[1])], reverse=True)
    return f"{a}{b}"


def is_double(dice: list | None) -> bool | None:
    if dice is None or len(dice) != 2:
        return None
    return int(dice[0]) == int(dice[1])


def dice_pips(dice: list | None) -> int | None:
    """Total pips moved = 2×each die (4× for doubles)."""
    if dice is None or len(dice) != 2:
        return None
    a, b = int(dice[0]), int(dice[1])
    if a == b:
        return a * 4
    return a + b


def load_checker(enriched_dir: str, sample: int) -> pl.DataFrame:
    paths = list(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    want = list(dict.fromkeys([
        "position_id", "decision_type", "dice",
        "move_played_error", "eval_equity", "eval_win",
        "match_phase", "gammon_threat", "gammon_risk",
        "pip_count_p1", "pip_count_p2",
        "num_blots_p1", "num_blots_p2",
        "num_points_made_p1", "num_points_made_p2",
        "score_away_p1", "score_away_p2",
    ]))

    frames = []
    total = 0
    for p in sorted(paths):
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols = [c for c in want if c in probe.columns]
            df = pl.read_parquet(p, columns=cols)
        except Exception:
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "checker")
        if "dice" in df.columns:
            df = df.filter(pl.col("dice").is_not_null())
        if "move_played_error" in df.columns:
            df = df.filter(pl.col("move_played_error").is_not_null())
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        return pl.DataFrame()
    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def main():
    ap = argparse.ArgumentParser(description="S1.6 — Dice Structure Analysis")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory")
    ap.add_argument("--output", default="data/dice",
                    help="Output directory for CSV files")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max checker rows to load (default: 500000)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.6 — Dice Structure Analysis")
    print("=" * 60)
    print(f"  enriched : {args.enriched}")
    print(f"  output   : {output_dir}")

    t0 = time.time()
    df = load_checker(args.enriched, args.sample)
    if df.is_empty():
        sys.exit("No checker data with dice found")
    print(f"  Loaded {len(df):,} checker rows ({time.time()-t0:.1f}s)")

    # Derive dice features
    df = df.with_columns(
        pl.col("dice").map_elements(dice_combo, return_dtype=pl.Utf8).alias("combo"),
        pl.col("dice").map_elements(is_double, return_dtype=pl.Boolean).alias("is_double"),
        pl.col("dice").map_elements(dice_pips, return_dtype=pl.Int32).alias("total_pips"),
    )

    # 1. Error by dice combination (21 unordered pairs)
    section("Mean Error per Dice Combination (top/bottom 10)")
    combo_stats = (
        df.filter(pl.col("combo").is_not_null())
        .group_by("combo")
        .agg([
            pl.len().alias("count"),
            pl.col("move_played_error").mean().alias("mean_error"),
            pl.col("move_played_error").median().alias("median_error"),
            (pl.col("move_played_error") >= 0.025).mean().alias("nontrivial_rate"),
            (pl.col("move_played_error") >= 0.100).mean().alias("blunder_rate"),
        ])
        .sort("mean_error", descending=True)
    )
    print(f"  {'Combo':>6} {'N':>6} {'MeanErr':>9} {'Nontrivial%':>12} {'Blunder%':>9}")
    print("  " + "-" * 47)
    all_combos = combo_stats.to_dicts()
    for row in all_combos[:10]:
        nt = row["nontrivial_rate"] * 100
        br = row["blunder_rate"] * 100
        print(f"  {row['combo']:>6} {row['count']:>6,} {row['mean_error']:>9.4f} "
              f"{nt:>11.1f}% {br:>8.1f}%")
    print("  ...")
    for row in all_combos[-5:]:
        nt = row["nontrivial_rate"] * 100
        br = row["blunder_rate"] * 100
        print(f"  {row['combo']:>6} {row['count']:>6,} {row['mean_error']:>9.4f} "
              f"{nt:>11.1f}% {br:>8.1f}%")
    combo_stats.write_csv(output_dir / "error_by_dice_combo.csv")
    print(f"  → {output_dir / 'error_by_dice_combo.csv'} ({len(combo_stats)} combos)")

    # 2. Doubles vs non-doubles
    section("Doubles vs Non-Doubles")
    double_stats = (
        df.filter(pl.col("is_double").is_not_null())
        .group_by("is_double")
        .agg([
            pl.len().alias("count"),
            pl.col("move_played_error").mean().alias("mean_error"),
            pl.col("move_played_error").median().alias("median_error"),
            (pl.col("move_played_error") >= 0.025).mean().alias("nontrivial_rate"),
            (pl.col("move_played_error") >= 0.100).mean().alias("blunder_rate"),
        ])
        .sort("is_double")
    )
    for row in double_stats.iter_rows(named=True):
        label = "doubles" if row["is_double"] else "non-doubles"
        nt = row["nontrivial_rate"] * 100
        br = row["blunder_rate"] * 100
        print(f"  {label:<15} N={row['count']:>8,}  mean={row['mean_error']:.4f}  "
              f"nontrivial={nt:.1f}%  blunder={br:.1f}%")
    double_stats.write_csv(output_dir / "doubles_vs_nondoubles.csv")

    # 3. Dice × game phase interaction
    if "match_phase" in df.columns:
        section("Dice × Game Phase")
        phase_double = (
            df.filter(pl.col("is_double").is_not_null() & pl.col("match_phase").is_not_null())
            .with_columns(
                pl.col("match_phase").cast(pl.Int32).map_elements(
                    lambda x: PHASE_LABELS.get(x, f"phase{x}"), return_dtype=pl.Utf8
                ).alias("phase_label")
            )
            .group_by(["phase_label", "is_double"])
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                (pl.col("move_played_error") >= 0.025).mean().alias("nontrivial_rate"),
            ])
            .sort(["phase_label", "is_double"])
        )
        print(f"  {'Phase':<12} {'Type':<13} {'N':>7} {'MeanErr':>9} {'Nontrivial%':>12}")
        print("  " + "-" * 57)
        for row in phase_double.iter_rows(named=True):
            dtype = "doubles" if row["is_double"] else "non-doubles"
            nt = row["nontrivial_rate"] * 100
            print(f"  {row['phase_label']:<12} {dtype:<13} {row['count']:>7,} "
                  f"{row['mean_error']:>9.4f} {nt:>11.1f}%")
        phase_double.write_csv(output_dir / "dice_by_phase.csv")

    # 4. Dice movement potential × error
    section("Error by Total Pips Moved")
    pip_stats = (
        df.filter(pl.col("total_pips").is_not_null())
        .group_by("total_pips")
        .agg([
            pl.len().alias("count"),
            pl.col("move_played_error").mean().alias("mean_error"),
            (pl.col("move_played_error") >= 0.025).mean().alias("nontrivial_rate"),
        ])
        .sort("total_pips")
    )
    print(f"  {'TotalPips':>10} {'N':>7} {'MeanErr':>9} {'Nontrivial%':>12}")
    print("  " + "-" * 43)
    for row in pip_stats.iter_rows(named=True):
        nt = row["nontrivial_rate"] * 100
        print(f"  {row['total_pips']:>10} {row['count']:>7,} "
              f"{row['mean_error']:>9.4f} {nt:>11.1f}%")
    pip_stats.write_csv(output_dir / "error_by_dice_pips.csv")

    # 5. Dice × gammon threat interaction
    if "gammon_threat" in df.columns:
        section("Doubles Error by Gammon Threat")
        gammon_double = (
            df.filter(pl.col("is_double").is_not_null() & pl.col("gammon_threat").is_not_null())
            .with_columns(
                (pl.col("gammon_threat") >= 0.25).alias("high_gammon")
            )
            .group_by(["is_double", "high_gammon"])
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
            ])
            .sort(["high_gammon", "is_double"])
        )
        print(f"  {'Type':<15} {'HighGammon':>11} {'N':>7} {'MeanErr':>9}")
        print("  " + "-" * 47)
        for row in gammon_double.iter_rows(named=True):
            dtype = "doubles" if row["is_double"] else "non-doubles"
            hg = "yes" if row["high_gammon"] else "no"
            print(f"  {dtype:<15} {hg:>11} {row['count']:>7,} {row['mean_error']:>9.4f}")
        gammon_double.write_csv(output_dir / "dice_by_gammon.csv")

    print(f"\n{'='*60}")
    print(f"  Done in {time.time()-t0:.1f}s — CSVs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
