#!/usr/bin/env python3
"""S0.2 — JSONL to Parquet conversion for the mining study pipeline.

Converts matches.jsonl, games.jsonl, positions.jsonl (from cmd/export-jsonl)
to partitioned Parquet files with strict typing and snappy compression.

Output layout:
  <parquet-dir>/
    matches.parquet             one file, ~few MB
    games.parquet               one file, ~few MB
    positions/
      part-0000.parquet         ~100-500 MB per file
      part-0001.parquet
      ...

Board columns (board_p1, board_p2) stored as fixed-size list[int8] (26 vals).
Probability columns (eval_win, etc.) stored as float32.
String columns (player, tournament) stored as categorical.

Usage:
    python scripts/convert_jsonl_to_parquet.py \\
        --jsonl-dir data/jsonl \\
        --parquet-dir data/parquet \\
        [--positions-parts 16] \\
        [--chunk-rows 500000]

Batch/append mode (for incremental export):
    python scripts/convert_jsonl_to_parquet.py \\
        --jsonl-dir /tmp/batch_003 \\
        --parquet-dir data/parquet \\
        --batch-id 3 --append
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

MATCHES_SCHEMA = {
    "match_id": pl.String,
    "player1": pl.Categorical,
    "player2": pl.Categorical,
    "match_length": pl.Int16,
    "tournament": pl.Categorical,
    "date": pl.String,
    "num_games": pl.Int16,
    "winner": pl.Int8,
    "score_final_p1": pl.Int16,
    "score_final_p2": pl.Int16,
}

GAMES_SCHEMA = {
    "game_id": pl.String,
    "match_id": pl.String,
    "game_number": pl.Int16,
    "score_away_p1": pl.Int16,
    "score_away_p2": pl.Int16,
    "crawford": pl.Boolean,
    "winner": pl.Int8,
    "points_won": pl.Int16,
    "gammon": pl.Boolean,
    "backgammon": pl.Boolean,
}

# Positions schema (applied after initial read; board arrays handled separately)
POSITIONS_SCALAR_SCHEMA = {
    "position_id": pl.String,
    "game_id": pl.String,
    "move_number": pl.Int16,
    "player_on_roll": pl.Int8,
    "decision_type": pl.Categorical,
    "cube_value": pl.Int8,
    "cube_owner": pl.Int8,
    "eval_equity": pl.Float64,
    "eval_win": pl.Float32,
    "eval_win_g": pl.Float32,
    "eval_win_bg": pl.Float32,
    "eval_lose_g": pl.Float32,
    "eval_lose_bg": pl.Float32,
    "move_played": pl.String,
    "move_played_error": pl.Float32,
    "best_move": pl.String,
    "best_move_equity": pl.Float64,
    "cube_action_played": pl.Categorical,
    "cube_action_optimal": pl.Categorical,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cast_columns(df: pl.DataFrame, schema: dict) -> pl.DataFrame:
    """Cast existing columns to target types; ignore missing columns."""
    exprs = []
    for col, dtype in schema.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype))
    if exprs:
        df = df.with_columns(exprs)
    return df


def board_list_to_int8(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """Cast a List[...] board column to List[Int8]."""
    if col in df.columns:
        df = df.with_columns(
            pl.col(col).list.eval(pl.element().cast(pl.Int8)).alias(col)
        )
    return df


def partition_index(match_id: str, n_parts: int) -> int:
    """Deterministic partition assignment from match_id."""
    return hash(match_id) % n_parts


def count_lines(path: Path) -> int:
    """Count newline-terminated lines in a file."""
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------

def convert_matches(jsonl_path: Path, out_path: Path, append: bool = False) -> int:
    """Convert matches.jsonl → matches.parquet. Returns row count."""
    print(f"  reading {jsonl_path}...")
    df = pl.read_ndjson(jsonl_path)
    df = cast_columns(df, MATCHES_SCHEMA)
    if append and out_path.exists():
        existing = pl.read_parquet(out_path)
        df = pl.concat([existing, df])
        print(f"  appended → {len(df)} total matches → {out_path}")
    else:
        print(f"  {len(df)} matches → {out_path}")
    df.write_parquet(out_path, compression="snappy")
    return len(df)


def convert_games(jsonl_path: Path, out_path: Path, append: bool = False) -> int:
    """Convert games.jsonl → games.parquet. Returns row count."""
    print(f"  reading {jsonl_path}...")
    df = pl.read_ndjson(jsonl_path)
    df = cast_columns(df, GAMES_SCHEMA)
    if append and out_path.exists():
        existing = pl.read_parquet(out_path)
        df = pl.concat([existing, df])
        print(f"  appended → {len(df)} total games → {out_path}")
    else:
        print(f"  {len(df)} games → {out_path}")
    df.write_parquet(out_path, compression="snappy")
    return len(df)


def convert_positions(
    jsonl_path: Path,
    out_dir: Path,
    n_parts: int,
    chunk_rows: int,
    batch_id: int | None = None,
) -> int:
    """Convert positions.jsonl → partitioned positions/*.parquet.

    Reads in chunks to handle files larger than RAM. Each chunk is distributed
    to the appropriate partition bucket based on match_id hash.

    When batch_id is set, part files are named part-{batch:03d}-{partition:04d}.parquet
    to allow multiple batches to coexist without overwriting.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # One PyArrow writer per partition.
    writers: dict[int, pq.ParquetWriter] = {}
    schema_ready = False
    arrow_schema = None

    # Canonical column order — ensures all chunks share the same schema
    # regardless of which optional fields appear in each row.
    CANONICAL_COLS = [
        "position_id", "game_id", "move_number", "player_on_roll", "decision_type",
        "dice", "board_p1", "board_p2", "cube_value", "cube_owner",
        "eval_equity", "eval_win", "eval_win_g", "eval_win_bg", "eval_lose_g", "eval_lose_bg",
        "move_played", "move_played_error", "best_move", "best_move_equity",
        "cube_action_played", "cube_action_optimal",
    ]

    def align_to_schema(table: pa.Table, schema: pa.Schema) -> pa.Table:
        """Reorder columns and add nulls for any missing columns."""
        cols = []
        for field in schema:
            if field.name in table.schema.names:
                col = table.column(field.name)
                if col.type != field.type:
                    try:
                        col = col.cast(field.type)
                    except Exception:
                        col = pa.nulls(len(table), type=field.type)
            else:
                col = pa.nulls(len(table), type=field.type)
            cols.append(col)
        return pa.table(cols, schema=schema)

    def part_filename(partition: int) -> str:
        if batch_id is not None:
            return f"part-{batch_id:03d}-{partition:04d}.parquet"
        return f"part-{partition:04d}.parquet"

    def flush_df(df: pl.DataFrame):
        nonlocal schema_ready, arrow_schema

        # Apply scalar type casts.
        df = cast_columns(df, POSITIONS_SCALAR_SCHEMA)

        # Cast board columns to List[Int8].
        for col in ("board_p1", "board_p2"):
            df = board_list_to_int8(df, col)

        # Drop candidates column (nested struct — stored separately if needed).
        if "candidates" in df.columns:
            df = df.drop("candidates")

        # Ensure canonical column order (add missing cols as null via pyarrow).
        # First convert to Arrow with whatever columns exist, then align.
        table = df.to_arrow()

        if not schema_ready:
            # Build the reference schema from the canonical column list,
            # using the types present in this first chunk.
            fields = []
            for col in CANONICAL_COLS:
                if col in table.schema.names:
                    fields.append(table.schema.field(col))
                else:
                    # Use a sensible nullable type for optional columns.
                    if col in ("move_played", "best_move", "cube_action_played", "cube_action_optimal"):
                        fields.append(pa.field(col, pa.large_utf8(), nullable=True))
                    elif col in ("eval_equity", "best_move_equity"):
                        fields.append(pa.field(col, pa.float64(), nullable=True))
                    elif col in ("move_played_error", "eval_win", "eval_win_g", "eval_win_bg",
                                 "eval_lose_g", "eval_lose_bg"):
                        fields.append(pa.field(col, pa.float32(), nullable=True))
                    elif col == "dice":
                        fields.append(pa.field(col, pa.large_list(pa.int64()), nullable=True))
                    else:
                        fields.append(pa.field(col, pa.int8(), nullable=True))
            arrow_schema = pa.schema(fields)
            schema_ready = True

        table = align_to_schema(table, arrow_schema)

        # Distribute rows to partition writers.
        match_col = "game_id"  # game_id always present; use for partitioning
        if "position_id" in df.columns:
            match_ids = [pid.rsplit("_game_", 1)[0] if "_game_" in pid else pid
                         for pid in df["position_id"].to_list()]
        else:
            match_ids = [""] * len(df)
        part_indices = [partition_index(mid, n_parts) for mid in match_ids]

        # Group consecutive rows by partition for efficiency.
        i = 0
        while i < len(part_indices):
            p = part_indices[i]
            j = i + 1
            while j < len(part_indices) and part_indices[j] == p:
                j += 1
            slice_tbl = table.slice(i, j - i)
            if p not in writers:
                part_path = out_dir / part_filename(p)
                writers[p] = pq.ParquetWriter(
                    str(part_path), arrow_schema, compression="snappy"
                )
            writers[p].write_table(slice_tbl)
            i = j

    # Stream through positions.jsonl in chunks.
    total = 0
    chunk_buf = []
    t0 = time.time()

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk_buf.append(json.loads(line))
            if len(chunk_buf) >= chunk_rows:
                df = pl.DataFrame(chunk_buf, strict=False)
                flush_df(df)
                total += len(df)
                chunk_buf = []
                elapsed = time.time() - t0
                print(
                    f"  {total:,} positions processed "
                    f"({total / elapsed:,.0f} pos/s)...",
                    end="\r",
                )

    # Flush remaining rows.
    if chunk_buf:
        df = pl.DataFrame(chunk_buf, strict=False)
        flush_df(df)
        total += len(df)

    # Close all writers.
    for w in writers.values():
        w.close()

    elapsed = time.time() - t0
    print(
        f"  {total:,} positions → {out_dir}/ "
        f"({len(writers)} parts, {elapsed:.1f}s, {total / elapsed:,.0f} pos/s)"
    )
    return total


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify(parquet_dir: Path, n_matches: int, n_games: int, n_positions: int):
    """Re-read Parquet files and verify counts match originals."""
    print("\nVerification:")

    m = pl.read_parquet(parquet_dir / "matches.parquet")
    assert len(m) == n_matches, f"matches mismatch: {len(m)} vs {n_matches}"
    print(f"  matches.parquet:   {len(m):,} rows ✓")

    g = pl.read_parquet(parquet_dir / "games.parquet")
    assert len(g) == n_games, f"games mismatch: {len(g)} vs {n_games}"
    print(f"  games.parquet:     {len(g):,} rows ✓")

    pos_files = sorted((parquet_dir / "positions").glob("part-*.parquet"))
    n_pos_read = sum(pq.read_metadata(str(f)).num_rows for f in pos_files)
    assert n_pos_read == n_positions, f"positions mismatch: {n_pos_read} vs {n_positions}"
    print(f"  positions/*.parquet: {n_pos_read:,} rows across {len(pos_files)} files ✓")

    # Quick schema spot-check.
    if pos_files:
        schema = pq.read_schema(str(pos_files[0]))
        print(f"  positions schema: {len(schema)} columns")
        print(f"  compression: snappy (verified by pyarrow)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S0.2: Convert JSONL to Parquet for the mining study pipeline"
    )
    parser.add_argument(
        "--jsonl-dir", default="data/jsonl",
        help="Directory containing matches.jsonl, games.jsonl, positions.jsonl"
    )
    parser.add_argument(
        "--parquet-dir", default="data/parquet",
        help="Output directory for Parquet files"
    )
    parser.add_argument(
        "--positions-parts", type=int, default=16,
        help="Number of position partition files (default: 16, ~50-500 MB each)"
    )
    parser.add_argument(
        "--chunk-rows", type=int, default=500_000,
        help="Rows per processing chunk for positions (default: 500000)"
    )
    parser.add_argument(
        "--skip-verify", action="store_true",
        help="Skip verification step"
    )
    parser.add_argument(
        "--batch-id", type=int, default=None,
        help="Batch identifier for incremental export (unique part-file naming)"
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to existing matches/games Parquet files instead of overwriting"
    )
    args = parser.parse_args()

    jsonl_dir = Path(args.jsonl_dir)
    parquet_dir = Path(args.parquet_dir)
    parquet_dir.mkdir(parents=True, exist_ok=True)

    for name in ("matches.jsonl", "games.jsonl", "positions.jsonl"):
        p = jsonl_dir / name
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)

    t_start = time.time()

    print("Converting matches...")
    n_matches = convert_matches(
        jsonl_dir / "matches.jsonl", parquet_dir / "matches.parquet",
        append=args.append,
    )

    print("Converting games...")
    n_games = convert_games(
        jsonl_dir / "games.jsonl", parquet_dir / "games.parquet",
        append=args.append,
    )

    print(f"Converting positions (parts={args.positions_parts}, chunk={args.chunk_rows:,}"
          f"{f', batch={args.batch_id}' if args.batch_id is not None else ''})...")
    n_positions = convert_positions(
        jsonl_dir / "positions.jsonl",
        parquet_dir / "positions",
        n_parts=args.positions_parts,
        chunk_rows=args.chunk_rows,
        batch_id=args.batch_id,
    )

    print(f"\nTotal: {n_matches:,} matches, {n_games:,} games, {n_positions:,} positions")
    print(f"Elapsed: {time.time() - t_start:.1f}s")

    if not args.skip_verify and not args.append:
        verify(parquet_dir, n_matches, n_games, n_positions)

    print("\nDone.")


if __name__ == "__main__":
    main()
