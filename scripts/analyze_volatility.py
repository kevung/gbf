#!/usr/bin/env python3
"""
S1.5 — Position Volatility & Complexity Analysis

Note: the candidates column was dropped in S0.2 to avoid nested-struct
complexity. True volatility (std dev of candidate equities) is therefore
unavailable. This script instead uses move_played_error as a proxy for
decision complexity:
  - error = 0     → trivial decision (one clear best move)
  - error > 0.025 → non-trivial (player found it difficult)
  - error > 0.100 → high-volatility (blunder-level complexity)

Analyses:
  1. Error magnitude distribution by game phase
  2. Non-trivial error rate by pip count bins (game stage complexity)
  3. Error by gammon threat level (gammon-loaded = more complex)
  4. Error by cube leverage (high-stakes = more errors?)
  5. Error by score bracket (DMP / Crawford / money game effect)
  6. High-complexity position profile (top-quartile error positions)
  7. Structural complexity score: features that predict non-trivial decisions
"""

import argparse
import time
import sys
from pathlib import Path

import polars as pl

TINY_THR = 0.010     # error below this → essentially perfect play
SMALL_THR = 0.025    # error above this → non-trivial decision
MEDIUM_THR = 0.050   # medium difficulty
BLUNDER_THR = 0.100  # high-complexity blunder

PHASE_LABELS = {0: "contact", 1: "race", 2: "bearoff"}

FEATURES = [
    "pip_count_p1", "pip_count_p2", "pip_count_diff",
    "num_blots_p1", "num_blots_p2",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "longest_prime_p1", "longest_prime_p2",
    "back_anchor_p1", "num_checkers_back_p1",
    "num_builders_p1", "outfield_blots_p1",
    "num_on_bar_p1", "num_on_bar_p2",
    "gammon_threat", "gammon_risk", "net_gammon",
    "cube_leverage",
    "score_away_p1", "score_away_p2", "score_differential",
    "match_phase",
]


