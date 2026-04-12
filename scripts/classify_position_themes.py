#!/usr/bin/env python3
"""S1.9 — Thematic Position Classification.

Reads ``positions_enriched/*.parquet`` and labels every position with up
to 26 canonical backgammon themes (The Opening, Blitz, Back Games,
etc.). Outputs a parquet mirror partitioned identically to the input
plus two summary CSVs.

Two modes:

  default          Structural + new-feature pass (23 Phase-A themes +
                   three trajectory themes initialised to False).

  --trajectory     Game-ordered window pass that populates the three
                   history-dependent themes (Breaking Anchor,
                   Post-Blitz Turnaround, Post-Ace-Point Games). Must
                   be run after the default pass has completed.

Canonical theme definitions and citations live in
``docs/themes/theme_dictionary.md``. Predicates are in
``scripts/lib/theme_rules.py``; board-scan helpers in
``scripts/lib/board_predicates.py``.

Usage::

    python scripts/classify_position_themes.py \\
        --enriched data/parquet/positions_enriched \\
        --output   data/parquet/position_themes \\
        --summary  data/themes

    python scripts/classify_position_themes.py \\
        --output   data/parquet/position_themes \\
        --enriched data/parquet/positions_enriched \\
        --trajectory
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# Make scripts/lib importable when running as `python scripts/classify_position_themes.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.board_predicates import can_hit_this_roll, max_gap_p1  # noqa: E402
from lib.theme_rules import (  # noqa: E402
    ALL_THEME_COLUMNS,
    PHASE_A_THEMES,
    PHASE_B_THEMES,
    primary_theme_expr,
    theme_count_expr,
)


# Columns read from positions_enriched. Keep minimal — the board_p1/p2
# arrays are by far the heaviest columns and we only need them for the
# two ancillary features.
READ_COLUMNS = [
    "position_id", "game_id", "move_number", "player_on_roll", "decision_type",
    "dice", "board_p1", "board_p2",
    "eval_win", "gammon_threat", "gammon_risk",
    "cube_action_optimal",
    "match_phase",
    "pip_count_p1", "pip_count_p2", "pip_count_diff",
    "num_on_bar_p1", "num_on_bar_p2",
    "num_borne_off_p1", "num_borne_off_p2",
    "num_blots_p1", "num_blots_p2",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "longest_prime_p1", "longest_prime_p2",
    "back_anchor_p1", "num_checkers_back_p1",
    "num_builders_p1", "outfield_blots_p1",
]

# Columns kept in the final position_themes parquet (inputs are
# dropped to keep the themes dataset narrow — join on position_id
# to re-attach enriched features).
KEY_COLUMNS = ["position_id", "game_id", "move_number"]


def _ancillary_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Add the columns theme predicates reference that are not in
    positions_enriched: num_checkers_back_p2, anchors_back_p1,
    ace_anchor_only_p1, max_gap_p1, can_hit_this_roll_p1.
    """
    # num_checkers_back_p2: sum of board_p2[19..24] (p2's own back).
    p2_back = sum(
        pl.col("board_p2").list.get(i).cast(pl.Int32)
        for i in range(19, 25)
    )

    # anchors_back_p1: count of board_p1[20..24] >= 2.
    anchors = sum(
        (pl.col("board_p1").list.get(i).cast(pl.Int32) >= 2).cast(pl.Int32)
        for i in range(20, 25)
    )

    # ace_anchor_only_p1: B1[24] >= 2 AND B1[19..23] all < 2.
    b1_24_made = pl.col("board_p1").list.get(24).cast(pl.Int32) >= 2
    no_other_back = sum(
        (pl.col("board_p1").list.get(i).cast(pl.Int32) >= 2).cast(pl.Int32)
        for i in range(19, 24)
    ) == 0

    df = df.with_columns([
        p2_back.alias("num_checkers_back_p2"),
        anchors.alias("anchors_back_p1"),
        (b1_24_made & no_other_back).alias("ace_anchor_only_p1"),
    ])

    # max_gap_p1 and can_hit_this_roll_p1 need per-row Python — use
    # map_elements. Only a couple of hundred nanoseconds per row, but
    # these run over every row, so use them sparingly.
    df = df.with_columns([
        pl.col("board_p1")
          .map_elements(max_gap_p1, return_dtype=pl.Int8)
          .alias("max_gap_p1"),
        pl.struct(["board_p1", "board_p2", "dice"])
          .map_elements(
              lambda s: can_hit_this_roll(s["board_p1"], s["board_p2"], s["dice"]),
              return_dtype=pl.Boolean,
          )
          .alias("can_hit_this_roll_p1"),
    ])

    return df


