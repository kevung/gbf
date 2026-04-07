#!/usr/bin/env python3
"""
S2.1 — Player Profiling Metrics

Compute ~20 metrics per player from positions_enriched (S0.4).
Players are resolved by joining player_on_roll with matches.player1/player2.
Only players with >= --min-matches matches are profiled.

Metrics computed
----------------
Volume:
  total_matches           distinct matches in which the player appears
  total_positions         total checker + cube decisions
  total_checker           checker decisions count
  total_cube              cube decisions count

Global performance (checker moves):
  avg_error_checker       mean move_played_error (checker decisions)
  avg_error_cube          mean move_played_error (cube decisions)
  error_rate              fraction with error > 0.020 (checker)
  blunder_rate            fraction with error > 0.080 (checker)
  pr_rating               avg_error_checker * 500 (XG approximation)
  error_std               std dev of move_played_error (checker)

Phase profile (checker moves):
  avg_error_contact       mean error in contact phase (match_phase == 0)
  avg_error_race          mean error in race phase (match_phase == 1)
  avg_error_bearoff       mean error in bearoff phase (match_phase == 2)
  avg_error_opening       mean error on move_number <= 10
  avg_error_midgame       mean error on move_number 11..30
  avg_error_endgame       mean error on move_number > 30

Cube profile (cube decisions, requires cube_action_played / cube_action_optimal):
  missed_double_rate      P(played=no_double | optimal=double)
  wrong_take_rate         P(played=take | optimal=pass)
  wrong_pass_rate         P(played=pass | optimal=take)

Tactical profile (checker moves):
  aggression_index        avg home_board_points_p1 — proxy for blitz tendency
  risk_appetite           avg gammon_threat — proxy for gammon-prone positions

Consistency (checker moves, per-game sequential):
  streak_tendency         lag-1 autocorrelation of errors within games

Outputs
-------
  <output>/player_profiles.parquet
  <output>/player_profiles.csv
  <output>/cube_error_by_score.csv    (cube error × away-score bracket, top players)
  <output>/player_summary.txt

Usage
-----
  python scripts/analyze_player_profiles.py \\
      --enriched data/parquet/positions_enriched \\
      --parquet  data/parquet \\
      --output   data/player_profiles \\
      [--min-matches 20] [--sample 5000000]
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
ERROR_THR = 0.020        # non-trivial error
BLUNDER_THR = 0.080      # blunder (XG definition)
MIN_PAIRS = 30           # minimum move-pairs for autocorrelation
PR_FACTOR = 500.0        # XG approximation: PR = avg_error * PR_FACTOR


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_matches(parquet_dir: str) -> pl.DataFrame:
    """Load matches table (player1, player2, match_id)."""
    p = Path(parquet_dir) / "matches.parquet"
    if not p.exists():
        sys.exit(f"matches.parquet not found in {parquet_dir}")
    return pl.read_parquet(p, columns=["match_id", "player1", "player2"])


def load_enriched(enriched_dir: str, sample: int) -> pl.DataFrame:
    """Load positions_enriched, prioritising relevant columns."""
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    # Columns we ideally want — script is tolerant of missing ones.
    want = [
        "position_id", "game_id", "match_id", "move_number", "player_on_roll",
        "decision_type", "move_played_error",
        "match_phase",
        "home_board_points_p1", "gammon_threat",
        "cube_action_played", "cube_action_optimal",
        "score_away_p1", "score_away_p2",
    ]

    frames = []
    total = 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols = [c for c in want if c in probe.columns]
            df = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] Could not read {p.name}: {exc}", file=sys.stderr)
            continue
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No enriched data found")

    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


# ---------------------------------------------------------------------------
# Player resolution: player_on_roll ∈ {1,2} → player name
# ---------------------------------------------------------------------------

def resolve_player_names(pos: pl.DataFrame, matches: pl.DataFrame) -> pl.DataFrame:
    """
    Add column `player` by joining on (match_id, player_on_roll).

    matches has: match_id, player1, player2.
    player_on_roll == 1 → player1, player_on_roll == 2 → player2.
    """
    if "match_id" not in pos.columns:
        print("  [WARN] match_id missing — cannot resolve player names", file=sys.stderr)
        return pos.with_columns(pl.lit(None).cast(pl.String).alias("player"))

    # Build long table: (match_id, player_on_roll, player_name)
    m1 = matches.select([
        pl.col("match_id"),
        pl.lit(1).cast(pl.Int8).alias("player_on_roll"),
        pl.col("player1").cast(pl.String).alias("player"),
    ])
    m2 = matches.select([
        pl.col("match_id"),
        pl.lit(2).cast(pl.Int8).alias("player_on_roll"),
        pl.col("player2").cast(pl.String).alias("player"),
    ])
    lookup = pl.concat([m1, m2], how="vertical")

    # Ensure player_on_roll is Int8 in pos
    if pos["player_on_roll"].dtype != pl.Int8:
        pos = pos.with_columns(pl.col("player_on_roll").cast(pl.Int8))

    return pos.join(lookup, on=["match_id", "player_on_roll"], how="left")


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_checker_metrics(ch: pl.DataFrame) -> pl.DataFrame:
    """Aggregate checker-decision metrics per player."""
    if ch.is_empty():
        return pl.DataFrame()

    agg_exprs = [
        pl.col("match_id").n_unique().alias("total_matches"),
        pl.len().alias("total_checker"),
        pl.col("move_played_error").mean().alias("avg_error_checker"),
        pl.col("move_played_error").std().alias("error_std"),
        (pl.col("move_played_error") > ERROR_THR).mean().alias("error_rate"),
        (pl.col("move_played_error") > BLUNDER_THR).mean().alias("blunder_rate"),
    ]

    # Phase breakdowns (match_phase: 0=contact 1=race 2=bearoff)
    if "match_phase" in ch.columns:
        for phase_val, name in [(0, "contact"), (1, "race"), (2, "bearoff")]:
            agg_exprs.append(
                pl.col("move_played_error")
                .filter(pl.col("match_phase") == phase_val)
                .mean()
                .alias(f"avg_error_{name}")
            )

    # Move-number breakdowns (opening/midgame/endgame)
    if "move_number" in ch.columns:
        agg_exprs += [
            pl.col("move_played_error")
            .filter(pl.col("move_number") <= 10)
            .mean()
            .alias("avg_error_opening"),
            pl.col("move_played_error")
            .filter(pl.col("move_number").is_between(11, 30))
            .mean()
            .alias("avg_error_midgame"),
            pl.col("move_played_error")
            .filter(pl.col("move_number") > 30)
            .mean()
            .alias("avg_error_endgame"),
        ]

    # Tactical proxies
    if "home_board_points_p1" in ch.columns:
        agg_exprs.append(
            pl.col("home_board_points_p1").mean().alias("aggression_index")
        )
    if "gammon_threat" in ch.columns:
        agg_exprs.append(
            pl.col("gammon_threat").mean().alias("risk_appetite")
        )

    return ch.group_by("player").agg(agg_exprs)


def compute_cube_metrics(cube: pl.DataFrame) -> pl.DataFrame:
    """Aggregate cube-decision metrics per player."""
    if cube.is_empty():
        return pl.DataFrame()

    agg_exprs = [
        pl.len().alias("total_cube"),
        pl.col("move_played_error").mean().alias("avg_error_cube"),
    ]

    if "cube_action_played" in cube.columns and "cube_action_optimal" in cube.columns:
        # Cast to string for comparison
        cube = cube.with_columns([
            pl.col("cube_action_played").cast(pl.String),
            pl.col("cube_action_optimal").cast(pl.String),
        ])

        # Missed double: optimal=double, played=no_double
        agg_exprs.append(
            (
                (pl.col("cube_action_optimal").str.to_lowercase().str.contains("double"))
                & (pl.col("cube_action_played").str.to_lowercase().str.contains("no_double")
                   | pl.col("cube_action_played").str.to_lowercase().str.contains("no double"))
            ).mean().alias("missed_double_rate")
        )
        # Wrong take: optimal=pass, played=take
        agg_exprs.append(
            (
                (pl.col("cube_action_optimal").str.to_lowercase() == "pass")
                & (pl.col("cube_action_played").str.to_lowercase() == "take")
            ).mean().alias("wrong_take_rate")
        )
        # Wrong pass: optimal=take, played=pass
        agg_exprs.append(
            (
                (pl.col("cube_action_optimal").str.to_lowercase() == "take")
                & (pl.col("cube_action_played").str.to_lowercase() == "pass")
            ).mean().alias("wrong_pass_rate")
        )

    return cube.group_by("player").agg(agg_exprs)


def compute_streak_tendency(ch: pl.DataFrame) -> pl.DataFrame:
    """
    Compute lag-1 error autocorrelation per player (streak_tendency).

    For each player, collect their consecutive move pairs (move_number,
    move_number+2 by same player in the same game), then compute the
    Pearson correlation between error_t and error_{t+1}.
    """
    if ch.is_empty() or "game_id" not in ch.columns or "move_number" not in ch.columns:
        return pl.DataFrame({"player": pl.Series([], dtype=pl.String),
                             "streak_tendency": pl.Series([], dtype=pl.Float64)})

    ordered = ch.select([
        "player", "game_id", "move_number", "move_played_error",
    ]).sort(["player", "game_id", "move_number"])

    # Lag-2 within same game (players alternate, so same player's next turn
    # is move_number + 2).
    curr = ordered.rename({"move_number": "mn"})
    prev = ordered.rename({
        "move_number": "mn",
        "move_played_error": "prev_error",
        "player": "prev_player",
    }).with_columns((pl.col("mn") + 2).alias("mn"))

    pairs = curr.join(
        prev, on=["game_id", "mn"], how="inner"
    ).filter(pl.col("player") == pl.col("prev_player"))

    if pairs.is_empty():
        return pl.DataFrame({"player": pl.Series([], dtype=pl.String),
                             "streak_tendency": pl.Series([], dtype=pl.Float64)})

    # Per-player autocorrelation
    results = []
    for player_name, grp in pairs.group_by("player"):
        if len(grp) < MIN_PAIRS:
            continue
        corr = grp.select(
            pl.corr("move_played_error", "prev_error").alias("r")
        )[0, 0]
        results.append({"player": player_name[0], "streak_tendency": corr})

    if not results:
        return pl.DataFrame({"player": pl.Series([], dtype=pl.String),
                             "streak_tendency": pl.Series([], dtype=pl.Float64)})
    return pl.DataFrame(results)


def compute_cube_by_score(cube: pl.DataFrame, top_n: int = 50) -> pl.DataFrame:
    """
    Cube error by away-score bracket per player (top_n players by volume).
    Returns long-format table: player, score_bracket, n, avg_cube_error.
    """
    if cube.is_empty():
        return pl.DataFrame()
    need = {"score_away_p1", "score_away_p2", "move_played_error"}
    if not need.issubset(set(cube.columns)):
        return pl.DataFrame()

    # Focus on top players by cube volume
    top_players = (
        cube.group_by("player")
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
        .head(top_n)
        .select("player")
    )
    sub = cube.join(top_players, on="player", how="inner")

    sub = sub.with_columns(
        pl.when(
            (pl.col("score_away_p1") <= 2) & (pl.col("score_away_p2") <= 2)
        ).then(pl.lit("DMP/GS"))
        .when(
            (pl.col("score_away_p1") <= 3) | (pl.col("score_away_p2") <= 3)
        ).then(pl.lit("3-away"))
        .when(
            (pl.col("score_away_p1") <= 5) | (pl.col("score_away_p2") <= 5)
        ).then(pl.lit("4-5 away"))
        .when(
            (pl.col("score_away_p1") <= 9) | (pl.col("score_away_p2") <= 9)
        ).then(pl.lit("6-9 away"))
        .otherwise(pl.lit("10+ away"))
        .alias("score_bracket")
    )

    return (
        sub.group_by(["player", "score_bracket"])
        .agg([
            pl.len().alias("n"),
            pl.col("move_played_error").mean().alias("avg_cube_error"),
        ])
        .sort(["player", "score_bracket"])
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def print_top_bottom(profiles: pl.DataFrame, col: str, label: str,
                     n: int = 10, ascending: bool = True) -> None:
    """Print top-N and bottom-N players for a given metric."""
    valid = profiles.filter(pl.col(col).is_not_null()).sort(col, descending=not ascending)
    print(f"\n  {'Player':<32} {label:>10}")
    print("  " + "-" * 44)
    shown = min(n, len(valid))
    for row in valid.head(shown).iter_rows(named=True):
        print(f"  {str(row['player']):<32} {row[col]:>10.4f}")
    if len(valid) > n:
        print(f"  ... ({len(valid) - n} more)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S2.1 — Player Profiling Metrics")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory (S0.4)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet directory (contains matches.parquet)")
    ap.add_argument("--output", default="data/player_profiles",
                    help="Output directory for CSV/Parquet files")
    ap.add_argument("--min-matches", type=int, default=20,
                    help="Minimum matches to include a player (default: 20)")
    ap.add_argument("--sample", type=int, default=5_000_000,
                    help="Max rows to load from enriched (default: 5000000)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S2.1 — Player Profiling Metrics")
    print("=" * 60)
    print(f"  enriched    : {args.enriched}")
    print(f"  parquet     : {args.parquet}")
    print(f"  output      : {output_dir}")
    print(f"  min-matches : {args.min_matches}")
    print(f"  sample      : {args.sample:,}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    section("Loading data")
    matches = load_matches(args.parquet)
    print(f"  Loaded {len(matches):,} matches")

    pos = load_enriched(args.enriched, args.sample)
    print(f"  Loaded {len(pos):,} enriched positions ({time.time()-t0:.1f}s)")

    # Resolve player names
    pos = resolve_player_names(pos, matches)
    n_resolved = pos.filter(pl.col("player").is_not_null()).height
    print(f"  Player names resolved for {n_resolved:,} / {len(pos):,} rows")

    pos = pos.filter(pl.col("player").is_not_null())
    if pos.is_empty():
        sys.exit("No rows with resolved player names — check match_id presence in enriched data")

    # Split checker vs cube
    if "decision_type" in pos.columns:
        ch  = pos.filter(pl.col("decision_type") == "checker")
        cube = pos.filter(pl.col("decision_type") == "cube")
    else:
        ch   = pos
        cube = pl.DataFrame()

    print(f"  Checker decisions : {len(ch):,}")
    print(f"  Cube decisions    : {len(cube):,}")

    # ------------------------------------------------------------------
    # Compute metrics
    # ------------------------------------------------------------------
    section("Computing checker metrics")
    checker_metrics = compute_checker_metrics(ch)
    print(f"  {len(checker_metrics):,} players with checker data")

    section("Computing cube metrics")
    cube_metrics = compute_cube_metrics(cube) if not cube.is_empty() else pl.DataFrame()
    print(f"  {len(cube_metrics):,} players with cube data")

    section("Computing streak tendency (autocorrelation)")
    streak_df = compute_streak_tendency(ch)
    print(f"  {len(streak_df):,} players with enough consecutive pairs")

    section("Computing cube error by score bracket")
    cube_score_df = compute_cube_by_score(cube) if not cube.is_empty() else pl.DataFrame()

    # ------------------------------------------------------------------
    # Merge into player_profiles
    # ------------------------------------------------------------------
    section("Building player_profiles table")

    profiles = checker_metrics
    if not cube_metrics.is_empty():
        profiles = profiles.join(cube_metrics, on="player", how="left")
    if not streak_df.is_empty():
        profiles = profiles.join(streak_df, on="player", how="left")

    # Derived columns
    profiles = profiles.with_columns([
        (pl.col("avg_error_checker") * PR_FACTOR).alias("pr_rating"),
    ])

    # Apply minimum-matches filter
    profiles = profiles.filter(pl.col("total_matches") >= args.min_matches)
    print(f"  {len(profiles):,} players with >= {args.min_matches} matches")

    # Column order — put key metrics first
    priority = [
        "player", "total_matches", "total_checker", "total_cube",
        "avg_error_checker", "avg_error_cube", "pr_rating",
        "error_rate", "blunder_rate", "error_std",
        "avg_error_contact", "avg_error_race", "avg_error_bearoff",
        "avg_error_opening", "avg_error_midgame", "avg_error_endgame",
        "missed_double_rate", "wrong_take_rate", "wrong_pass_rate",
        "aggression_index", "risk_appetite", "streak_tendency",
    ]
    present = [c for c in priority if c in profiles.columns]
    remaining = [c for c in profiles.columns if c not in present]
    profiles = profiles.select(present + remaining)

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    section("Saving outputs")

    profiles_parquet = output_dir / "player_profiles.parquet"
    profiles_csv = output_dir / "player_profiles.csv"
    profiles.write_parquet(profiles_parquet)
    profiles.write_csv(profiles_csv)
    print(f"  → {profiles_parquet}  ({len(profiles):,} rows × {len(profiles.columns)} cols)")
    print(f"  → {profiles_csv}")

    if not cube_score_df.is_empty():
        cube_score_path = output_dir / "cube_error_by_score.csv"
        cube_score_df.write_csv(cube_score_path)
        print(f"  → {cube_score_path}  ({len(cube_score_df):,} rows)")

    # Text summary
    summary_path = output_dir / "player_summary.txt"
    with open(summary_path, "w") as f:
        f.write("S2.1 — Player Profiling Summary\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Players profiled : {len(profiles):,}\n")
        f.write(f"Min matches      : {args.min_matches}\n")
        f.write(f"Sample rows      : {len(pos):,}\n\n")

        for col, label, asc in [
            ("pr_rating",           "PR Rating (best = lowest)",   True),
            ("blunder_rate",        "Blunder Rate (best = lowest)", True),
            ("avg_error_contact",   "Contact Error",               True),
            ("avg_error_race",      "Race Error",                  True),
            ("avg_error_cube",      "Cube Error",                  True),
            ("avg_error_opening",   "Opening Error",               True),
        ]:
            if col not in profiles.columns:
                continue
            valid = profiles.filter(pl.col(col).is_not_null()).sort(col, descending=not asc)
            f.write(f"\n{'─'*60}\n  {label}\n{'─'*60}\n")
            f.write(f"  {'Player':<32} {label:>12}\n")
            f.write("  " + "-" * 46 + "\n")
            for row in valid.head(15).iter_rows(named=True):
                f.write(f"  {str(row['player']):<32} {row[col]:>12.4f}\n")
    print(f"  → {summary_path}")

    # ------------------------------------------------------------------
    # Quick console report
    # ------------------------------------------------------------------
    section("Top players by PR Rating (lowest = best)")
    if "pr_rating" in profiles.columns:
        print_top_bottom(profiles, "pr_rating", "PR Rating", n=15, ascending=True)

    section("Phase error profile (population mean)")
    for col in ["avg_error_contact", "avg_error_race", "avg_error_bearoff"]:
        if col in profiles.columns:
            v = profiles.filter(pl.col(col).is_not_null())[col].mean()
            print(f"  {col:<28} : {v:.4f}")

    section("Cube profile (population mean)")
    for col in ["missed_double_rate", "wrong_take_rate", "wrong_pass_rate"]:
        if col in profiles.columns:
            v = profiles.filter(pl.col(col).is_not_null())[col].mean()
            print(f"  {col:<28} : {v:.4f}")

    section("Consistency (population mean streak_tendency)")
    if "streak_tendency" in profiles.columns:
        v = profiles.filter(pl.col("streak_tendency").is_not_null())["streak_tendency"].mean()
        n = profiles.filter(pl.col("streak_tendency").is_not_null()).height
        print(f"  mean lag-1 autocorrelation : {v:.4f}  (N={n:,} players)")
        print("  (positive = errors come in series; negative = self-correcting)")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