def load_checker(enriched_dir: str, sample: int) -> pl.DataFrame:
    paths = list(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    want = list(dict.fromkeys(FEATURES + [
        "position_id", "decision_type", "move_played_error",
        "eval_equity", "eval_win", "match_phase",
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


def complexity_class(err: float) -> str:
    if err < TINY_THR:
        return "trivial"
    if err < SMALL_THR:
        return "easy"
    if err < MEDIUM_THR:
        return "moderate"
    if err < BLUNDER_THR:
        return "difficult"
    return "very-difficult"


def pip_bin(pip: int) -> str:
    if pip < 50:
        return "<50 (late bearoff)"
    if pip < 100:
        return "50-99 (late race/bearoff)"
    if pip < 130:
        return "100-129 (mid-race)"
    if pip < 160:
        return "130-159 (early race)"
    return "≥160 (opening)"


def gammon_bracket(g: float) -> str:
    if g < 0.10:
        return "<10% (low)"
    if g < 0.25:
        return "10-25% (moderate)"
    if g < 0.40:
        return "25-40% (high)"
    return "≥40% (very high)"


def leverage_bracket(lev: float) -> str:
    if lev < 0.25:
        return "<0.25 (low)"
    if lev < 0.50:
        return "0.25-0.50"
    if lev < 1.0:
        return "0.50-1.00"
    return "≥1.00 (high)"


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def print_table(df: pl.DataFrame, key_col: str, sort_col: str = "mean_error") -> None:
    df = df.sort(sort_col, descending=True)
    hdr = f"  {key_col:<28} {'N':>7} {'MeanErr':>9} {'Nontrivial%':>12} {'BlunderRate%':>13}"
    print(hdr)
    print("  " + "-" * 73)
    for row in df.iter_rows(named=True):
        k = str(row.get(key_col, "?"))
        n = row.get("count", 0)
        me = row.get("mean_error", float("nan"))
        nt = row.get("nontrivial_rate", float("nan")) * 100
        br = row.get("blunder_rate", float("nan")) * 100
        print(f"  {k:<28} {n:>7,} {me:>9.4f} {nt:>11.1f}% {br:>12.1f}%")


def aggregate_by(df: pl.DataFrame, group_col: str) -> pl.DataFrame:
    return (
        df.group_by(group_col)
        .agg([
            pl.len().alias("count"),
            pl.col("move_played_error").mean().alias("mean_error"),
            pl.col("move_played_error").median().alias("median_error"),
            (pl.col("move_played_error") >= SMALL_THR)
            .mean().alias("nontrivial_rate"),
            (pl.col("move_played_error") >= BLUNDER_THR)
            .mean().alias("blunder_rate"),
        ])
    )


def main():
    ap = argparse.ArgumentParser(description="S1.5 — Position Volatility & Complexity")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory")
    ap.add_argument("--output", default="data/volatility",
                    help="Output directory for CSV files")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max rows to load (default: 500000)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.5 — Position Volatility & Complexity Analysis")
    print("=" * 60)
    print(f"  enriched : {args.enriched}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,}")

    t0 = time.time()
    df = load_checker(args.enriched, args.sample)
    if df.is_empty():
        sys.exit("No checker data found")
    print(f"  Loaded {len(df):,} checker rows ({time.time()-t0:.1f}s)")

    # Add derived columns
    df = df.with_columns(
        pl.col("move_played_error").map_elements(
            complexity_class, return_dtype=pl.Utf8
        ).alias("complexity"),
    )

    if "pip_count_p1" in df.columns:
        df = df.with_columns(
            pl.col("pip_count_p1").map_elements(
                pip_bin, return_dtype=pl.Utf8
            ).alias("pip_bin")
        )
    if "gammon_threat" in df.columns:
        df = df.with_columns(
            pl.col("gammon_threat").map_elements(
                gammon_bracket, return_dtype=pl.Utf8
            ).alias("gammon_bracket")
        )
    if "cube_leverage" in df.columns:
        df = df.with_columns(
            pl.col("cube_leverage").map_elements(
                leverage_bracket, return_dtype=pl.Utf8
            ).alias("leverage_bracket")
        )

    # 1. Overall complexity distribution
    section("Overall Complexity Distribution")
    total = len(df)
    complexity_dist = (
        df.group_by("complexity")
        .agg([
            pl.len().alias("count"),
            pl.col("move_played_error").mean().alias("mean_error"),
        ])
        .sort("mean_error")
    )
    for row in complexity_dist.iter_rows(named=True):
        pct = row["count"] / total * 100
        print(f"  {row['complexity']:<16} {row['count']:>8,} ({pct:5.1f}%)  "
              f"mean_error={row['mean_error']:.4f}")
    complexity_dist.write_csv(output_dir / "complexity_distribution.csv")

    # 2. By game phase
    if "match_phase" in df.columns:
        section("Complexity by Game Phase")
        df = df.with_columns(
            pl.col("match_phase").cast(pl.Int32).map_elements(
                lambda x: PHASE_LABELS.get(x, f"phase{x}"), return_dtype=pl.Utf8
            ).alias("phase_label")
        )
        phase_stats = aggregate_by(df, "phase_label")
        print_table(phase_stats, "phase_label")
        phase_stats.write_csv(output_dir / "complexity_by_phase.csv")

    # 3. By pip count bin (on-roll player)
    if "pip_bin" in df.columns:
        section("Complexity by Pip Count (on-roll player)")
        pip_stats = aggregate_by(df, "pip_bin")
        print_table(pip_stats, "pip_bin")
        pip_stats.write_csv(output_dir / "complexity_by_pip.csv")

    # 4. By gammon threat level
    if "gammon_bracket" in df.columns:
        section("Complexity by Gammon Threat Level")
        gammon_stats = aggregate_by(df, "gammon_bracket")
        print_table(gammon_stats, "gammon_bracket")
        gammon_stats.write_csv(output_dir / "complexity_by_gammon.csv")

    # 5. By cube leverage
    if "leverage_bracket" in df.columns:
        section("Complexity by Cube Leverage")
        lev_stats = aggregate_by(df, "leverage_bracket")
        print_table(lev_stats, "leverage_bracket")
        lev_stats.write_csv(output_dir / "complexity_by_leverage.csv")

    # 6. High-complexity position profile
    section("High-Complexity Position Profile (error ≥ 0.050)")
    high = df.filter(pl.col("move_played_error") >= MEDIUM_THR)
    low = df.filter(pl.col("move_played_error") < TINY_THR)
    avail = [f for f in FEATURES if f in df.columns]
    if avail and len(high) > 0 and len(low) > 0:
        high_means = high.select(avail).mean()
        low_means = low.select(avail).mean()
        print(f"\n  {'Feature':<28} {'High-error mean':>16} {'Trivial mean':>13} {'Ratio':>7}")
        print("  " + "-" * 68)
        for feat in avail:
            if feat not in high_means.columns:
                continue
            h_val = high_means[feat][0]
            l_val = low_means[feat][0]
            if h_val is None or l_val is None:
                continue
            ratio = h_val / l_val if abs(l_val) > 0.001 else float("nan")
            print(f"  {feat:<28} {h_val:>16.3f} {l_val:>13.3f} {ratio:>7.2f}")

        # Save profile comparison
        profile_df = pl.DataFrame({
            "feature": avail,
            "high_error_mean": [high.select(f).mean()[f][0] for f in avail
                                 if f in high.columns],
            "trivial_mean": [low.select(f).mean()[f][0] for f in avail
                             if f in low.columns],
        }).filter(pl.col("high_error_mean").is_not_null())
        profile_df.write_csv(output_dir / "high_complexity_profile.csv")
        print(f"\n  → {output_dir / 'high_complexity_profile.csv'}")

    # 7. Error evolution by move number within game
    if "move_number" in df.columns:
        section("Complexity by Move Number (early vs late game)")
        move_stats = (
            df.with_columns(
                (pl.col("move_number") // 5 * 5).alias("move_bin")
            )
            .group_by("move_bin")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
            ])
            .sort("move_bin")
        )
        print(f"  {'Move bin':>10} {'N':>7} {'MeanErr':>9} {'Nontrivial%':>12}")
        print("  " + "-" * 43)
        for row in move_stats.head(20).iter_rows(named=True):
            nt = row["nontrivial_rate"] * 100
            print(f"  {row['move_bin']:>10} {row['count']:>7,} "
                  f"{row['mean_error']:>9.4f} {nt:>11.1f}%")
        move_stats.write_csv(output_dir / "complexity_by_move_number.csv")

    print(f"\n{'='*60}")
    print(f"  Done in {time.time()-t0:.1f}s — CSVs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
