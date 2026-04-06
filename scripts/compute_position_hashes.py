#!/usr/bin/env python3
"""S0.6 — Position hashing + convergence index for the mining study pipeline.

Computes a canonical xxhash64 for each position (always from the on-roll
player's perspective) and builds a convergence index showing how often the
same exact position recurs across different games and matches.

Canonical hash key (32 bytes):
  26 bytes  board_p1 (int8, on-roll player's perspective)
   1 byte   cube_value_log2 (0-6)
   1 byte   cube_owner (0=center, 1=on-roll, 2=opponent)
   2 bytes  score_away_p1 (on-roll, uint16, 0 for money games)
   2 bytes  score_away_p2 (opponent, uint16)

Outputs
-------
position_hashes.parquet   — one row per position:
    position_id, position_hash (int64), game_id, match_id, move_number,
    decision_type, move_number

convergence_index.parquet — one row per unique hash:
    position_hash (int64), occurrence_count, distinct_games, distinct_matches
    (ordered by occurrence_count DESC)

Preliminary report printed to stdout:
  - Unique vs shared positions
  - Top 20 most frequent hashes (crossroads)
  - Convergence by game phase (if enriched positions available)

Usage::

    python scripts/compute_position_hashes.py \\
        --parquet-dir data/parquet \\
        --output data/parquet \\
        [--chunk-rows 200000]
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import xxhash


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

# Canonical key layout (32 bytes total):
#   [0:26]  board_p1 as signed int8
#   [26]    cube_value_log2 (uint8)
#   [27]    cube_owner      (uint8: 0=center,1=on-roll,2=opp)
#   [28:30] score_away_p1   (uint16 LE)
#   [30:32] score_away_p2   (uint16 LE)
_STRUCT_FMT = "26b BB HH"
_PACK = struct.Struct(_STRUCT_FMT)


def _cube_log2(cube_value: int) -> int:
    """Return log2 of cube value (1→0, 2→1, 4→2, …)."""
    if cube_value <= 1:
        return 0
    return int(math.log2(max(1, cube_value)))


def _canonical_hash(row: dict) -> int:
    """Compute xxhash64 of the canonical position key.

    Returns a signed int64 (DuckDB/Parquet compatible).
    """
    board = row["board_p1"]  # list of 26 int8
    cube_log2 = _cube_log2(row.get("cube_value") or 1)
    cube_owner = int(row.get("cube_owner") or 0)
    away_p1 = int(row.get("score_away_p1") or 0)
    away_p2 = int(row.get("score_away_p2") or 0)

    # Clamp values to valid ranges.
    away_p1 = max(0, min(65535, away_p1))
    away_p2 = max(0, min(65535, away_p2))

    key = _PACK.pack(*board, cube_log2, cube_owner, away_p1, away_p2)
    h = xxhash.xxh64(key).intdigest()

    # Reinterpret as signed int64 (same as GBF Zobrist convention).
    if h >= (1 << 63):
        h -= (1 << 64)
    return h


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

_HASH_SCHEMA = pa.schema([
    pa.field("position_id", pa.string()),
    pa.field("position_hash", pa.int64()),
    pa.field("game_id", pa.string()),
    pa.field("match_id", pa.string()),
    pa.field("move_number", pa.int16()),
    pa.field("decision_type", pa.string()),
])


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def compute_hashes(
    conn: duckdb.DuckDBPyConnection,
    hash_writer: pq.ParquetWriter,
    chunk_rows: int,
) -> int:
    """Stream positions+games, compute hashes, write position_hashes.parquet."""

    total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    join_sql = """
        SELECT
            p.position_id, p.game_id, p.move_number, p.decision_type,
            p.board_p1, p.cube_value, p.cube_owner,
            g.match_id, g.score_away_p1, g.score_away_p2
        FROM positions p
        LEFT JOIN games g ON g.game_id = p.game_id
        ORDER BY p.position_id
        LIMIT {limit} OFFSET {offset}
    """

    processed = 0
    t0 = time.time()

    while processed < total:
        sql = join_sql.format(limit=chunk_rows, offset=processed)
        chunk = conn.execute(sql).pl()
        if chunk.is_empty():
            break

        hashes = [_canonical_hash(r) for r in chunk.iter_rows(named=True)]

        table = pa.table({
            "position_id":   chunk["position_id"].to_list(),
            "position_hash": hashes,
            "game_id":       chunk["game_id"].to_list(),
            "match_id":      chunk["match_id"].to_list(),
            "move_number":   chunk["move_number"].to_list(),
            "decision_type": chunk["decision_type"].to_list(),
        }, schema=_HASH_SCHEMA)

        hash_writer.write_table(table)
        processed += len(chunk)
        elapsed = time.time() - t0
        print(f"  {processed:,}/{total:,} ({processed/elapsed:,.0f} pos/s) ...", end="\r")

    print(f"  {processed:,}/{total:,} done in {time.time()-t0:.1f}s            ")
    return processed


def build_convergence_index(
    conn: duckdb.DuckDBPyConnection,
    hash_path: str,
    out_path: Path,
):
    """GROUP BY position_hash → convergence_index.parquet."""
    conn.execute(
        f"CREATE OR REPLACE VIEW hashes AS SELECT * FROM read_parquet('{hash_path}')"
    )
    df = conn.execute("""
        SELECT
            position_hash,
            COUNT(*)            AS occurrence_count,
            COUNT(DISTINCT game_id)  AS distinct_games,
            COUNT(DISTINCT match_id) AS distinct_matches
        FROM hashes
        GROUP BY position_hash
        ORDER BY occurrence_count DESC
    """).pl()

    df = df.with_columns([
        pl.col("occurrence_count").cast(pl.Int32),
        pl.col("distinct_games").cast(pl.Int32),
        pl.col("distinct_matches").cast(pl.Int32),
    ])
    df.write_parquet(str(out_path), compression="snappy")
    return df


def print_report(
    conn: duckdb.DuckDBPyConnection,
    conv_df: pl.DataFrame,
    hash_path: str,
):
    """Print preliminary convergence analysis."""
    print("\n" + "=" * 60)
    print("  S0.6 — Convergence Analysis Report")
    print("=" * 60)

    total = conv_df["occurrence_count"].sum()
    unique = len(conv_df)
    shared = (conv_df["occurrence_count"] > 1).sum()
    singletons = (conv_df["occurrence_count"] == 1).sum()

    print(f"\n  Total positions hashed:   {total:>12,}")
    print(f"  Unique position hashes:   {unique:>12,}  ({100*unique/max(total,1):.1f}% of total)")
    print(f"  Positions seen > 1 time:  {shared:>12,}  ({100*shared/max(unique,1):.1f}% of unique hashes)")
    print(f"  Singleton positions:      {singletons:>12,}  ({100*singletons/max(unique,1):.1f}% of unique hashes)")

    # Occurrence distribution.
    print("\n  Occurrence frequency distribution:")
    bins = [(1, 1), (2, 2), (3, 5), (6, 10), (11, 50), (51, 1000), (1001, None)]
    for lo, hi in bins:
        if hi is None:
            mask = conv_df["occurrence_count"] >= lo
            label = f"≥{lo}"
        else:
            mask = (conv_df["occurrence_count"] >= lo) & (conv_df["occurrence_count"] <= hi)
            label = f"{lo}" if lo == hi else f"{lo}–{hi}"
        n_hashes = mask.sum()
        n_pos = conv_df.filter(mask)["occurrence_count"].sum()
        print(f"    {label:>8}× :  {n_hashes:>8,} hashes  ({n_pos:>10,} positions)")

    # Top 20 crossroads.
    print("\n  Top 20 most frequent positions (crossroads):")
    print(f"  {'hash':>20}  {'occurrences':>12}  {'games':>8}  {'matches':>8}")
    for row in conv_df.head(20).iter_rows(named=True):
        print(
            f"  {row['position_hash']:>20}  {row['occurrence_count']:>12,}"
            f"  {row['distinct_games']:>8,}  {row['distinct_matches']:>8,}"
        )

    # Positions appearing in ≥ 3 distinct matches (trajectory threshold).
    threshold = 3
    crossroads_3 = (conv_df["distinct_matches"] >= threshold).sum()
    print(f"\n  Positions in ≥{threshold} distinct matches (trajectory nodes): {crossroads_3:,}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S0.6: Compute canonical position hashes and convergence index"
    )
    parser.add_argument("--parquet-dir", default="data/parquet",
                        help="Parquet directory (S0.2 output)")
    parser.add_argument("--output", default="data/parquet",
                        help="Output directory for hash files (default: same as --parquet-dir)")
    parser.add_argument("--chunk-rows", type=int, default=200_000,
                        help="Rows per chunk (default: 200000)")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    pos_glob = str(parquet_dir / "positions" / "part-*.parquet")
    games_path = parquet_dir / "games.parquet"

    pos_files = sorted((parquet_dir / "positions").glob("part-*.parquet"))
    if not pos_files or not games_path.exists():
        print("ERROR: positions/ or games.parquet not found", file=sys.stderr)
        sys.exit(1)

    conn = duckdb.connect()
    conn.execute(f"CREATE VIEW positions AS SELECT * FROM read_parquet('{pos_glob}')")
    conn.execute(f"CREATE VIEW games AS SELECT * FROM read_parquet('{games_path}')")

    hash_path = str(out_dir / "position_hashes.parquet")
    conv_path = out_dir / "convergence_index.parquet"

    # Step 1: compute and write position hashes.
    print(f"Step 1: computing canonical hashes (chunk={args.chunk_rows:,}) ...")
    t0 = time.time()
    with pq.ParquetWriter(hash_path, _HASH_SCHEMA, compression="snappy") as writer:
        n = compute_hashes(conn, writer, args.chunk_rows)
    print(f"  → position_hashes.parquet: {n:,} rows in {time.time()-t0:.1f}s")

    # Step 2: build convergence index via GROUP BY.
    print("\nStep 2: building convergence index ...")
    t1 = time.time()
    conv_df = build_convergence_index(conn, hash_path, conv_path)
    print(f"  → convergence_index.parquet: {len(conv_df):,} unique hashes in {time.time()-t1:.1f}s")

    # Step 3: print analysis report.
    print_report(conn, conv_df, hash_path)

    conn.close()


if __name__ == "__main__":
    main()
