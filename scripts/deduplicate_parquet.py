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

import polars as pl


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
    """Deduplicate positions by keeping the first occurrence of each game_id.

    BMAB has ~5x duplicate matches: the same game_id appears in 5 different
    batches. We process files in sorted (batch) order and keep only positions
    whose game_id has not been seen yet. This is equivalent to keeping positions
    from the first batch that processed each match.

    Memory: seen_game_ids grows to ~268K strings ≈ 16 MB. Peak RAM is negligible.
    """
    pos_files = sorted((parquet_dir / "positions").glob("part-*.parquet"))
    if not pos_files:
        print("  ERROR: no position part files found", file=sys.stderr)
        return 0

    out_dir = parquet_dir / "positions_dedup"
    out_dir.mkdir(exist_ok=True)

    seen_game_ids: set = set()
    total_in = 0
    total_out = 0
    t0 = time.time()

    for fi, pos_file in enumerate(pos_files):
        df = pl.read_parquet(pos_file)
        total_in += len(df)

        # Find game_ids in this file that haven't been seen yet.
        file_game_ids = set(df["game_id"].unique().to_list())
        new_game_ids = file_game_ids - seen_game_ids

        if new_game_ids:
            filtered = df.filter(pl.col("game_id").is_in(list(new_game_ids)))
            seen_game_ids.update(new_game_ids)
            out_file = out_dir / pos_file.name
            filtered.write_parquet(out_file, compression="snappy")
            total_out += len(filtered)
            del filtered
        del df

        if (fi + 1) % 200 == 0 or (fi + 1) == len(pos_files):
            elapsed = time.time() - t0
            rate = total_out / elapsed if elapsed > 0 else 0
            pct = total_out / total_in * 100 if total_in > 0 else 0
            print(
                f"  file {fi+1}/{len(pos_files)}: {total_out:,} kept / {total_in:,} scanned"
                f" ({pct:.1f}%, {rate:,.0f} pos/s)",
                flush=True,
            )

    elapsed = time.time() - t0
    print(f"\n  positions: {total_out:,} unique rows → {out_dir}/", flush=True)
    print(f"  elapsed: {elapsed:.1f}s", flush=True)
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
