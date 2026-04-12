#!/usr/bin/env python3
"""S2.5 — Player profiling by thematic position.

Joins S1.9 ``position_themes`` with S0.4 ``positions_enriched`` + the
``matches`` table to compute per-player × per-theme performance:

- position count (sample support)
- mean move_played_error
- error_rate   (fraction with error > 0.020)
- blunder_rate (fraction with error > 0.080)
- PR rating (avg_error_checker × 500, XG approximation — checker-only)

Only players with >= --min-matches distinct matches are profiled.

Outputs
-------
  <output>/player_theme_profile.parquet    long format per (player, theme)
  <output>/player_theme_profile.csv        same (CSV, sorted by sample size)
  <output>/player_theme_primary.csv        per-player primary-theme breakdown

Usage::

    python scripts/analyze_player_themes.py \\
        --enriched data/parquet/positions_enriched \\
        --themes   data/parquet/position_themes \\
        --parquet  data/parquet \\
        --output   data/player_themes \\
        [--min-matches 20] [--sample 10000000]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.theme_rules import ALL_THEME_COLUMNS  # noqa: E402

ERROR_THR = 0.020
BLUNDER_THR = 0.080
PR_FACTOR = 500.0


def load_matches(parquet_dir: Path) -> pl.DataFrame:
    p = parquet_dir / "matches.parquet"
    if not p.exists():
        sys.exit(f"matches.parquet not found in {parquet_dir}")
    return pl.read_parquet(p, columns=["match_id", "player1", "player2"])


def player_lookup(matches: pl.DataFrame) -> pl.DataFrame:
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
    return pl.concat([m1, m2], how="vertical")


def load_slice(
    enriched_dir: Path,
    themes_dir: Path,
    lookup: pl.DataFrame,
    sample: int,
) -> pl.DataFrame:
    """Stream partition pairs, resolve player names, and join themes.

    Returns one row per position with player, decision_type,
    move_played_error, and a boolean column per theme.
    """
    enriched_files = sorted(enriched_dir.glob("part-*.parquet"))
    if not enriched_files:
        sys.exit(f"No enriched partitions in {enriched_dir}")

    enriched_cols = [
        "position_id", "game_id", "match_id", "player_on_roll",
        "decision_type", "move_played_error",
    ]

    frames: list[pl.DataFrame] = []
    total = 0
    for f in enriched_files:
        themes_file = themes_dir / f.name
        if not themes_file.exists():
            continue
        try:
            enr_probe = pl.read_parquet(f, n_rows=1).columns
            cols = [c for c in enriched_cols if c in enr_probe]
            enr = pl.read_parquet(f, columns=cols)
        except Exception as exc:
            print(f"  [warn] {f.name}: {exc}", file=sys.stderr)
            continue

        # Derive match_id from game_id when not present.
        if "match_id" not in enr.columns and "game_id" in enr.columns:
            enr = enr.with_columns(
                pl.col("game_id").str.replace(r"_game_\d+$", "").alias("match_id")
            )

        theme_probe = pl.read_parquet(themes_file, n_rows=1).columns
        theme_cols = (
            ["position_id", "primary_theme"]
            + [c for c in ALL_THEME_COLUMNS if c in theme_probe]
        )
        themes = pl.read_parquet(themes_file, columns=theme_cols)

        if "player_on_roll" in enr.columns and enr["player_on_roll"].dtype != pl.Int8:
            enr = enr.with_columns(pl.col("player_on_roll").cast(pl.Int8))

        enr = enr.join(lookup, on=["match_id", "player_on_roll"], how="left")
        enr = enr.filter(pl.col("player").is_not_null())
        enr = enr.join(themes, on="position_id", how="left")
        frames.append(enr)
        total += len(enr)
        if total >= sample:
            break

    if not frames:
        sys.exit("no data loaded — check inputs")

    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def compute_profile(
    df: pl.DataFrame,
    min_matches: int,
) -> pl.DataFrame:
    """Long-form per-player × per-theme metrics."""
    player_matches = (
        df.group_by("player")
          .agg(pl.col("match_id").n_unique().alias("player_matches"))
    )
    eligible = player_matches.filter(pl.col("player_matches") >= min_matches)
    df = df.join(eligible, on="player", how="inner")

    rows: list[pl.DataFrame] = []
    present_themes = [c for c in ALL_THEME_COLUMNS if c in df.columns]

    for theme_col in present_themes:
        theme_name = theme_col.removeprefix("theme_")
        sub = df.filter(pl.col(theme_col))
        if sub.is_empty():
            continue

        agg = (
            sub.group_by("player")
               .agg([
                   pl.len().alias("positions"),
                   pl.col("match_id").n_unique().alias("matches"),
                   pl.col("move_played_error").mean().alias("avg_error"),
                   (pl.col("move_played_error") > ERROR_THR)
                       .mean().alias("error_rate"),
                   (pl.col("move_played_error") > BLUNDER_THR)
                       .mean().alias("blunder_rate"),
                   pl.col("move_played_error")
                       .filter(pl.col("decision_type") == "checker")
                       .mean().alias("avg_error_checker"),
               ])
               .with_columns([
                   pl.lit(theme_name).alias("theme"),
                   (pl.col("avg_error_checker") * PR_FACTOR).alias("pr_rating"),
               ])
        )
        rows.append(agg)

    if not rows:
        return pl.DataFrame()

    out = pl.concat(rows, how="diagonal")
    return out.select([
        "player", "theme", "positions", "matches",
        "avg_error", "avg_error_checker", "pr_rating",
        "error_rate", "blunder_rate",
    ]).sort(["player", "positions"], descending=[False, True])


def compute_primary_breakdown(df: pl.DataFrame) -> pl.DataFrame:
    """Per-player count of each primary_theme (single-label view)."""
    if "primary_theme" not in df.columns:
        return pl.DataFrame()
    return (
        df.group_by(["player", "primary_theme"])
          .agg(pl.len().alias("positions"))
          .sort(["player", "positions"], descending=[False, True])
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="S2.5 — Player theme profiling")
    ap.add_argument("--enriched", default="data/parquet/positions_enriched")
    ap.add_argument("--themes", default="data/parquet/position_themes")
    ap.add_argument("--parquet", default="data/parquet")
    ap.add_argument("--output", default="data/player_themes")
    ap.add_argument("--min-matches", type=int, default=20)
    ap.add_argument("--sample", type=int, default=10_000_000)
    args = ap.parse_args()

    enriched_dir = Path(args.enriched)
    themes_dir = Path(args.themes)
    parquet_dir = Path(args.parquet)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S2.5 — Player × Theme Profile")
    print("=" * 60)
    print(f"  enriched : {enriched_dir}")
    print(f"  themes   : {themes_dir}")
    print(f"  sample   : {args.sample:,}")
    print(f"  min-match: {args.min_matches}")

    t0 = time.time()
    matches = load_matches(parquet_dir)
    lookup = player_lookup(matches)
    print(f"  players in lookup: {lookup['player'].n_unique():,}")

    t1 = time.time()
    df = load_slice(enriched_dir, themes_dir, lookup, args.sample)
    print(f"  loaded {len(df):,} rows "
          f"across {df['player'].n_unique():,} players "
          f"({time.time()-t1:.1f}s)")

    t2 = time.time()
    profile = compute_profile(df, args.min_matches)
    print(f"  profile: {len(profile):,} (player,theme) rows "
          f"({time.time()-t2:.1f}s)")
    profile.write_parquet(out_dir / "player_theme_profile.parquet")
    profile.write_csv(out_dir / "player_theme_profile.csv")
    print(f"  → {out_dir / 'player_theme_profile.parquet'}")
    print(f"  → {out_dir / 'player_theme_profile.csv'}")

    primary = compute_primary_breakdown(df)
    if not primary.is_empty():
        primary.write_csv(out_dir / "player_theme_primary.csv")
        print(f"  → {out_dir / 'player_theme_primary.csv'}")

    print(f"\nDone in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
