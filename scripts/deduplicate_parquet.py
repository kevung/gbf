#!/usr/bin/env python3
"""S0.2b — Deduplicate matches, games, and positions Parquet files.

The BMAB dataset contains multiple .xg files for the same match
(same players/tournament/date). This script keeps one occurrence
per unique match_id / game_id / position_id.

Deduplication strategy:
  - matches: keep first occurrence per match_id
  - games: keep first occurrence per game_id (implies unique match_id)
  - positions: keep positions whose game_id is in deduplicated games

Output: overwrites matches.parquet and games.parquet in-place,
writes deduplicated positions to positions_dedup/ (new directory).

Usage:
    python scripts/deduplicate_parquet.py --parquet-dir data/parquet
"""

import argparse
import sys
import time
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


def deduplicate_matches(parquet_dir: Path) -> int:
    p = parquet_dir / "matches.parquet"
    df = pl.read_parquet(p)
    before = len(df)
    df = df.unique(subset=["match_id"], keep="first")
    after = len(df)
    df.write_parquet(p, compression="snappy")
    print(f"  matches: {before:,} → {after:,} unique ({before-after:,} removed)")
    return after


def deduplicate_games(parquet_dir: Path) -> int:
    p = parquet_dir / "games.parquet"
    df = pl.read_parquet(p)
    before = len(df)
    df = df.unique(subset=["game_id"], keep="first")
    after = len(df)
    df.write_parquet(p, compression="snappy")
    print(f"  games: {before:,} → {after:,} unique ({before-after:,} removed)")
    return after


def deduplicate_positions(parquet_dir: Path, chunk_rows: int = 200_000) -> int:
    """Filter positions to keep only game_ids present in deduplicated games."""
    pos_files = sorted((parquet_dir / "positions").glob("part-*.parquet"))
    if not pos_files:
        print("  ERROR: no position part files found", file=sys.stderr)
        return 0

    out_dir = parquet_dir / "positions_dedup"
    out_dir.mkdir(exist_ok=True)

    # Load valid game_ids from deduplicated games.
    games_df = pl.read_parquet(parquet_dir / "games.parquet")
    valid_game_ids = set(games_df["game_id"].to_list())
    print(f"  valid game_ids: {len(valid_game_ids):,}")

    conn = duckdb.connect()
    # Register valid game_ids as a DuckDB relation.
    valid_df = pl.DataFrame({"game_id": list(valid_game_ids)})
    conn.register("valid_game_ids", valid_df.to_arrow())

    writers: dict[int, pq.ParquetWriter] = {}
    arrow_schema = None
    total_in = 0
    total_out = 0
    t0 = time.time()

    for fi, pos_file in enumerate(pos_files):
        file_rows = pq.read_metadata(str(pos_file)).num_rows
        offset = 0
        while offset < file_rows:
            sql = f"""
                SELECT p.* FROM read_parquet('{pos_file}') p
                WHERE p.game_id IN (SELECT game_id FROM valid_game_ids)
                LIMIT {chunk_rows} OFFSET {offset}
            """
            chunk = conn.execute(sql).fetchdf()
            if chunk.empty:
                break

            total_in += min(chunk_rows, file_rows - offset)
            total_out += len(chunk)
            offset += chunk_rows

            if len(chunk) == 0:
                continue

            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if arrow_schema is None:
                arrow_schema = table.schema

            # Partition by game_id hash.
            game_ids = chunk["game_id"].tolist()
            part_indices = [hash(gid) % 16 for gid in game_ids]

            i = 0
            while i < len(part_indices):
                p_idx = part_indices[i]
                j = i + 1
                while j < len(part_indices) and part_indices[j] == p_idx:
                    j += 1
                slice_tbl = table.slice(i, j - i)
                if p_idx not in writers:
                    part_path = out_dir / f"part-{p_idx:04d}.parquet"
                    writers[p_idx] = pq.ParquetWriter(
                        str(part_path), arrow_schema, compression="snappy"
                    )
                writers[p_idx].write_table(slice_tbl)
                i = j

        elapsed = time.time() - t0
        rate = total_out / elapsed if elapsed > 0 else 0
        print(f"  file {fi+1}/{len(pos_files)}: {total_out:,} kept ({rate:,.0f} pos/s)", end="\r")

    for w in writers.values():
        w.close()
    conn.close()

    elapsed = time.time() - t0
    print(f"\n  positions: filtered {total_out:,} unique rows → {out_dir}/")
    print(f"  elapsed: {elapsed:.1f}s")
    return total_out


def main():
    parser = argparse.ArgumentParser(
        description="S0.2b: Deduplicate matches, games, and positions Parquet files"
    )
    parser.add_argument("--parquet-dir", default="data/parquet")
    parser.add_argument("--chunk-rows", type=int, default=200_000)
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    t0 = time.time()

    print("Deduplicating matches...")
    n_matches = deduplicate_matches(parquet_dir)

    print("Deduplicating games...")
    n_games = deduplicate_games(parquet_dir)

    print("Filtering positions to unique game_ids...")
    n_positions = deduplicate_positions(parquet_dir, args.chunk_rows)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s:")
    print(f"  {n_matches:,} unique matches")
    print(f"  {n_games:,} unique games")
    print(f"  {n_positions:,} unique positions")
    print(f"\nNext: re-run compute_features.py with --parquet-dir pointing to")
    print(f"  positions_dedup/ instead of positions/")


if __name__ == "__main__":
    main()
