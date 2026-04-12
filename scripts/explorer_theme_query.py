#!/usr/bin/env python3
"""Helper script for the GBF Explorer to query themed positions from Parquet files.

Called by the Go backend as a subprocess. Reads partition-aligned position_themes
and positions_enriched parquets, converts board state to the Board.svelte format,
and outputs a JSON array to stdout.

Usage:
    explorer_theme_query.py <theme> <n> <data_dir>

    theme    — theme name without prefix, e.g. "blitz" (matches column theme_blitz)
    n        — number of positions to return
    data_dir — path to the data/ directory (contains parquet/ and themes/ subdirs)
"""
import sys
import json
import os
import random
import glob

import polars as pl


def cube_log2(cube_value: int) -> int:
    if cube_value is None or cube_value <= 0:
        return 0
    v = int(cube_value)
    return max(0, v.bit_length() - 1)


def board_to_display(b1: list[int], b2: list[int]) -> list[int]:
    """Convert (board_p1, board_p2) 26-element lists to Board.svelte format.

    board_p1/board_p2 layout (26 elements, 1-indexed):
      index 0  : unused (always 0)
      index 1–24: checkers at point 1–24 (from each player's own perspective)
      index 25  : checkers on the bar

    Board.svelte board[i] (0-indexed, i = display point index 0–23):
      positive = X (player on roll / P1) checkers
      negative = O (P2) checkers

    P2 point j maps to P1 display index (24 - j), so:
      board[i] = b1[i+1] - b2[24-i]   for i in 0..23
    """
    return [int(b1[i + 1]) - int(b2[24 - i]) for i in range(24)]


def row_to_position(row: dict) -> dict:
    b1 = row["board_p1"]
    b2 = row["board_p2"]
    board = board_to_display(b1, b2)
    bar_x = int(b1[25]) if len(b1) > 25 else 0
    bar_o = int(b2[25]) if len(b2) > 25 else 0

    cv = row.get("cube_value")
    cv = int(cv) if cv is not None else 1
    co = row.get("cube_owner")
    co = int(co) if co is not None else 0
    # XG cube_owner: 0=centred, 1=P1/X, -1 or 2=P2/O → normalise to 0/1/2
    if co == -1:
        co = 2

    err = row.get("move_played_error")
    err = float(err) if err is not None else 0.0
    win = row.get("eval_win")
    win = float(win) if win is not None else 0.5

    pt = row.get("primary_theme")
    tc = row.get("theme_count")

    return {
        "position_id": row["position_id"],
        "board": board,
        "bar_x": bar_x,
        "bar_o": bar_o,
        "borne_off_x": int(row["num_borne_off_p1"]),
        "borne_off_o": int(row["num_borne_off_p2"]),
        "away_x": int(row["score_away_p1"]),
        "away_o": int(row["score_away_p2"]),
        "pip_x": int(row["pip_count_p1"]),
        "pip_o": int(row["pip_count_p2"]),
        "cube_log2": cube_log2(cv),
        "cube_owner": co,
        "primary_theme": str(pt) if pt is not None else "",
        "theme_count": int(tc) if tc is not None else 1,
        "error": err,
        "eval_win": win,
    }


ENRICHED_COLS = [
    "position_id",
    "board_p1",
    "board_p2",
    "num_on_bar_p1",
    "num_on_bar_p2",
    "num_borne_off_p1",
    "num_borne_off_p2",
    "pip_count_p1",
    "pip_count_p2",
    "score_away_p1",
    "score_away_p2",
    "move_played_error",
    "eval_win",
    "cube_value",
    "cube_owner",
]


def main() -> None:
    if len(sys.argv) != 4:
        sys.stdout.write(json.dumps({"error": "usage: theme n data_dir"}))
        sys.exit(1)

    theme = sys.argv[1]
    n = int(sys.argv[2])
    data_dir = sys.argv[3]
    theme_col = f"theme_{theme}"

    theme_files = sorted(
        glob.glob(os.path.join(data_dir, "parquet", "position_themes", "part-*.parquet"))
    )
    enriched_files = sorted(
        glob.glob(os.path.join(data_dir, "parquet", "positions_enriched", "part-*.parquet"))
    )

    if not theme_files:
        sys.stdout.write(json.dumps({"error": "position_themes parquet not found in " + data_dir}))
        sys.exit(1)
    if not enriched_files:
        sys.stdout.write(json.dumps({"error": "positions_enriched parquet not found in " + data_dir}))
        sys.exit(1)

    # Pair by partition index (both dirs have the same 232-partition structure)
    indices = list(range(min(len(theme_files), len(enriched_files))))
    random.shuffle(indices)

    rows: list[dict] = []

    for idx in indices:
        tf = theme_files[idx]
        ef = enriched_files[idx]

        try:
            themes = pl.read_parquet(
                tf, columns=[theme_col, "position_id", "primary_theme", "theme_count"]
            )
        except Exception:
            continue

        matched_themes = themes.filter(pl.col(theme_col) == True)
        if len(matched_themes) == 0:
            continue

        matched_ids = matched_themes["position_id"]

        try:
            enriched = pl.read_parquet(ef, columns=ENRICHED_COLS)
        except Exception:
            continue

        matched_enriched = enriched.filter(pl.col("position_id").is_in(matched_ids.to_list()))
        if len(matched_enriched) == 0:
            continue

        theme_sub = matched_themes.select(["position_id", "primary_theme", "theme_count"])
        joined = matched_enriched.join(theme_sub, on="position_id", how="left")

        for row in joined.iter_rows(named=True):
            try:
                rows.append(row_to_position(row))
            except Exception:
                continue

        if len(rows) >= n * 3:
            break

    if len(rows) > n:
        rows = random.sample(rows, n)

    sys.stdout.write(json.dumps(rows))


if __name__ == "__main__":
    main()
