#!/usr/bin/env python3
"""
S1.7 — Temporal & Sequential Analysis

Study how play quality evolves within matches and games: fatigue,
warm-up, post-blunder tilt, post-loss effects, score deficit impact,
and error autocorrelation.

Analyses:
  1. Average error by game number within match (fatigue vs warm-up)
  2. Average error by move number within game (early vs late game)
  3. Post-blunder tilt: does a blunder worsen the next move by same player?
  4. Post-loss effect: does play quality drop after losing a game?
  5. Score deficit effect: when trailing, do players play better or worse?
  6. Error autocorrelation: do errors come in series?

Dependencies: S0.3 (bgdata), S0.4 (enriched features).
Input: positions_enriched + games.parquet
Output: 6 CSV files in --output directory
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

BLUNDER_THR = 0.100   # error ≥ this → blunder
SMALL_THR = 0.025     # non-trivial threshold


def load_enriched(enriched_dir: str, sample: int) -> pl.DataFrame:
    """Load checker decisions from enriched Parquet directory."""
    paths = list(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    want = [
        "position_id", "game_id", "move_number", "player_on_roll",
        "decision_type", "move_played_error",
        "score_away_p1", "score_away_p2", "score_differential",
        "match_phase",
    ]

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


def load_games(parquet_dir: str) -> pl.DataFrame:
    """Load games table with game_number, winner, match_id."""
    games_path = Path(parquet_dir) / "games.parquet"
    if not games_path.exists():
        sys.exit(f"Games parquet not found: {games_path}")
    return pl.read_parquet(games_path, columns=[
        "game_id", "match_id", "game_number", "winner",
    ])


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def main():
    ap = argparse.ArgumentParser(description="S1.7 — Temporal & Sequential Analysis")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet directory (contains games.parquet)")
    ap.add_argument("--output", default="data/temporal",
                    help="Output directory for CSV files")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max checker rows to load (default: 500000)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.7 — Temporal & Sequential Analysis")
    print("=" * 60)
    print(f"  enriched : {args.enriched}")
    print(f"  parquet  : {args.parquet}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,}")

    t0 = time.time()
    pos = load_enriched(args.enriched, args.sample)
    if pos.is_empty():
        sys.exit("No checker data found")
    print(f"  Loaded {len(pos):,} checker rows ({time.time()-t0:.1f}s)")

    games = load_games(args.parquet)
    print(f"  Loaded {len(games):,} games")

    # Join positions ← games to get game_number, match_id, winner
    df = pos.join(games, on="game_id", how="left")
    print(f"  Joined → {len(df):,} rows with game metadata")

    # ──────────────────────────────────────────────────────────
    # 1. Error by game number within match (fatigue vs warm-up)
    # ──────────────────────────────────────────────────────────
    section("1. Error by Game Number (fatigue vs warm-up)")
    if "game_number" in df.columns:
        game_num_stats = (
            df.filter(pl.col("game_number").is_not_null())
            .group_by("game_number")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
                (pl.col("move_played_error") >= BLUNDER_THR)
                .mean().alias("blunder_rate"),
            ])
            .sort("game_number")
        )
        print(f"  {'Game#':>6} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
              f"{'Nontrivial%':>12} {'Blunder%':>9}")
        print("  " + "-" * 60)
        for row in game_num_stats.head(25).iter_rows(named=True):
            nt = row["nontrivial_rate"] * 100
            br = row["blunder_rate"] * 100
            print(f"  {row['game_number']:>6} {row['count']:>8,} "
                  f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                  f"{nt:>11.1f}% {br:>8.1f}%")
        game_num_stats.write_csv(output_dir / "error_by_game_number.csv")
        print(f"  → {output_dir / 'error_by_game_number.csv'}")
    else:
        print("  [SKIP] game_number not available")

    # ──────────────────────────────────────────────────────────
    # 2. Error by move number within game (early vs late)
    # ──────────────────────────────────────────────────────────
    section("2. Error by Move Number (early vs late game)")
    if "move_number" in df.columns:
        # Bin moves: 1-5, 6-10, 11-15, ...
        move_stats = (
            df.with_columns(
                ((pl.col("move_number") - 1) // 5 * 5 + 1).alias("move_bin")
            )
            .group_by("move_bin")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
                (pl.col("move_played_error") >= BLUNDER_THR)
                .mean().alias("blunder_rate"),
            ])
            .sort("move_bin")
        )
        print(f"  {'Moves':>10} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
              f"{'Nontrivial%':>12} {'Blunder%':>9}")
        print("  " + "-" * 64)
        for row in move_stats.head(20).iter_rows(named=True):
            mb = row["move_bin"]
            label = f"{mb}-{mb+4}"
            nt = row["nontrivial_rate"] * 100
            br = row["blunder_rate"] * 100
            print(f"  {label:>10} {row['count']:>8,} "
                  f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                  f"{nt:>11.1f}% {br:>8.1f}%")
        move_stats.write_csv(output_dir / "error_by_move_number.csv")
        print(f"  → {output_dir / 'error_by_move_number.csv'}")
    else:
        print("  [SKIP] move_number not available")

    # ──────────────────────────────────────────────────────────
    # 3. Post-blunder tilt
    # ──────────────────────────────────────────────────────────
    section("3. Post-Blunder Tilt")
    if "move_number" in df.columns and "game_id" in df.columns:
        # Sort by game_id + move_number. Same player's previous move is
        # move_number - 2 (players alternate), same game_id.
        ordered = df.select([
            "game_id", "move_number", "player_on_roll", "move_played_error",
        ]).sort(["game_id", "move_number"])

        # Self-join: for each position, find the previous position by
        # the same player in the same game (move_number - 2).
        prev = ordered.rename({
            "move_played_error": "prev_error",
            "move_number": "prev_move_number",
            "player_on_roll": "prev_player",
        })
        curr = ordered.with_columns(
            (pl.col("move_number") - 2).alias("prev_move_number"),
        )
        tilt_df = curr.join(
            prev, on=["game_id", "prev_move_number"],
            how="inner",
        ).filter(
            pl.col("player_on_roll") == pl.col("prev_player")
        )

        if len(tilt_df) > 0:
            tilt_df = tilt_df.with_columns(
                (pl.col("prev_error") >= BLUNDER_THR).alias("prev_was_blunder"),
            )
            tilt_stats = (
                tilt_df.group_by("prev_was_blunder")
                .agg([
                    pl.len().alias("count"),
                    pl.col("move_played_error").mean().alias("mean_error"),
                    pl.col("move_played_error").median().alias("median_error"),
                    (pl.col("move_played_error") >= SMALL_THR)
                    .mean().alias("nontrivial_rate"),
                    (pl.col("move_played_error") >= BLUNDER_THR)
                    .mean().alias("blunder_rate"),
                ])
                .sort("prev_was_blunder")
            )
            print(f"  {'PrevBlunder':>12} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
                  f"{'Nontrivial%':>12} {'Blunder%':>9}")
            print("  " + "-" * 64)
            for row in tilt_stats.iter_rows(named=True):
                label = "yes" if row["prev_was_blunder"] else "no"
                nt = row["nontrivial_rate"] * 100
                br = row["blunder_rate"] * 100
                print(f"  {label:>12} {row['count']:>8,} "
                      f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                      f"{nt:>11.1f}% {br:>8.1f}%")
            tilt_stats.write_csv(output_dir / "post_blunder_tilt.csv")
            print(f"  → {output_dir / 'post_blunder_tilt.csv'}")

            # Finer breakdown: error after blunder by bucket of prev_error
            prev_buckets = (
                tilt_df.filter(pl.col("prev_was_blunder"))
                .with_columns(
                    pl.when(pl.col("prev_error") < 0.150)
                    .then(pl.lit("0.100-0.149"))
                    .when(pl.col("prev_error") < 0.200)
                    .then(pl.lit("0.150-0.199"))
                    .when(pl.col("prev_error") < 0.300)
                    .then(pl.lit("0.200-0.299"))
                    .otherwise(pl.lit("≥0.300"))
                    .alias("blunder_severity")
                )
                .group_by("blunder_severity")
                .agg([
                    pl.len().alias("count"),
                    pl.col("move_played_error").mean().alias("mean_next_error"),
                ])
                .sort("blunder_severity")
            )
            print(f"\n  Severity breakdown (after blunder):")
            print(f"  {'Severity':>16} {'N':>8} {'MeanNextErr':>12}")
            print("  " + "-" * 40)
            for row in prev_buckets.iter_rows(named=True):
                print(f"  {row['blunder_severity']:>16} {row['count']:>8,} "
                      f"{row['mean_next_error']:>12.4f}")
        else:
            print("  [SKIP] Could not match previous moves")
    else:
        print("  [SKIP] move_number or game_id not available")

    # ──────────────────────────────────────────────────────────
    # 4. Post-loss effect
    # ──────────────────────────────────────────────────────────
    section("4. Post-Loss Effect")
    if all(c in df.columns for c in ["game_number", "match_id", "winner", "player_on_roll"]):
        # For each game, determine if the player on roll lost the previous game.
        # Build a lookup: (match_id, game_number) → winner
        game_winners = (
            games.select(["match_id", "game_number", "winner"])
            .filter(pl.col("winner").is_not_null() & (pl.col("winner") > 0))
        )

        # Add previous game winner
        df_with_prev = (
            df.with_columns(
                (pl.col("game_number") - 1).alias("prev_game_number")
            )
            .join(
                game_winners.rename({
                    "game_number": "prev_game_number",
                    "winner": "prev_game_winner",
                }),
                on=["match_id", "prev_game_number"],
                how="left",
            )
        )

        # Did the current player lose the previous game?
        df_with_prev = df_with_prev.with_columns(
            pl.when(pl.col("prev_game_winner").is_null())
            .then(pl.lit("first_game"))
            .when(pl.col("player_on_roll") == pl.col("prev_game_winner"))
            .then(pl.lit("won_prev"))
            .otherwise(pl.lit("lost_prev"))
            .alias("prev_result")
        )

        loss_stats = (
            df_with_prev.group_by("prev_result")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
                (pl.col("move_played_error") >= BLUNDER_THR)
                .mean().alias("blunder_rate"),
            ])
            .sort("prev_result")
        )
        print(f"  {'PrevResult':>12} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
              f"{'Nontrivial%':>12} {'Blunder%':>9}")
        print("  " + "-" * 64)
        for row in loss_stats.iter_rows(named=True):
            nt = row["nontrivial_rate"] * 100
            br = row["blunder_rate"] * 100
            print(f"  {row['prev_result']:>12} {row['count']:>8,} "
                  f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                  f"{nt:>11.1f}% {br:>8.1f}%")
        loss_stats.write_csv(output_dir / "post_loss_effect.csv")
        print(f"  → {output_dir / 'post_loss_effect.csv'}")

        # Breakdown by game number (does post-loss effect worsen in late games?)
        if len(df_with_prev.filter(pl.col("prev_result") == "lost_prev")) > 100:
            loss_by_game = (
                df_with_prev.filter(
                    pl.col("prev_result").is_in(["won_prev", "lost_prev"])
                )
                .group_by(["game_number", "prev_result"])
                .agg([
                    pl.len().alias("count"),
                    pl.col("move_played_error").mean().alias("mean_error"),
                ])
                .sort(["game_number", "prev_result"])
            )
            loss_by_game.write_csv(output_dir / "post_loss_by_game_number.csv")
            print(f"  → {output_dir / 'post_loss_by_game_number.csv'}")
    else:
        missing = [c for c in ["game_number", "match_id", "winner", "player_on_roll"]
                   if c not in df.columns]
        print(f"  [SKIP] Missing columns: {missing}")

    # ──────────────────────────────────────────────────────────
    # 5. Score deficit effect
    # ──────────────────────────────────────────────────────────
    section("5. Score Deficit Effect")
    if "score_differential" in df.columns:
        # score_differential > 0 → leading, < 0 → trailing
        df_scored = df.with_columns(
            pl.when(pl.col("score_differential") <= -4)
            .then(pl.lit("big deficit (≤-4)"))
            .when(pl.col("score_differential") <= -2)
            .then(pl.lit("deficit (-3 to -2)"))
            .when(pl.col("score_differential") == -1)
            .then(pl.lit("slightly behind (-1)"))
            .when(pl.col("score_differential") == 0)
            .then(pl.lit("tied (0)"))
            .when(pl.col("score_differential") == 1)
            .then(pl.lit("slightly ahead (+1)"))
            .when(pl.col("score_differential") <= 3)
            .then(pl.lit("ahead (+2 to +3)"))
            .otherwise(pl.lit("big lead (≥+4)"))
            .alias("deficit_bracket")
        )
        deficit_stats = (
            df_scored.group_by("deficit_bracket")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
                (pl.col("move_played_error") >= BLUNDER_THR)
                .mean().alias("blunder_rate"),
            ])
            .sort("mean_error", descending=True)
        )
        print(f"  {'Deficit':>24} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
              f"{'Nontrivial%':>12} {'Blunder%':>9}")
        print("  " + "-" * 76)
        for row in deficit_stats.iter_rows(named=True):
            nt = row["nontrivial_rate"] * 100
            br = row["blunder_rate"] * 100
            print(f"  {row['deficit_bracket']:>24} {row['count']:>8,} "
                  f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                  f"{nt:>11.1f}% {br:>8.1f}%")
        deficit_stats.write_csv(output_dir / "score_deficit_effect.csv")
        print(f"  → {output_dir / 'score_deficit_effect.csv'}")
    elif all(c in df.columns for c in ["score_away_p1", "score_away_p2", "player_on_roll"]):
        # Compute deficit from score_away fields if score_differential missing
        df_scored = df.with_columns(
            pl.when(pl.col("player_on_roll") == 1)
            .then(pl.col("score_away_p2") - pl.col("score_away_p1"))
            .otherwise(pl.col("score_away_p1") - pl.col("score_away_p2"))
            .alias("deficit")
        ).with_columns(
            pl.when(pl.col("deficit") <= -4)
            .then(pl.lit("big deficit (≤-4)"))
            .when(pl.col("deficit") <= -2)
            .then(pl.lit("deficit (-3 to -2)"))
            .when(pl.col("deficit") == -1)
            .then(pl.lit("slightly behind (-1)"))
            .when(pl.col("deficit") == 0)
            .then(pl.lit("tied (0)"))
            .when(pl.col("deficit") == 1)
            .then(pl.lit("slightly ahead (+1)"))
            .when(pl.col("deficit") <= 3)
            .then(pl.lit("ahead (+2 to +3)"))
            .otherwise(pl.lit("big lead (≥+4)"))
            .alias("deficit_bracket")
        )
        deficit_stats = (
            df_scored.group_by("deficit_bracket")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                (pl.col("move_played_error") >= SMALL_THR)
                .mean().alias("nontrivial_rate"),
                (pl.col("move_played_error") >= BLUNDER_THR)
                .mean().alias("blunder_rate"),
            ])
            .sort("mean_error", descending=True)
        )
        print(f"  {'Deficit':>24} {'N':>8} {'MeanErr':>9} {'MedianErr':>10} "
              f"{'Nontrivial%':>12} {'Blunder%':>9}")
        print("  " + "-" * 76)
        for row in deficit_stats.iter_rows(named=True):
            nt = row["nontrivial_rate"] * 100
            br = row["blunder_rate"] * 100
            print(f"  {row['deficit_bracket']:>24} {row['count']:>8,} "
                  f"{row['mean_error']:>9.4f} {row['median_error']:>10.4f} "
                  f"{nt:>11.1f}% {br:>8.1f}%")
        deficit_stats.write_csv(output_dir / "score_deficit_effect.csv")
        print(f"  → {output_dir / 'score_deficit_effect.csv'}")
    else:
        print("  [SKIP] score_differential or score_away columns not available")

    # ──────────────────────────────────────────────────────────
    # 6. Error autocorrelation
    # ──────────────────────────────────────────────────────────
    section("6. Error Autocorrelation")
    if all(c in df.columns for c in ["game_id", "move_number", "player_on_roll"]):
        # Compute lag-1 autocorrelation: for consecutive moves by the same
        # player in the same game, is there correlation between errors?
        ordered = df.select([
            "game_id", "move_number", "player_on_roll", "move_played_error",
        ]).sort(["game_id", "move_number"])

        prev = ordered.rename({
            "move_played_error": "prev_error",
            "move_number": "prev_move_number",
            "player_on_roll": "prev_player",
        })
        curr = ordered.with_columns(
            (pl.col("move_number") - 2).alias("prev_move_number"),
        )
        pairs = curr.join(
            prev, on=["game_id", "prev_move_number"],
            how="inner",
        ).filter(
            pl.col("player_on_roll") == pl.col("prev_player")
        )

        if len(pairs) > 100:
            correlation = pairs.select(
                pl.corr("move_played_error", "prev_error").alias("autocorrelation")
            )[0, 0]
            print(f"  Lag-1 autocorrelation (same player, same game): {correlation:.4f}")
            print(f"  N pairs: {len(pairs):,}")

            # Bin current error by previous error level
            error_buckets = (
                pairs.with_columns(
                    pl.when(pl.col("prev_error") < 0.010)
                    .then(pl.lit("prev<0.010 (trivial)"))
                    .when(pl.col("prev_error") < 0.025)
                    .then(pl.lit("prev 0.010-0.024"))
                    .when(pl.col("prev_error") < 0.050)
                    .then(pl.lit("prev 0.025-0.049"))
                    .when(pl.col("prev_error") < 0.100)
                    .then(pl.lit("prev 0.050-0.099"))
                    .otherwise(pl.lit("prev≥0.100 (blunder)"))
                    .alias("prev_error_bin")
                )
                .group_by("prev_error_bin")
                .agg([
                    pl.len().alias("count"),
                    pl.col("move_played_error").mean().alias("mean_next_error"),
                    pl.col("move_played_error").median().alias("median_next_error"),
                    (pl.col("move_played_error") >= SMALL_THR)
                    .mean().alias("nontrivial_rate"),
                    (pl.col("move_played_error") >= BLUNDER_THR)
                    .mean().alias("blunder_rate"),
                ])
                .sort("prev_error_bin")
            )
            print(f"\n  {'Previous Error':>28} {'N':>8} {'MeanNextErr':>12} "
                  f"{'Nontrivial%':>12} {'Blunder%':>9}")
            print("  " + "-" * 73)
            for row in error_buckets.iter_rows(named=True):
                nt = row["nontrivial_rate"] * 100
                br = row["blunder_rate"] * 100
                print(f"  {row['prev_error_bin']:>28} {row['count']:>8,} "
                      f"{row['mean_next_error']:>12.4f} "
                      f"{nt:>11.1f}% {br:>8.1f}%")

            # Save combined autocorrelation results
            autocorr_summary = pl.DataFrame({
                "metric": ["lag1_autocorrelation", "n_pairs"],
                "value": [correlation, float(len(pairs))],
            })
            autocorr_full = pl.concat([
                autocorr_summary.rename({"metric": "prev_error_bin", "value": "mean_next_error"}),
                error_buckets.select([
                    "prev_error_bin",
                    pl.col("mean_next_error"),
                    pl.col("count").cast(pl.Float64).alias("count"),
                ]).drop("count").with_columns(
                    pl.col("mean_next_error")
                ),
            ], how="diagonal")
            error_buckets.write_csv(output_dir / "error_autocorrelation.csv")
            # Also save summary correlation
            with open(output_dir / "error_autocorrelation_summary.txt", "w") as f:
                f.write(f"lag1_autocorrelation={correlation:.6f}\n")
                f.write(f"n_pairs={len(pairs)}\n")
            print(f"\n  → {output_dir / 'error_autocorrelation.csv'}")
            print(f"  → {output_dir / 'error_autocorrelation_summary.txt'}")
        else:
            print("  [SKIP] Not enough consecutive-move pairs")
    else:
        print("  [SKIP] game_id, move_number, or player_on_roll not available")

    print(f"\n{'='*60}")
    print(f"  Done in {time.time()-t0:.1f}s — CSVs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
