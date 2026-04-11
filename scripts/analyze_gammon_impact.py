#!/usr/bin/env python3
"""
S3.5 — Gammon Impact Analysis

Quantify how gammon threat/risk modifies optimal cube decisions by score,
identify position types with high gammon potential, empirically verify dead
gammon situations, and measure the free-drop advantage in post-Crawford play.

Reference gammon-value tables (Kazaross-XG2, from legacy/*.js)
--------------------------------------------------------------
  gammonValue1Table : gammon value with 1-cube  [away_p1-1][away_p2-1]
  gammonValue2Table : gammon value with 2-cube
  gammonValue4Table : gammon value with 4-cube

Analyses
--------
  1. Gammon value by score  — avg(gammon_threat) & avg(gammon_risk) per
     (away_p1, away_p2), compared to Kazaross GV reference.
  2. Gammon × cube threshold — how high gammon threat shifts the pass
     threshold (cross-reference with S3.3 cube_thresholds.csv if available).
  3. Gammon-prone position features — logistic regression / DT importance
     to identify which board features predict high gammon threat.
  4. Dead gammon — empirically verify DGR flag: positions where gammon
     threat > 0.20 but score leader is at 1-away → wasted gammon threat.
  5. Free drop — post-Crawford positions: compare error rates on cube
     decisions with vs without the free-drop advantage, and quantify
     the equity gain from the free pass.

Outputs
-------
  <output>/gammon_value_by_score.csv      empirical vs Kazaross GV per cell
  <output>/gammon_features.csv            feature importance for gammon threat
  <output>/dead_gammon_analysis.csv       DGR positions: gammon_threat distribution
  <output>/free_drop_analysis.csv         post-Crawford cube error comparison
  <output>/gammon_report.txt              full analysis report

Usage
-----
  python scripts/analyze_gammon_impact.py \\
      --enriched data/parquet/positions_enriched \\
      --parquet  data/parquet \\
      --output   data/cube_analysis \\
      [--sample 3000000]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Kazaross-XG2 gammon-value tables  (from legacy/*.js)
# Index: [away_p1 - 1][away_p2 - 1]
# Value: fraction of a point that a gammon is worth at this score
# ---------------------------------------------------------------------------

GV1 = [  # 1-cube (undoubled)
    [0.91, 0.99, 0.86, 0.91, 0.78, 0.86, 0.75, 0.82],
    [0.71, 0.76, 0.86, 0.57, 0.58, 0.50, 0.50, 0.43],
    [0.46, 0.59, 0.68, 0.65, 0.66, 0.67, 0.67, 0.66],
    [0.40, 0.42, 0.48, 0.46, 0.48, 0.47, 0.49, 0.47],
    [0.52, 0.51, 0.58, 0.54, 0.58, 0.58, 0.59, 0.57],
    [0.52, 0.48, 0.55, 0.50, 0.53, 0.51, 0.53, 0.51],
    [0.48, 0.45, 0.54, 0.50, 0.54, 0.54, 0.56, 0.55],
    [0.48, 0.44, 0.49, 0.47, 0.49, 0.49, 0.51, 0.50],
]
GV2 = [  # 2-cube
    [0.48, 0.50, 0.45, 0.46, 0.36, 0.36, 0.31, 0.31],
    [1.00, 0.97, 0.98, 0.81, 0.67, 0.60, 0.54, 0.48],
    [0.69, 0.73, 0.77, 0.66, 0.61, 0.55, 0.54, 0.49],
    [0.51, 0.54, 0.56, 0.58, 0.55, 0.54, 0.53, 0.51],
    [0.56, 0.57, 0.56, 0.57, 0.55, 0.54, 0.53, 0.51],
    [0.65, 0.63, 0.61, 0.60, 0.58, 0.57, 0.56, 0.54],
    [0.63, 0.63, 0.60, 0.59, 0.57, 0.56, 0.55, 0.54],
]
GV4 = [  # 4-cube
    [0.48, 0.33, 0.23, 0.23, 0.13, 0.17, 0.13, 0.13],
    [1.00, 0.67, 0.50, 0.41, 0.34, 0.29, 0.24, 0.21],
    [1.50, 1.00, 0.75, 0.63, 0.52, 0.45, 0.39, 0.34],
    [2.02, 1.33, 1.00, 0.83, 0.69, 0.60, 0.52, 0.46],
    [1.64, 1.13, 0.93, 0.77, 0.67, 0.60, 0.55, 0.49],
]
GV_MAX_P1 = {1: len(GV1), 2: len(GV2), 4: len(GV4)}
GV_MAX_P2 = {1: len(GV1[0]), 2: len(GV2[0]), 4: len(GV4[0])}

MONEY_GAMMON_VALUE = 0.50   # money game: gammon = 0.5 equity points


def kazaross_gv(away_p1: int, away_p2: int, cube_val: int = 1) -> float | None:
    table = {1: GV1, 2: GV2, 4: GV4}.get(cube_val)
    if table is None:
        return None
    i, j = away_p1 - 1, away_p2 - 1
    if 0 <= i < len(table) and 0 <= j < len(table[0]):
        return table[i][j]
    return None


def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_positions(enriched_dir: str, sample: int) -> pl.DataFrame:
    want = [
        "position_id", "game_id", "match_id",
        "decision_type", "move_played_error",
        "eval_win", "eval_win_g", "eval_win_bg",
        "eval_lose_g",
        "gammon_threat", "gammon_risk", "net_gammon",
        "score_away_p1", "score_away_p2",
        "cube_value", "cube_action_played", "cube_action_optimal",
        "is_dmp", "dgr", "crawford", "is_post_crawford",
        "match_phase",
        # Board features for gammon-prone analysis
        "home_board_points_p1", "home_board_strength_p1",
        "longest_prime_p1", "num_blots_p2",
        "num_on_bar_p2", "num_checkers_back_p1",
        "pip_count_diff",
    ]
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    frames, total = [], 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols  = [c for c in want if c in probe.columns]
            df    = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No enriched data found")
    pos = pl.concat(frames, how="diagonal")
    if len(pos) > sample:
        pos = pos.sample(n=sample, seed=42)
    return pos


def load_games(parquet_dir: str) -> pl.DataFrame:
    p = Path(parquet_dir) / "games.parquet"
    if not p.exists():
        return pl.DataFrame()
    cols = ["game_id", "match_id", "gammon", "backgammon", "points_won"]
    probe = pl.read_parquet(p, n_rows=1)
    return pl.read_parquet(p, columns=[c for c in cols if c in probe.columns])


# ---------------------------------------------------------------------------
# 1. Gammon value by score
# ---------------------------------------------------------------------------

def compute_gammon_value_by_score(pos: pl.DataFrame,
                                   min_n: int = 50) -> pl.DataFrame:
    """
    Empirical gammon value proxy: avg(gammon_threat) and avg(gammon_risk)
    per (away_p1, away_p2) for checker decisions.
    Compare with Kazaross GV1 (1-cube reference).
    """
    checker = pos.filter(
        pl.col("decision_type") == "checker"
    ) if "decision_type" in pos.columns else pos

    need = {"gammon_threat", "gammon_risk", "score_away_p1", "score_away_p2"}
    if not need.issubset(set(checker.columns)):
        return pl.DataFrame()

    agg = (
        checker.filter(
            pl.col("gammon_threat").is_not_null() & pl.col("gammon_risk").is_not_null()
        )
        .group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n"),
            pl.col("gammon_threat").mean().alias("avg_gammon_threat"),
            pl.col("gammon_risk").mean().alias("avg_gammon_risk"),
            pl.col("net_gammon").mean().alias("avg_net_gammon")
            if "net_gammon" in checker.columns else pl.lit(None).alias("avg_net_gammon"),
            pl.col("gammon_threat").quantile(0.90).alias("p90_gammon_threat"),
        ])
        .filter(pl.col("n") >= min_n)
        .sort(["score_away_p1", "score_away_p2"])
    )

    # Attach Kazaross GV1 reference
    kaz_gv = [kazaross_gv(int(r["score_away_p1"]), int(r["score_away_p2"]), cube_val=1)
               for r in agg.iter_rows(named=True)]
    agg = agg.with_columns(pl.Series("kazaross_gv1", kaz_gv, dtype=pl.Float64))

    return agg


# ---------------------------------------------------------------------------
# 2. Gammon-prone position features
# ---------------------------------------------------------------------------

GAMMON_BOARD_FEATURES = [
    "home_board_points_p1", "home_board_strength_p1",
    "longest_prime_p1", "num_blots_p2",
    "num_on_bar_p2", "num_checkers_back_p1",
    "pip_count_diff",
]


def compute_gammon_feature_importance(pos: pl.DataFrame) -> pl.DataFrame:
    """
    Identify which board features predict high gammon threat (> 0.30).
    Uses a decision tree for feature importance.
    """
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        return pl.DataFrame()

    checker = pos.filter(
        pl.col("decision_type") == "checker"
    ) if "decision_type" in pos.columns else pos

    if "gammon_threat" not in checker.columns:
        return pl.DataFrame()

    avail = [f for f in GAMMON_BOARD_FEATURES if f in checker.columns]
    if len(avail) < 2:
        return pl.DataFrame()

    sub = checker.filter(pl.col("gammon_threat").is_not_null()).select(
        avail + ["gammon_threat"]
    ).fill_null(0)

    X = sub.select(avail).to_numpy().astype(np.float32)
    y = (sub["gammon_threat"] >= 0.30).to_numpy().astype(int)

    if y.mean() < 0.01 or y.mean() > 0.99:
        return pl.DataFrame()

    clf = DecisionTreeClassifier(max_depth=4, min_samples_leaf=100,
                                  class_weight="balanced", random_state=42)
    clf.fit(X, y)

    return pl.DataFrame({
        "feature":    avail,
        "importance": clf.feature_importances_.tolist(),
    }).sort("importance", descending=True)


# ---------------------------------------------------------------------------
# 3. Dead gammon analysis
# ---------------------------------------------------------------------------

def compute_dead_gammon(pos: pl.DataFrame) -> pl.DataFrame:
    """
    Dead gammon risk (DGR): leader is at 1-away, gammon doesn't help.
    Empirically verify: in DGR positions, is gammon_threat lower than expected?
    Compare gammon_threat distribution: DGR=True vs DGR=False.
    """
    if "dgr" not in pos.columns or "gammon_threat" not in pos.columns:
        return pl.DataFrame()

    checker = pos.filter(
        pl.col("decision_type") == "checker"
    ) if "decision_type" in pos.columns else pos

    result = (
        checker.filter(pl.col("gammon_threat").is_not_null())
        .group_by("dgr")
        .agg([
            pl.len().alias("n"),
            pl.col("gammon_threat").mean().alias("avg_gammon_threat"),
            pl.col("gammon_threat").median().alias("med_gammon_threat"),
            pl.col("gammon_threat").quantile(0.75).alias("p75_gammon_threat"),
            pl.col("move_played_error").mean().alias("avg_error")
            if "move_played_error" in checker.columns else pl.lit(None).alias("avg_error"),
        ])
        .sort("dgr")
    )
    return result


def compute_dead_gammon_by_score(pos: pl.DataFrame, min_n: int = 30) -> pl.DataFrame:
    """Gammon threat by (away_p1, away_p2) for DGR positions only."""
    if "dgr" not in pos.columns or "gammon_threat" not in pos.columns:
        return pl.DataFrame()

    dgr_pos = pos.filter(pl.col("dgr") == True)  # noqa: E712
    if dgr_pos.is_empty():
        return pl.DataFrame()

    return (
        dgr_pos.group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n"),
            pl.col("gammon_threat").mean().alias("avg_gammon_threat"),
            pl.col("gammon_threat").std().alias("std_gammon_threat"),
        ])
        .filter(pl.col("n") >= min_n)
        .sort("avg_gammon_threat", descending=True)
    )


# ---------------------------------------------------------------------------
# 4. Free drop analysis (post-Crawford)
# ---------------------------------------------------------------------------

def compute_free_drop(pos: pl.DataFrame) -> pl.DataFrame:
    """
    Post-Crawford free drop: the trailer can pass the initial double for free
    (Crawford rule — no cube penalty). Measure:
      - Cube decision error in post-Crawford vs non-post-Crawford
      - Missed pass rate (wrong_take in post-Crawford = missed free drop)
    """
    cube = pos.filter(
        pl.col("decision_type") == "cube"
    ) if "decision_type" in pos.columns else pl.DataFrame()

    if cube.is_empty() or "move_played_error" not in cube.columns:
        return pl.DataFrame()

    has_post = "is_post_crawford" in cube.columns
    has_crawford = "crawford" in cube.columns

    if not has_post and not has_crawford:
        return pl.DataFrame()

    # Tag cube decisions by game context
    if has_post:
        cube = cube.with_columns(
            pl.when(pl.col("is_post_crawford") == True)  # noqa: E712
            .then(pl.lit("post_crawford"))
            .when(has_crawford and pl.col("crawford") == True)  # noqa: E712
            .then(pl.lit("crawford"))
            .otherwise(pl.lit("normal"))
            .alias("game_context")
        )
    else:
        cube = cube.with_columns(
            pl.when(pl.col("crawford") == True)  # noqa: E712
            .then(pl.lit("crawford"))
            .otherwise(pl.lit("normal"))
            .alias("game_context")
        )

    agg_exprs = [
        pl.len().alias("n"),
        pl.col("move_played_error").mean().alias("avg_cube_error"),
        pl.col("move_played_error").median().alias("med_cube_error"),
        (pl.col("move_played_error") > 0.080).mean().alias("blunder_rate"),
    ]

    # Wrong take in post-Crawford = missed free drop
    if "cube_action_played" in cube.columns and "cube_action_optimal" in cube.columns:
        cube = cube.with_columns([
            pl.col("cube_action_played").cast(pl.String).str.to_lowercase(),
            pl.col("cube_action_optimal").cast(pl.String).str.to_lowercase(),
        ])
        agg_exprs.append(
            (
                (pl.col("cube_action_optimal") == "pass") &
                (pl.col("cube_action_played") == "take")
            ).mean().alias("wrong_take_rate")
        )

    return (
        cube.group_by("game_context")
        .agg(agg_exprs)
        .sort("game_context")
    )


def compute_free_drop_by_score(pos: pl.DataFrame, min_n: int = 20) -> pl.DataFrame:
    """
    In post-Crawford, quantify free-drop equity gain by trailing score.
    Free drop equity ≈ avg error on wrong takes in post-Crawford positions.
    """
    cube = pos.filter(
        pl.col("decision_type") == "cube"
    ) if "decision_type" in pos.columns else pl.DataFrame()

    if cube.is_empty():
        return pl.DataFrame()
    if "is_post_crawford" not in cube.columns:
        return pl.DataFrame()
    if "cube_action_played" not in cube.columns:
        return pl.DataFrame()

    post = cube.filter(pl.col("is_post_crawford") == True)  # noqa: E712
    if post.is_empty():
        return pl.DataFrame()

    post = post.with_columns([
        pl.col("cube_action_played").cast(pl.String).str.to_lowercase(),
        pl.col("cube_action_optimal").cast(pl.String).str.to_lowercase(),
    ])

    return (
        post.group_by(["score_away_p1", "score_away_p2"])
        .agg([
            pl.len().alias("n_cube"),
            pl.col("move_played_error").mean().alias("avg_error"),
            # Wrong take in post-Crawford = missed free drop
            (
                (pl.col("cube_action_optimal") == "pass") &
                (pl.col("cube_action_played") == "take")
            ).mean().alias("free_drop_miss_rate"),
            pl.col("move_played_error")
            .filter(
                (pl.col("cube_action_optimal") == "pass") &
                (pl.col("cube_action_played") == "take")
            ).mean().alias("avg_free_drop_error"),
        ])
        .filter(pl.col("n_cube") >= min_n)
        .sort(["score_away_p1", "score_away_p2"])
    )


# ---------------------------------------------------------------------------
# ASCII grid helper
# ---------------------------------------------------------------------------

def render_grid(data: pl.DataFrame, value_col: str,
                title: str, max_away: int = 9) -> str:
    cell: dict[tuple[int, int], float] = {}
    for row in data.iter_rows(named=True):
        p1, p2, v = row.get("score_away_p1"), row.get("score_away_p2"), row.get(value_col)
        if p1 and p2 and v is not None:
            cell[(int(p1), int(p2))] = float(v)
    if not cell:
        return f"  {title}: (no data)\n"
    amax = min(max_away, max(max(k) for k in cell))
    lines = [f"\n  {title}\n",
             "  away_p2 →  " + "".join(f"{p2:>7}" for p2 in range(1, amax + 1)),
             "  away_p1",
             "  " + "─" * (12 + 7 * amax)]
    for p1 in range(1, amax + 1):
        row_str = f"  {p1:>8}  │"
        for p2 in range(1, amax + 1):
            v = cell.get((p1, p2))
            row_str += f" {v:>5.3f} " if v is not None else "    .  "
        lines.append(row_str)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(gv_df: pl.DataFrame,
                  feat_df: pl.DataFrame,
                  dead_df: pl.DataFrame,
                  dead_score_df: pl.DataFrame,
                  free_drop_df: pl.DataFrame,
                  free_drop_score_df: pl.DataFrame,
                  output_path: Path) -> None:
    lines = [
        "S3.5 — Gammon Impact Analysis",
        "=" * 64, "",
        "Reference: Kazaross-XG2 gammon values (legacy/gammonValue*.js).",
        f"Money-game gammon value: {MONEY_GAMMON_VALUE:.2f}",
        "",
    ]

    # Kazaross GV1 reference table (compact)
    lines += ["─" * 64,
              "Kazaross-XG2 Gammon Value — 1-cube  "
              "(rows=away_p1, cols=away_p2)\n",
              "  away_p2 →  " + "".join(f"{j+1:>7}" for j in range(len(GV1[0]))),
              "  away_p1",
              "  " + "─" * (12 + 7 * len(GV1[0]))]
    for i, row in enumerate(GV1):
        lines.append("  " + f"{i+1:>8}  │" + "".join(f" {v:>5.2f} " for v in row))
    lines.append("")

    # Empirical gammon threat
    if not gv_df.is_empty():
        lines += ["─" * 64, "1. Empirical gammon threat by score\n"]
        lines.append(render_grid(gv_df, "avg_gammon_threat",
                                  "Avg gammon threat (your win-gammon prob)"))
        lines.append(render_grid(gv_df, "avg_gammon_risk",
                                  "Avg gammon risk (opponent win-gammon prob)"))

        # Top scores for gammon value
        lines += ["\n  Scores with highest gammon threat:"]
        lines.append(f"  {'away_p1':>8}  {'away_p2':>8}  {'n':>8}  "
                      f"{'avg_threat':>10}  {'kaz_gv1':>8}")
        lines.append("  " + "-" * 46)
        for row in gv_df.sort("avg_gammon_threat", descending=True).head(10).iter_rows(named=True):
            kaz = row.get("kazaross_gv1")
            kaz_s = f"{kaz:>8.3f}" if kaz is not None else "    n/a "
            lines.append(f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                          f"{row['n']:>8,}  {row['avg_gammon_threat']:>10.4f}  {kaz_s}")

    # Feature importance
    if not feat_df.is_empty():
        lines += ["─" * 64,
                  "2. Board features predicting high gammon threat (> 0.30)\n"]
        for row in feat_df.iter_rows(named=True):
            bar = "█" * min(int(row["importance"] * 200), 28)
            lines.append(f"  {row['feature']:<32}  {row['importance']:>6.4f}  {bar}")
        lines.append("")

    # Dead gammon
    if not dead_df.is_empty():
        lines += ["─" * 64, "3. Dead Gammon Risk (DGR)\n",
                  "  When the leader is at 1-away, winning a gammon doesn't help.",
                  "  DGR positions should show lower effective gammon value.\n"]
        lines.append(f"  {'DGR':>6}  {'N':>10}  {'Avg threat':>10}  "
                      f"{'Med threat':>10}  {'Avg error':>10}")
        lines.append("  " + "-" * 50)
        for row in dead_df.iter_rows(named=True):
            ae = row.get("avg_error")
            ae_s = f"{ae:>10.4f}" if ae is not None else f"{'n/a':>10}"
            lines.append(f"  {str(row['dgr']):>6}  {row['n']:>10,}  "
                          f"{row['avg_gammon_threat']:>10.4f}  "
                          f"{row['med_gammon_threat']:>10.4f}  {ae_s}")
        lines.append("")

    # Free drop
    if not free_drop_df.is_empty():
        lines += ["─" * 64,
                  "4. Free Drop Analysis (post-Crawford)\n",
                  "  Post-Crawford: the trailer may pass the initial double at no cost.",
                  "  wrong_take_rate = player took when they should have passed (missed free drop).\n"]
        lines.append(f"  {'Context':<16}  {'N':>8}  {'AvgError':>9}  "
                      f"{'Blunder%':>9}  {'WrongTake%':>11}")
        lines.append("  " + "-" * 58)
        for row in free_drop_df.iter_rows(named=True):
            bl = (row.get("blunder_rate") or 0) * 100
            wt = (row.get("wrong_take_rate") or 0) * 100
            ae = row['avg_cube_error']
            ae_s = f"{ae:>9.4f}" if ae is not None else "      n/a"
            lines.append(f"  {str(row['game_context']):<16}  {row['n']:>8,}  "
                          f"{ae_s}  {bl:>8.1f}%  {wt:>10.1f}%")
        lines.append("")

    if not free_drop_score_df.is_empty():
        lines += ["\n  Free-drop miss rate by score (post-Crawford only):\n",
                  f"  {'away_p1':>8}  {'away_p2':>8}  {'n_cube':>8}  "
                  f"{'miss_rate':>10}  {'avg_miss_err':>13}"]
        lines.append("  " + "-" * 52)
        for row in free_drop_score_df.sort("free_drop_miss_rate", descending=True) \
                                      .head(15).iter_rows(named=True):
            mr = (row.get("free_drop_miss_rate") or 0) * 100
            ae = row.get("avg_free_drop_error")
            ae_s = f"{ae:>13.4f}" if ae is not None else f"{'n/a':>13}"
            lines.append(f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                          f"{row['n_cube']:>8,}  {mr:>9.1f}%  {ae_s}")

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S3.5 — Gammon Impact Analysis")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=3_000_000,
                    help="Max positions to load (default: 3000000)")
    ap.add_argument("--min-n", type=int, default=50,
                    help="Min positions per score cell (default: 50)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  S3.5 — Gammon Impact Analysis")
    print("=" * 64)
    print(f"  enriched : {args.enriched}")
    print(f"  parquet  : {args.parquet}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading enriched positions")
    pos = load_positions(args.enriched, args.sample)
    print(f"  {len(pos):,} positions loaded ({time.time()-t0:.1f}s)")

    # Column inventory
    for col, label in [("gammon_threat", "gammon_threat"), ("dgr", "DGR flag"),
                        ("is_post_crawford", "post-Crawford flag"),
                        ("crawford", "crawford flag")]:
        if col in pos.columns:
            n = pos[col].is_not_null().sum()
            print(f"  {label:<22} : {n:>10,} non-null")
        else:
            print(f"  {label:<22} : (not available)")

    # ------------------------------------------------------------------
    # 1. Gammon value by score
    # ------------------------------------------------------------------
    section("1. Gammon value by score")
    gv_df = compute_gammon_value_by_score(pos, args.min_n)
    print(f"  {len(gv_df):,} score cells")
    if not gv_df.is_empty():
        top = gv_df.sort("avg_gammon_threat", descending=True).head(8)
        print(f"\n  Highest gammon-threat scores:")
        print(f"  {'p1':>6}  {'p2':>6}  {'avg_threat':>10}  {'kaz_gv1':>8}")
        print("  " + "-" * 36)
        for row in top.iter_rows(named=True):
            kaz = row.get("kazaross_gv1")
            kaz_s = f"{kaz:.3f}" if kaz is not None else " n/a"
            print(f"  {row['score_away_p1']:>6}  {row['score_away_p2']:>6}  "
                  f"{row['avg_gammon_threat']:>10.4f}  {kaz_s:>8}")

    # ------------------------------------------------------------------
    # 2. Gammon-prone position features
    # ------------------------------------------------------------------
    section("2. Features predicting high gammon threat")
    feat_df = compute_gammon_feature_importance(pos)
    if not feat_df.is_empty():
        print(f"  {'Feature':<32}  {'Importance':>10}")
        print("  " + "-" * 44)
        for row in feat_df.iter_rows(named=True):
            bar = "█" * min(int(row["importance"] * 200), 24)
            print(f"  {row['feature']:<32}  {row['importance']:>10.4f}  {bar}")
    else:
        print("  [SKIP] Not enough gammon data or sklearn not available")

    # ------------------------------------------------------------------
    # 3. Dead gammon
    # ------------------------------------------------------------------
    section("3. Dead gammon risk (DGR)")
    dead_df       = compute_dead_gammon(pos)
    dead_score_df = compute_dead_gammon_by_score(pos, args.min_n)

    if not dead_df.is_empty():
        print(f"  {'DGR':>6}  {'N':>10}  {'AvgThreat':>10}  {'MedThreat':>10}")
        print("  " + "-" * 42)
        for row in dead_df.iter_rows(named=True):
            print(f"  {str(row['dgr']):>6}  {row['n']:>10,}  "
                  f"{row['avg_gammon_threat']:>10.4f}  "
                  f"{row['med_gammon_threat']:>10.4f}")
        if len(dead_df) >= 2:
            dgr_vals = {str(r["dgr"]): r["avg_gammon_threat"]
                        for r in dead_df.iter_rows(named=True)}
            if "True" in dgr_vals and "False" in dgr_vals:
                diff = dgr_vals["True"] - dgr_vals["False"]
                print(f"\n  Gammon threat in DGR vs non-DGR: Δ = {diff:+.4f}")
                if diff > 0:
                    print("  → DGR positions have HIGHER gammon threat (wasted potential)")
                else:
                    print("  → DGR positions show lower gammon threat (as expected)")
    else:
        print("  [SKIP] DGR flag not available in enriched data")

    if not dead_score_df.is_empty():
        print(f"\n  DGR positions with highest gammon threat (wasted):")
        for row in dead_score_df.head(8).iter_rows(named=True):
            print(f"    p1={row['score_away_p1']}-away p2={row['score_away_p2']}-away : "
                  f"avg_threat={row['avg_gammon_threat']:.4f}  n={row['n']:,}")

    # ------------------------------------------------------------------
    # 4. Free drop
    # ------------------------------------------------------------------
    section("4. Free drop analysis (post-Crawford)")
    free_drop_df       = compute_free_drop(pos)
    free_drop_score_df = compute_free_drop_by_score(pos, min_n=20)

    if not free_drop_df.is_empty():
        print(f"  {'Context':<16}  {'N':>8}  {'AvgError':>9}  {'Blunder%':>9}  {'WrongTake%':>11}")
        print("  " + "-" * 58)
        for row in free_drop_df.iter_rows(named=True):
            bl = (row.get("blunder_rate") or 0) * 100
            wt = (row.get("wrong_take_rate") or 0) * 100
            ae = row['avg_cube_error']
            ae_s = f"{ae:>9.4f}" if ae is not None else "      n/a"
            print(f"  {str(row['game_context']):<16}  {row['n']:>8,}  "
                  f"{ae_s}  {bl:>8.1f}%  {wt:>10.1f}%")

        # Quantify the free drop advantage
        ctx_map = {r["game_context"]: r for r in free_drop_df.iter_rows(named=True)}
        if "post_crawford" in ctx_map and "normal" in ctx_map:
            pc = ctx_map["post_crawford"]
            nm = ctx_map["normal"]
            pc_err = pc["avg_cube_error"]
            nm_err = nm["avg_cube_error"]
            if pc_err is not None and nm_err is not None:
                delta = pc_err - nm_err
                print(f"\n  Cube error delta (post_crawford − normal): {delta:+.4f}")
            if pc.get("wrong_take_rate") is not None:
                print(f"  Free-drop miss rate in post-Crawford  : "
                      f"{pc['wrong_take_rate']*100:.1f}%")
    else:
        print("  [SKIP] post-Crawford or cube action data not available")

    if not free_drop_score_df.is_empty():
        print(f"\n  Scores with highest free-drop miss rate:")
        for row in free_drop_score_df.sort("free_drop_miss_rate", descending=True) \
                                      .head(6).iter_rows(named=True):
            mr = (row.get("free_drop_miss_rate") or 0) * 100
            ae = row.get("avg_free_drop_error")
            ae_s = f"{ae:.4f}" if ae is not None else "n/a"
            print(f"    p1={row['score_away_p1']}-away p2={row['score_away_p2']}-away : "
                  f"miss={mr:.1f}%  avg_err={ae_s}  n={row['n_cube']:,}")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    if not gv_df.is_empty():
        p = output_dir / "gammon_value_by_score.csv"
        gv_df.write_csv(p)
        print(f"  → {p}  ({len(gv_df):,} rows)")

    if not feat_df.is_empty():
        p = output_dir / "gammon_features.csv"
        feat_df.write_csv(p)
        print(f"  → {p}")

    if not dead_df.is_empty():
        p = output_dir / "dead_gammon_analysis.csv"
        pl.concat([dead_df, dead_score_df], how="diagonal").write_csv(p)
        print(f"  → {p}")

    if not free_drop_df.is_empty():
        p = output_dir / "free_drop_analysis.csv"
        pl.concat([free_drop_df, free_drop_score_df], how="diagonal").write_csv(p)
        print(f"  → {p}")

    report_path = output_dir / "gammon_report.txt"
    write_report(gv_df, feat_df, dead_df, dead_score_df,
                 free_drop_df, free_drop_score_df, report_path)
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*64}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
