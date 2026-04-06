#!/usr/bin/env python3
"""S0.4 — Feature engineering for the backgammon mining study pipeline.

Reads positions + games Parquet files from S0.2 and computes ~34
interpretable features per position. Outputs positions_enriched.parquet
(partitioned), ready for S1 exploration and S0.5 validation.

Features computed
-----------------
Board structure (from on-roll player's perspective, _p1 = on-roll):
  pip_count_p1/p2           pip count per player
  pip_count_diff            p1 - p2 (negative = p1 behind)
  num_blots_p1/p2           isolated checkers (vulnerable)
  num_points_made_p1/p2     points with >= 2 checkers
  home_board_points_p1/p2   made points in home board (indices 1-6)
  home_board_strength_p1    weighted home board (point 6=6, 1=1)
  longest_prime_p1/p2       longest run of consecutive made points
  prime_location_p1         start index of longest prime (0 = none)
  back_anchor_p1            highest made point in opp home board (19-24)
  num_checkers_back_p1      checkers at points 19-24 (opponent home)
  num_builders_p1           lone checkers adjacent to unmade points
  outfield_blots_p1         blots between points 7 and 18
  num_on_bar_p1/p2          board index 0
  num_borne_off_p1/p2       board index 25

Match context (from eval columns):
  match_phase               0=contact, 1=race, 2=bearoff
  gammon_threat             eval_win_g + eval_win_bg
  gammon_risk               eval_lose_g + eval_lose_bg
  net_gammon                gammon_threat - gammon_risk
  cube_leverage             cube_value / max(away_p1, away_p2)

Score features (from games join):
  score_away_p1/p2          away scores (joined from games table)
  leader                    1=p1 ahead, 2=p2 ahead, 0=tied
  score_differential        abs(away_p1 - away_p2)
  crawford                  boolean Crawford game flag
  is_pre_crawford           min(away) == 1, not crawford
  is_post_crawford          post-Crawford game
  is_dmp                    2away-2away (Double Match Point)
  dgr                       dead gammon risk (leader at 1away, gammon useless)
  take_point_match          approximate match take point (Janowski formula)

Usage::

    python scripts/compute_features.py \\
        --parquet-dir data/parquet \\
        --output data/parquet/positions_enriched \\
        [--chunk-rows 100000] [--parts 16]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# Board feature helpers (numpy, applied per-row via map_elements)
# ---------------------------------------------------------------------------

def _longest_prime(board: list[int]) -> int:
    """Return length of longest run of consecutive made points (>= 2) in 1..24."""
    best = cur = 0
    for i in range(1, 25):
        if board[i] >= 2:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _prime_location(board: list[int]) -> int:
    """Return start index (1..24) of longest prime, 0 if no prime."""
    best_len = best_start = cur_len = cur_start = 0
    for i in range(1, 25):
        if board[i] >= 2:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start = cur_start
        else:
            cur_len = 0
    return best_start if best_len >= 2 else 0


def _back_anchor(board: list[int]) -> int:
    """Highest made point (>= 2 checkers) in opponent home board (19..24)."""
    for i in range(24, 18, -1):
        if board[i] >= 2:
            return i
    return 0


def _num_builders(board: list[int]) -> int:
    """Lone checkers (blots) on points adjacent to unmade points (builders).

    A builder is a lone checker on point i where point i-1 or i+1
    is unmade (< 2 checkers) and could be made with the builder's help.
    """
    count = 0
    for i in range(1, 25):
        if board[i] == 1:  # blot = potential builder
            # Check adjacent points that are currently unmade.
            adjacent_unmade = any(
                1 <= j <= 24 and board[j] < 2
                for j in (i - 1, i + 1)
            )
            if adjacent_unmade:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Vectorized Polars feature computation
# ---------------------------------------------------------------------------

# Pip weight: index 0=bar(25 pips), 1..24=point value, 25=off(0 pips)
_PIP_WEIGHTS = [25] + list(range(1, 25)) + [0]

# Home board indices: 1..6 (player's own home board)
_HOME_INDICES = list(range(1, 7))

# Opponent home board indices: 19..24 (where back anchors live)
_OPP_HOME_INDICES = list(range(19, 25))

# Outfield indices: 7..18
_OUTFIELD_INDICES = list(range(7, 19))


def _pip_count_expr(col: str) -> pl.Expr:
    """Vectorized pip count from a 26-element board List[Int8]."""
    return sum(
        pl.col(col).list.get(i).cast(pl.Int32) * w
        for i, w in enumerate(_PIP_WEIGHTS)
        if w > 0
    )


def _sum_blots_expr(col: str, indices: list[int]) -> pl.Expr:
    """Number of blots (== 1) at given board indices."""
    return sum(
        (pl.col(col).list.get(i).cast(pl.Int32) == 1).cast(pl.Int32)
        for i in indices
    )


def _sum_points_made_expr(col: str, indices: list[int]) -> pl.Expr:
    """Number of made points (>= 2) at given board indices."""
    return sum(
        (pl.col(col).list.get(i).cast(pl.Int32) >= 2).cast(pl.Int32)
        for i in indices
    )


def _home_strength_expr(col: str) -> pl.Expr:
    """Weighted home board strength: sum of point_index * (point_made >= 2)."""
    return sum(
        (pl.col(col).list.get(i).cast(pl.Int32) >= 2).cast(pl.Int32) * i
        for i in _HOME_INDICES
    )


def _sum_checkers_expr(col: str, indices: list[int]) -> pl.Expr:
    """Total checker count at given board indices."""
    return sum(
        pl.col(col).list.get(i).cast(pl.Int32)
        for i in indices
    )


# ---------------------------------------------------------------------------
# Contact / race / bearoff classification
# ---------------------------------------------------------------------------

def _classify_phase(df: pl.DataFrame) -> pl.Series:
    """Classify each position as contact(0), race(1), or bearoff(2).

    Bearoff: both players have all checkers in home board (1-6) or borne off.
    Race: no contact — P1's back checker (highest index) + P2's back checker
          (highest index) <= 24. This is the standard contact test.
    Contact: otherwise (checkers cross each other or bar occupied).
    """
    def classify(row) -> int:
        b1, b2 = row["board_p1"], row["board_p2"]

        # Bearoff: no checkers outside home board (1-6) and none on bar.
        p1_bearoff = all(b1[i] == 0 for i in range(7, 25)) and b1[0] == 0
        p2_bearoff = all(b2[i] == 0 for i in range(7, 25)) and b2[0] == 0
        if p1_bearoff and p2_bearoff:
            return 2

        # Contact test: find each player's MOST ADVANCED (highest-index) checker.
        # board_p1[24] = P1's 24-point (furthest from home); board_p2[24] = same.
        # Contact exists when p1_back + p2_back > 24 (they overlap on the board).
        p1_back = next((i for i in range(24, 0, -1) if b1[i] > 0), 0)
        p2_back = next((i for i in range(24, 0, -1) if b2[i] > 0), 0)

        # Bar checkers also mean contact (checker needs to re-enter opponent home).
        if b1[0] > 0 or b2[0] > 0:
            return 0  # contact

        if p1_back + p2_back > 24:
            return 0  # contact
        return 1  # race

    return pl.Series("match_phase", [classify(r) for r in df.iter_rows(named=True)])


# ---------------------------------------------------------------------------
# Match equity approximation (Janowski formula)
# ---------------------------------------------------------------------------

def _take_point_match(away_p1: int, away_p2: int) -> float:
    """Approximate match take point using Janowski's formula.

    Returns the equity threshold below which the player on roll should not
    double (i.e., the take point for the receiving player).

    For money game: always 0.25.
    For match: derived from ME(away_p1 - 1) - ME(away_p1) etc.
    Uses a symmetric approximation: ME(n) ≈ 0.5 * (1 + 0.85^n * sign).
    This is a rough approximation — the full Kazaross MET should replace it.
    """
    if away_p1 <= 0 or away_p2 <= 0:
        return 0.25

    def me(n_self: int, n_opp: int) -> float:
        """Approximate match equity for player needing n_self points."""
        if n_self <= 0:
            return 1.0
        if n_opp <= 0:
            return 0.0
        # Simplified Janowski approximation.
        x = (n_opp - n_self) / (n_self + n_opp)
        return 0.5 + 0.85 * x * 0.5

    me_no_dbl = me(away_p1, away_p2)
    me_win = me(away_p1 - 1, away_p2)
    me_lose = me(away_p1, away_p2 - 1)

    denom = me_win - me_lose
    if abs(denom) < 1e-6:
        return 0.25

    take_point = (me_no_dbl - me_lose) / denom
    return max(0.0, min(0.5, take_point))


# ---------------------------------------------------------------------------
# Per-chunk feature computation
# ---------------------------------------------------------------------------

def compute_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add ~34 feature columns to a positions+games DataFrame chunk."""

    # --- Board structure features (vectorized) ---
    df = df.with_columns([
        # Pip counts.
        _pip_count_expr("board_p1").alias("pip_count_p1"),
        _pip_count_expr("board_p2").alias("pip_count_p2"),

        # On-bar / borne-off.
        pl.col("board_p1").list.get(0).cast(pl.Int32).alias("num_on_bar_p1"),
        pl.col("board_p2").list.get(0).cast(pl.Int32).alias("num_on_bar_p2"),
        pl.col("board_p1").list.get(25).cast(pl.Int32).alias("num_borne_off_p1"),
        pl.col("board_p2").list.get(25).cast(pl.Int32).alias("num_borne_off_p2"),

        # Blots (all 24 points).
        _sum_blots_expr("board_p1", list(range(1, 25))).alias("num_blots_p1"),
        _sum_blots_expr("board_p2", list(range(1, 25))).alias("num_blots_p2"),

        # Points made (all 24 points).
        _sum_points_made_expr("board_p1", list(range(1, 25))).alias("num_points_made_p1"),
        _sum_points_made_expr("board_p2", list(range(1, 25))).alias("num_points_made_p2"),

        # Home board points + strength.
        _sum_points_made_expr("board_p1", _HOME_INDICES).alias("home_board_points_p1"),
        _sum_points_made_expr("board_p2", _HOME_INDICES).alias("home_board_points_p2"),
        _home_strength_expr("board_p1").alias("home_board_strength_p1"),

        # Checkers in opponent home (back anchor zone).
        _sum_checkers_expr("board_p1", _OPP_HOME_INDICES).alias("num_checkers_back_p1"),

        # Outfield blots.
        _sum_blots_expr("board_p1", _OUTFIELD_INDICES).alias("outfield_blots_p1"),
    ])

    # Pip count diff.
    df = df.with_columns(
        (pl.col("pip_count_p1") - pl.col("pip_count_p2")).alias("pip_count_diff")
    )

    # --- Complex board features (map_elements for sequential logic) ---
    df = df.with_columns([
        pl.col("board_p1").map_elements(_longest_prime, return_dtype=pl.Int32).alias("longest_prime_p1"),
        pl.col("board_p2").map_elements(_longest_prime, return_dtype=pl.Int32).alias("longest_prime_p2"),
        pl.col("board_p1").map_elements(_prime_location, return_dtype=pl.Int32).alias("prime_location_p1"),
        pl.col("board_p1").map_elements(_back_anchor, return_dtype=pl.Int32).alias("back_anchor_p1"),
        pl.col("board_p1").map_elements(_num_builders, return_dtype=pl.Int32).alias("num_builders_p1"),
    ])

    # --- Match context features ---
    gammon_threat = None
    gammon_risk = None

    has_win_g = "eval_win_g" in df.columns and "eval_win_bg" in df.columns
    has_lose_g = "eval_lose_g" in df.columns and "eval_lose_bg" in df.columns

    if has_win_g:
        df = df.with_columns(
            (pl.col("eval_win_g").cast(pl.Float64) + pl.col("eval_win_bg").cast(pl.Float64))
            .alias("gammon_threat")
        )
    if has_lose_g:
        df = df.with_columns(
            (pl.col("eval_lose_g").cast(pl.Float64) + pl.col("eval_lose_bg").cast(pl.Float64))
            .alias("gammon_risk")
        )
    if has_win_g and has_lose_g:
        df = df.with_columns(
            (pl.col("gammon_threat") - pl.col("gammon_risk")).alias("net_gammon")
        )

    # Cube leverage.
    if "cube_value" in df.columns and "score_away_p1" in df.columns:
        df = df.with_columns(
            (
                pl.col("cube_value").cast(pl.Float64)
                / pl.max_horizontal(pl.col("score_away_p1"), pl.col("score_away_p2"))
                  .cast(pl.Float64)
                  .clip(lower_bound=1)
            ).alias("cube_leverage")
        )

    # Match phase (contact/race/bearoff).
    phase = _classify_phase(df)
    df = df.with_columns(phase.alias("match_phase"))

    # --- Score features (require score_away_p1/p2 from games join) ---
    if "score_away_p1" in df.columns and "score_away_p2" in df.columns:
        df = df.with_columns([
            pl.when(pl.col("score_away_p1") < pl.col("score_away_p2"))
              .then(1)
              .when(pl.col("score_away_p2") < pl.col("score_away_p1"))
              .then(2)
              .otherwise(0)
              .cast(pl.Int8)
              .alias("leader"),

            (pl.col("score_away_p1") - pl.col("score_away_p2"))
              .abs()
              .alias("score_differential"),

            # Classic score flags.
            (
                (pl.col("score_away_p1") == 2) & (pl.col("score_away_p2") == 2)
            ).alias("is_dmp"),

            # Dead gammon risk: leader at 1-away, gammon doesn't help.
            (
                (pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1)
            ).alias("dgr"),
        ])

        if "crawford" in df.columns:
            df = df.with_columns([
                # Pre-Crawford: one player is 1-away, but not in Crawford game.
                (
                    ((pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1))
                    & ~pl.col("crawford")
                ).alias("is_pre_crawford"),

                # Post-Crawford: crawford column is False AND a previous game was Crawford.
                # Approximation: post-crawford if min(away) == 1 and not crawford.
                (
                    ((pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1))
                    & ~pl.col("crawford")
                ).alias("is_post_crawford"),
            ])

        # Take point match (row-by-row, float computation).
        take_points = [
            _take_point_match(r["score_away_p1"], r["score_away_p2"])
            for r in df.select(["score_away_p1", "score_away_p2"]).iter_rows(named=True)
        ]
        df = df.with_columns(
            pl.Series("take_point_match", take_points, dtype=pl.Float32)
        )

    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S0.4: Compute features for the mining study pipeline"
    )
    parser.add_argument("--parquet-dir", default="data/parquet",
                        help="Input Parquet directory (S0.2 output)")
    parser.add_argument("--output", default="data/parquet/positions_enriched",
                        help="Output directory for positions_enriched/*.parquet")
    parser.add_argument("--chunk-rows", type=int, default=100_000,
                        help="Rows per processing chunk (default: 100000)")
    parser.add_argument("--parts", type=int, default=16,
                        help="Number of output partitions (default: 16)")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    pos_glob = str(parquet_dir / "positions" / "part-*.parquet")
    games_path = parquet_dir / "games.parquet"

    for p in [games_path]:
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)
    pos_files = sorted((parquet_dir / "positions").glob("part-*.parquet"))
    if not pos_files:
        print("ERROR: no position part files found", file=sys.stderr)
        sys.exit(1)

    conn = duckdb.connect()
    conn.execute(f"CREATE VIEW positions AS SELECT * FROM read_parquet('{pos_glob}')")
    conn.execute(f"CREATE VIEW games AS SELECT * FROM read_parquet('{games_path}')")

    # Count total for progress reporting.
    total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    print(f"Processing {total:,} positions from {len(pos_files)} part files")

    # Join query: positions + games to get score columns.
    join_sql = """
        SELECT
            p.*,
            g.score_away_p1,
            g.score_away_p2,
            g.crawford
        FROM positions p
        LEFT JOIN games g ON g.game_id = p.game_id
        ORDER BY p.position_id
        LIMIT {limit} OFFSET {offset}
    """

    # One writer per partition.
    writers: dict[int, pq.ParquetWriter] = {}
    arrow_schema = None

    t0 = time.time()
    processed = 0
    offset = 0

    while offset < total:
        sql = join_sql.format(limit=args.chunk_rows, offset=offset)
        chunk = conn.execute(sql).pl()
        if chunk.is_empty():
            break

        enriched = compute_features(chunk)

        # Determine partition for each row.
        match_ids = enriched["game_id"].str.slice(0, 16).to_list()
        part_indices = [hash(mid) % args.parts for mid in match_ids]

        table = enriched.to_arrow()
        if arrow_schema is None:
            arrow_schema = table.schema

        # Distribute to partitions.
        i = 0
        while i < len(part_indices):
            p = part_indices[i]
            j = i + 1
            while j < len(part_indices) and part_indices[j] == p:
                j += 1
            slice_tbl = table.slice(i, j - i)
            if p not in writers:
                part_path = out_dir / f"part-{p:04d}.parquet"
                writers[p] = pq.ParquetWriter(str(part_path), arrow_schema, compression="snappy")
            writers[p].write_table(slice_tbl)
            i = j

        processed += len(chunk)
        offset += args.chunk_rows
        elapsed = time.time() - t0
        rate = processed / elapsed
        print(f"  {processed:,}/{total:,} ({rate:,.0f} rows/s) ...", end="\r")

    for w in writers.values():
        w.close()
    conn.close()

    elapsed = time.time() - t0
    n_cols = len(arrow_schema) if arrow_schema else 0
    print(f"\nDone: {processed:,} rows, {n_cols} columns, {len(writers)} parts, {elapsed:.1f}s")
    print(f"Output: {out_dir}/")

    # Quick verification.
    out_files = sorted(out_dir.glob("part-*.parquet"))
    n_out = sum(pq.read_metadata(str(f)).num_rows for f in out_files)
    assert n_out == processed, f"Row count mismatch: {n_out} vs {processed}"
    print(f"Verification: {n_out:,} rows across {len(out_files)} files ✓")


if __name__ == "__main__":
    main()