def _apply_phase_a_themes(df: pl.DataFrame) -> pl.DataFrame:
    """Evaluate each Phase-A theme predicate as a boolean column."""
    exprs = [fn().fill_null(False).alias(name) for name, fn in PHASE_A_THEMES]
    df = df.with_columns(exprs)

    # various_endgames acts as a catch-all among contact endgame themes:
    # suppress it when any more specific contact-endgame theme fires.
    specific_endgame = (
        pl.col("theme_bearoff_vs_contact")
        | pl.col("theme_back_game")
        | pl.col("theme_ace_point")
        | pl.col("theme_containment")
        | pl.col("theme_holding")
    )
    df = df.with_columns(
        (pl.col("theme_various_endgames") & ~specific_endgame)
        .alias("theme_various_endgames")
    )
    return df


def _init_phase_b_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Populate Phase B theme columns with False so schema is stable
    after the structural pass."""
    return df.with_columns([
        pl.lit(False).alias(name) for name, _ in PHASE_B_THEMES
    ])


def _derived_columns(df: pl.DataFrame) -> pl.DataFrame:
    cols_present = df.columns
    return df.with_columns([
        primary_theme_expr(cols_present).alias("primary_theme"),
        theme_count_expr(cols_present).cast(pl.Int8).alias("theme_count"),
    ])


def _output_columns(df: pl.DataFrame) -> list[str]:
    keep = KEY_COLUMNS + ALL_THEME_COLUMNS + [
        "primary_theme", "theme_count",
        "max_gap_p1", "can_hit_this_roll_p1",
    ]
    return [c for c in keep if c in df.columns]


def classify_partition(pos_file: Path, out_file: Path) -> int:
    # Read required columns (skip missing gracefully).
    schema_cols = pl.read_parquet(pos_file, n_rows=1).columns
    cols = [c for c in READ_COLUMNS if c in schema_cols]
    df = pl.read_parquet(pos_file, columns=cols)

    df = _ancillary_columns(df)
    df = _apply_phase_a_themes(df)
    df = _init_phase_b_columns(df)
    df = _derived_columns(df)

    out_df = df.select(_output_columns(df))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_df.write_parquet(out_file, compression="snappy")
    return len(out_df)


# ── Trajectory pass (Phase B) ──────────────────────────────────────

TRAJECTORY_K = 8  # moves to look back for Post-Blitz / Post-Ace-Point.

# Columns read from enriched for the trajectory predicates.
TRAJECTORY_ENRICHED_COLS = [
    "position_id", "game_id", "move_number",
    "match_phase", "eval_win", "pip_count_p1",
    "num_checkers_back_p1", "num_on_bar_p2",
]


def _trajectory_update_partition(
    themes_file: Path,
    enriched_file: Path,
) -> int:
    """Compute Phase B themes for one partition, in place.

    Approximation: windows are evaluated within the partition only.
    Games that cross a partition boundary lose at most K moves of
    look-back on the early side of the next partition. For BMAB's
    ~70K rows/partition vs ~30 moves/game, this affects well under
    0.1% of positions.
    """
    themes_df = pl.read_parquet(themes_file)

    enr_cols = [c for c in TRAJECTORY_ENRICHED_COLS
                if c in pl.read_parquet(enriched_file, n_rows=1).columns]
    enr_df = pl.read_parquet(enriched_file, columns=enr_cols)
    # num_checkers_back_p2 is computed from board_p2 in the structural
    # pass, but the trajectory pass only needs it for post_blitz — load
    # it selectively from enriched if not already present.
    if "num_checkers_back_p2" not in enr_df.columns:
        b2 = pl.read_parquet(enriched_file, columns=["position_id", "board_p2"])
        b2 = b2.with_columns(
            sum(
                pl.col("board_p2").list.get(i).cast(pl.Int32)
                for i in range(19, 25)
            ).alias("num_checkers_back_p2"),
        ).drop("board_p2")
        enr_df = enr_df.join(b2, on="position_id", how="left")

    # Merge enriched fields we need with the existing themes frame.
    # Only bring in the columns not already present in themes_df.
    new_cols = [c for c in enr_df.columns if c not in themes_df.columns and c != "position_id"]
    if new_cols:
        themes_df = themes_df.join(
            enr_df.select(["position_id"] + new_cols),
            on="position_id",
            how="left",
        )

    merged = themes_df.sort(["game_id", "move_number"])

    merged = merged.with_columns([
        pl.col("num_checkers_back_p1")
          .shift(1)
          .over("game_id")
          .alias("prev_num_checkers_back_p1"),
        pl.col("theme_blitz")
          .cast(pl.Int8)
          .rolling_max(window_size=TRAJECTORY_K)
          .over("game_id")
          .cast(pl.Boolean)
          .alias("blitz_in_window"),
        pl.col("theme_ace_point")
          .cast(pl.Int8)
          .rolling_max(window_size=TRAJECTORY_K)
          .over("game_id")
          .cast(pl.Boolean)
          .alias("ace_point_in_window"),
    ])
    # prev_anchors_back_p1 is only consulted by theme_breaking_anchor
    # and its predicate only checks >= 1, so a proxy derived from
    # prev_num_checkers_back_p1 suffices.
    merged = merged.with_columns(
        (pl.col("prev_num_checkers_back_p1").fill_null(0) >= 2)
          .cast(pl.Int8)
          .alias("prev_anchors_back_p1"),
    )

    from lib import theme_rules as tr
    merged = merged.with_columns([
        tr.theme_breaking_anchor().fill_null(False).alias("theme_breaking_anchor"),
        tr.theme_post_blitz_turnaround().fill_null(False).alias("theme_post_blitz_turnaround"),
        tr.theme_post_ace_point().fill_null(False).alias("theme_post_ace_point"),
    ])

    # Drop derived + scratch columns and recompute primary_theme and
    # theme_count with the new Phase B information.
    scratch = [
        "prev_num_checkers_back_p1", "prev_anchors_back_p1",
        "blitz_in_window", "ace_point_in_window",
        "primary_theme", "theme_count",
    ] + [c for c in new_cols if c not in KEY_COLUMNS]
    merged = merged.drop([c for c in scratch if c in merged.columns])
    merged = _derived_columns(merged)
    merged = merged.select(_output_columns(merged))
    merged.write_parquet(themes_file, compression="snappy")
    return len(merged)


def trajectory_pass(enriched_dir: Path, themes_dir: Path) -> int:
    themes_files = sorted(themes_dir.glob("part-*.parquet"))
    if not themes_files:
        sys.exit(f"No position_themes partitions found in {themes_dir}")

    total = 0
    t0 = time.time()
    for idx, themes_file in enumerate(themes_files):
        enriched_file = enriched_dir / themes_file.name
        if not enriched_file.exists():
            print(f"  [skip] no matching enriched file for {themes_file.name}",
                  file=sys.stderr)
            continue
        n = _trajectory_update_partition(themes_file, enriched_file)
        total += n
        elapsed = time.time() - t0
        rate = total / elapsed if elapsed > 0 else 0.0
        print(f"  file {idx+1}/{len(themes_files)}: "
              f"{total:,} rows ({rate:,.0f} rows/s)", flush=True)
    return total


# ── Summary reports ─────────────────────────────────────────────────

def write_summary(themes_dir: Path, summary_dir: Path) -> None:
    summary_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(themes_dir.glob("part-*.parquet"))
    if not files:
        return

    print("  Aggregating theme frequencies across partitions...")
    frames = []
    for f in files:
        cols = [c for c in ALL_THEME_COLUMNS + ["theme_count"]
                if c in pl.read_parquet(f, n_rows=1).columns]
        frames.append(pl.read_parquet(f, columns=cols))
    combined = pl.concat(frames)
    total = len(combined)

    # theme_frequencies.csv
    rows = []
    for theme in ALL_THEME_COLUMNS:
        if theme in combined.columns:
            count = int(combined[theme].cast(pl.Int64).sum())
            rows.append({
                "theme": theme.removeprefix("theme_"),
                "count": count,
                "proportion": count / total if total else 0.0,
            })
    freq_df = pl.DataFrame(rows).sort("count", descending=True)
    freq_df.write_csv(summary_dir / "theme_frequencies.csv")
    print(f"  → {summary_dir / 'theme_frequencies.csv'}")

    # theme_count distribution
    if "theme_count" in combined.columns:
        dist = combined.group_by("theme_count").agg(pl.len().alias("n")).sort("theme_count")
        dist.write_csv(summary_dir / "theme_count_distribution.csv")
        print(f"  → {summary_dir / 'theme_count_distribution.csv'}")

    # theme_cooccurrence.csv (Jaccard, upper triangle).
    present = [t for t in ALL_THEME_COLUMNS if t in combined.columns]
    cooc_rows = []
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            both = int(((combined[a]) & (combined[b])).sum())
            either = int(((combined[a]) | (combined[b])).sum())
            jaccard = both / either if either else 0.0
            cooc_rows.append({
                "theme_a": a.removeprefix("theme_"),
                "theme_b": b.removeprefix("theme_"),
                "both": both,
                "either": either,
                "jaccard": jaccard,
            })
    pl.DataFrame(cooc_rows).sort("jaccard", descending=True).write_csv(
        summary_dir / "theme_cooccurrence.csv"
    )
    print(f"  → {summary_dir / 'theme_cooccurrence.csv'}")


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="S1.9 — Thematic position classification")
    ap.add_argument("--enriched", default="data/parquet/positions_enriched",
                    help="Input positions_enriched directory (S0.4 output)")
    ap.add_argument("--output", default="data/parquet/position_themes",
                    help="Output position_themes partition directory")
    ap.add_argument("--summary", default="data/themes",
                    help="Output directory for CSV summaries")
    ap.add_argument("--trajectory", action="store_true",
                    help="Run the trajectory (Phase B) pass over existing themes parquet")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only process the first N partitions (debugging)")
    ap.add_argument("--no-summary", action="store_true",
                    help="Skip summary CSV generation")
    args = ap.parse_args()

    enriched_dir = Path(args.enriched)
    out_dir = Path(args.output)
    summary_dir = Path(args.summary)

    print("=" * 60)
    print(f"  S1.9 — Thematic Position Classification"
          f"{' (trajectory)' if args.trajectory else ''}")
    print("=" * 60)

    if args.trajectory:
        t0 = time.time()
        n = trajectory_pass(enriched_dir, out_dir)
        print(f"\nTrajectory pass done: {n:,} rows in {time.time()-t0:.1f}s")
    else:
        pos_files = sorted(enriched_dir.glob("part-*.parquet"))
        if not pos_files:
            sys.exit(f"No enriched partitions found in {enriched_dir}")
        if args.limit:
            pos_files = pos_files[:args.limit]

        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        total = 0
        for idx, pos_file in enumerate(pos_files):
            out_file = out_dir / pos_file.name
            n = classify_partition(pos_file, out_file)
            total += n
            elapsed = time.time() - t0
            rate = total / elapsed if elapsed > 0 else 0.0
            print(f"  file {idx+1}/{len(pos_files)}: "
                  f"{total:,} rows ({rate:,.0f} rows/s)", flush=True)
        print(f"\nStructural pass done: {total:,} rows in {time.time()-t0:.1f}s")

    if not args.no_summary:
        print("\nWriting summary reports...")
        write_summary(out_dir, summary_dir)

    print("=" * 60)
    print(f"  Output: {out_dir}/")
    if not args.no_summary:
        print(f"  Summary: {summary_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
