#!/usr/bin/env python3
"""
S3.3 — Cube Equity Thresholds by Score

Extract empirical equity thresholds for cube decisions (double / no-double /
take / pass) per (away_p1, away_p2) score pair, compare with Kazaross-XG2
reference take points, and quantify how gammon rate modifies the thresholds.

Method
------
  For each score cell, cube decisions are split by optimal action:
    • Double threshold   : equity where "no_double" ↔ "double/redouble" switches.
      Estimated as the midpoint between:
        p90 of eval_equity | optimal = no_double
        p10 of eval_equity | optimal = double
    • Pass threshold (take point) : equity where "take" ↔ "pass" switches.
      Estimated as midpoint between:
        p90 of eval_equity | optimal = take
        p10 of eval_equity | optimal = pass
  Also computes the equity range for each action (confidence band).

  Gammon interaction: cells split by gammon_threat quartile to observe
  how the take point shifts with gammon threat.

  Janowski money-game formula (reference):
    double_threshold  ≈ -0.5 + 2 * take_point
    pass_threshold    ≈ take_point_equity
    (for match play: derived from MET differences)

Reference (Kazaross-XG2 take points from legacy/*.js)
------------------------------------------------------
  Table rows   : taker's away score  (1-indexed, 1..8)
  Table columns: doubler's away score (1-indexed, 1..8)
  Values        : take point in % (winning chances needed to take)

Outputs
-------
  <output>/cube_thresholds.csv          per (away_p1, away_p2): double/pass thresholds
  <output>/cube_thresholds_gammon.csv   same, split by gammon_threat quartile
  <output>/cube_thresholds_report.txt   printable reference tables + analysis

Usage
-----
  python scripts/compute_cube_thresholds.py \\
      --enriched data/parquet/positions_enriched \\
      --parquet  data/parquet \\
      --output   data/cube_analysis \\
      [--sample 2000000] [--min-n 30]
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Kazaross-XG2 take-point reference tables  (from legacy/*.js)
# Index: [taker_away - 1][doubler_away - 1], values in % (win chances to take)
# ---------------------------------------------------------------------------

TP2_LIVE = [                        # 2-cube, live game
    [32.5, 26,   20,   17.5, 22.5, 22,   21.5, 21  ],
    [25,   25,   21.5, 19.5, 22.5, 23,   22.5, 23  ],
    [18.5, 24,   22,   19.5, 23,   22.5, 22.5, 21.5],
    [23.5, 21.5, 24,   20,   23,   22.5, 23,   22  ],
    [22.5, 22,   24.5, 20,   23,   22,   22.5, 21  ],
    [23,   19.5, 25,   20,   23,   21.5, 22.5, 21.5],
    [20.5, 19.5, 24,   20,   22.5, 21,   22.5, 21.5],
    [22,   17.5, 24,   20,   22.5, 21,   22.5, 21.5],
]
TP2_LAST = [                        # 2-cube, last game
    [32.5, 26,   20,   17.5, 22.5, 22,   21.5, 21  ],
    [37,   30,   24,   21,   24,   24.5, 23,   23.5],
    [37,   35,   29,   22.5, 26,   24.5, 24.5, 23  ],
    [39.5, 28.5, 30.5, 24,   27,   25.5, 25,   24  ],
    [34,   28,   29.5, 23.5, 27,   25,   25.5, 24  ],
    [36,   25,   30.5, 24,   27.5, 25,   26,   24.5],
    [33.5, 26,   30.5, 24.5, 27.5, 25.5, 26.5, 24.5],
    [35.5, 23,   30.5, 24.5, 28,   25.5, 26.5, 25  ],
]
TP4_LIVE = [                        # 4-cube, live game
    [25, 40, 33, 29, 30, 33, 32],
    [19, 33, 30, 25, 26, 29, 29],
    [16, 26, 25, 25, 25, 27, 28],
    [11, 20, 22, 23, 24, 26, 26],
    [9,  16, 18, 20, 22, 24, 25],
    [7,  12, 16, 18, 20, 22, 23],
    [7,  12, 15, 17, 19, 21, 22],
]
TP4_LAST = [                        # 4-cube, last game
    [25, 40, 33, 29, 30, 33, 32],
    [19, 33, 30, 25, 26, 29, 29],
    [21, 31, 28, 26, 27, 28, 28],
    [19, 30, 28, 26, 26, 28, 28],
    [19, 27, 26, 26, 26, 27, 27],
    [16, 25, 25, 25, 25, 26, 26],
    [16, 23, 23, 24, 25, 26, 26],
]
TP_MAX = 8          # tables cover away 1..8

# Janowski money-game reference (constant)
MONEY_TAKE_POINT_PCT = 25.0         # 25% winning chances
MONEY_DOUBLE_THRESHOLD_EQ = 0.0     # equity ~ 0 for initial double
MONEY_PASS_THRESHOLD_EQ   = -0.5   # equity below which receiver should pass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print(f"\n{'─'*66}")
    print(f"  {title}")
    print(f"{'─'*66}")


def kazaross_tp(taker_away: int, doubler_away: int,
                cube_val: int = 2, last_game: bool = False) -> float | None:
    """Return Kazaross take point (%) for given score, cube, game context."""
    i, j = taker_away - 1, doubler_away - 1
    if cube_val == 2:
        table = TP2_LAST if last_game else TP2_LIVE
    else:
        table = TP4_LAST if last_game else TP4_LIVE

    n_rows = len(table)
    n_cols = len(table[0]) if table else 0
    if 0 <= i < n_rows and 0 <= j < n_cols:
        return table[i][j]
    return None


def janowski_double_threshold(away_p1: int, away_p2: int,
                               met_table: list[list[float]]) -> float | None:
    """
    Janowski approximation for match-play double threshold.
    Returns equity threshold above which doubling is optimal.
    Uses: DT = (ME(won) - ME(no_double)) / (ME(won) - ME(lost))
    where ME values come from the Kazaross MET.
    """
    if away_p1 <= 0 or away_p2 <= 0:
        return None
    n = len(met_table)

    def met(p1: int, p2: int) -> float:
        if p1 <= 0:
            return 100.0
        if p2 <= 0:
            return 0.0
        i, j = min(p1 - 1, n - 1), min(p2 - 1, n - 1)
        return met_table[i][j]

    me_now   = met(away_p1, away_p2)
    me_win1  = met(away_p1 - 1, away_p2)   # win 1 pt (opponent takes)
    me_win2  = met(away_p1 - 2, away_p2)   # win 2 pts (gammon after cube)
    me_lose1 = met(away_p1, away_p2 - 1)   # lose 1 pt
    me_lose2 = met(away_p1, away_p2 - 2)   # lose 2 pts

    # For a 2-cube: on take, outcomes are ±2pts
    denom = (me_win2 - me_lose2)
    if abs(denom) < 1e-6:
        return None
    dt = (me_now - me_lose2) / denom
    # Convert to equity scale (0-based): dt_equity ≈ 2*dt - 1 (approx)
    return float(2.0 * dt / 100.0 - 1.0)


MET_TABLE = [
    [50,   67.7, 75.1, 81.4, 84.2, 88.7, 90.7, 93.3, 94.4, 95.9, 96.6, 97.6, 98,   98.5, 98.8],
    [32.3, 50,   59.9, 66.9, 74.4, 79.9, 84.2, 87.5, 90.2, 92.3, 93.9, 95.2, 96.2, 97.1, 97.7],
    [24.9, 40.1, 50,   57.6, 64.8, 71.1, 76.2, 80.5, 84,   87.1, 89.4, 91.5, 93.1, 94.4, 95.5],
    [18.6, 33.1, 42.9, 50,   57.7, 64.3, 69.9, 74.6, 78.8, 82.4, 85.4, 87.9, 90,   91.8, 93.3],
    [15.8, 25.6, 35.2, 42.3, 50,   56.6, 62.6, 67.8, 72.5, 76.7, 80.3, 83.4, 86,   88.3, 90.2],
    [11.3, 20.1, 28.9, 35.7, 43.4, 50,   56.3, 61.6, 66.8, 71.3, 75.3, 78.9, 82,   84.7, 87.0],
    [9.3,  15.8, 23.8, 30.1, 37.4, 43.7, 50,   55.5, 60.8, 65.6, 70.0, 73.9, 77.4, 80.5, 83.3],
    [6.8,  12.5, 19.5, 25.4, 32.2, 38.4, 44.5, 50,   55.4, 60.4, 65.0, 69.1, 72.9, 76.4, 79.4],
    [5.6,  9.8,  16.0, 21.2, 27.5, 33.2, 39.1, 44.6, 50,   55.0, 59.8, 64.1, 68.2, 71.9, 75.3],
    [4.1,  7.7,  12.9, 17.6, 23.3, 28.7, 34.4, 39.6, 45.0, 50,   54.9, 59.3, 63.6, 67.5, 71.1],
    [3.4,  6.1,  10.6, 14.6, 19.7, 24.7, 30.0, 35.0, 40.2, 45.1, 50,   54.6, 58.9, 63.0, 66.8],
    [2.4,  4.8,  8.5,  12.1, 16.6, 21.1, 26.1, 30.9, 35.9, 40.7, 45.4, 50,   54.4, 58.6, 62.5],
    [2.0,  3.8,  6.9,  10.0, 14.0, 18.0, 22.6, 27.1, 31.8, 36.4, 41.1, 45.6, 50,   54.2, 58.3],
    [1.5,  2.9,  5.6,  8.2,  11.7, 15.3, 19.5, 23.6, 28.1, 32.5, 37.0, 41.4, 45.8, 50,   54.1],
    [1.2,  2.3,  4.5,  6.7,  9.8,  13.0, 16.7, 20.6, 24.7, 28.9, 33.2, 37.5, 41.7, 45.9, 50],
]

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cube(enriched_dir: str, parquet_dir: str, sample: int) -> pl.DataFrame:
    want = [
        "game_id", "match_id",
        "decision_type", "eval_equity", "eval_win",
        "eval_win_g", "eval_win_bg",
        "cube_action_played", "cube_action_optimal",
        "cube_value",
        "score_away_p1", "score_away_p2",
        "gammon_threat", "gammon_risk",
        "is_dmp", "crawford",
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
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "cube")
        if "eval_equity" in df.columns:
            df = df.filter(pl.col("eval_equity").is_not_null())
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No cube decisions found in enriched data")

    cube = pl.concat(frames, how="diagonal")
    if len(cube) > sample:
        cube = cube.sample(n=sample, seed=42)

    # Normalise cube actions to lowercase strings
    for col in ["cube_action_played", "cube_action_optimal"]:
        if col in cube.columns:
            cube = cube.with_columns(
                pl.col(col).cast(pl.String).str.to_lowercase().alias(col)
            )

    # Join match_length for last-game detection
    mp = Path(parquet_dir) / "matches.parquet"
    if mp.exists() and "match_id" in cube.columns:
        matches = pl.read_parquet(mp, columns=["match_id", "match_length"])
        cube = cube.join(matches, on="match_id", how="left")

    return cube


# ---------------------------------------------------------------------------
# Threshold estimation
# ---------------------------------------------------------------------------

def classify_action(df: pl.DataFrame) -> pl.DataFrame:
    """Normalise cube_action_optimal into 4 canonical categories."""
    if "cube_action_optimal" not in df.columns:
        return df.with_columns(pl.lit(None).cast(pl.String).alias("action_cat"))

    act = pl.col("cube_action_optimal")
    return df.with_columns(
        pl.when(act.str.contains("no_double") | act.str.contains("no double"))
        .then(pl.lit("no_double"))
        .when(act.str.contains("double") | act.str.contains("redouble"))
        .then(pl.lit("double"))
        .when(act == "take")
        .then(pl.lit("take"))
        .when(act == "pass")
        .then(pl.lit("pass"))
        .otherwise(pl.lit("other"))
        .alias("action_cat")
    )


def compute_thresholds(cube: pl.DataFrame, min_n: int) -> pl.DataFrame:
    """
    Per (away_p1, away_p2): estimate double threshold and pass threshold.

    Double threshold: midpoint of
      p90(equity | no_double) and p10(equity | double)
    Pass threshold: midpoint of
      p90(equity | take) and p10(equity | pass)
    Also record confidence bands and n per action.
    """
    if "action_cat" not in cube.columns or "eval_equity" not in cube.columns:
        return pl.DataFrame()
    if "score_away_p1" not in cube.columns:
        return pl.DataFrame()

    results = []
    for (p1, p2), grp in cube.filter(
        pl.col("score_away_p1").is_not_null() & pl.col("score_away_p2").is_not_null()
    ).group_by(["score_away_p1", "score_away_p2"]):

        row: dict = {"score_away_p1": int(p1), "score_away_p2": int(p2)}

        # Split by action category
        no_dbl = grp.filter(pl.col("action_cat") == "no_double")["eval_equity"]
        dbl    = grp.filter(pl.col("action_cat") == "double")["eval_equity"]
        take   = grp.filter(pl.col("action_cat") == "take")["eval_equity"]
        pass_  = grp.filter(pl.col("action_cat") == "pass")["eval_equity"]

        row["n_total"]    = len(grp)
        row["n_no_double"] = len(no_dbl)
        row["n_double"]    = len(dbl)
        row["n_take"]      = len(take)
        row["n_pass"]      = len(pass_)

        # Double threshold
        if len(no_dbl) >= min_n and len(dbl) >= min_n:
            p90_nd = float(no_dbl.quantile(0.90))
            p10_d  = float(dbl.quantile(0.10))
            row["double_threshold"]  = (p90_nd + p10_d) / 2.0
            row["double_band_lo"]    = p90_nd
            row["double_band_hi"]    = p10_d
            row["double_n_valid"]    = len(no_dbl) + len(dbl)
        else:
            row["double_threshold"] = None
            row["double_band_lo"]   = None
            row["double_band_hi"]   = None
            row["double_n_valid"]   = None

        # Pass threshold (take point)
        if len(take) >= min_n and len(pass_) >= min_n:
            p90_tk = float(take.quantile(0.90))
            p10_ps = float(pass_.quantile(0.10))
            row["pass_threshold"]  = (p90_tk + p10_ps) / 2.0
            row["pass_band_lo"]    = p90_tk
            row["pass_band_hi"]    = p10_ps
            row["pass_n_valid"]    = len(take) + len(pass_)
        else:
            row["pass_threshold"] = None
            row["pass_band_lo"]   = None
            row["pass_band_hi"]   = None
            row["pass_n_valid"]   = None

        # Mean equity per action (descriptive)
        for action, arr in [("no_double", no_dbl), ("double", dbl),
                             ("take", take), ("pass", pass_)]:
            row[f"mean_equity_{action}"] = float(arr.mean()) if len(arr) > 0 else None

        results.append(row)

    if not results:
        return pl.DataFrame()

    df_out = pl.DataFrame(results).sort(["score_away_p1", "score_away_p2"])

    # Attach Kazaross take-point reference (2-cube live, as baseline)
    kaz_tp = []
    jan_dt = []
    for row in df_out.iter_rows(named=True):
        p1, p2 = int(row["score_away_p1"]), int(row["score_away_p2"])
        kaz_tp.append(kazaross_tp(p1, p2, cube_val=2, last_game=False))
        jan_dt.append(janowski_double_threshold(p1, p2, MET_TABLE))

    df_out = df_out.with_columns([
        pl.Series("kazaross_tp2_live_pct", kaz_tp, dtype=pl.Float64),
        pl.Series("janowski_double_threshold", jan_dt, dtype=pl.Float64),
    ])

    # Kazaross TP as equity: TP_equity ≈ 2*(TP_pct/100) - 1
    df_out = df_out.with_columns(
        (pl.col("kazaross_tp2_live_pct") / 50.0 - 1.0).alias("kazaross_tp_equity")
    )

    return df_out


# ---------------------------------------------------------------------------
# Gammon interaction
# ---------------------------------------------------------------------------

def compute_gammon_interaction(cube: pl.DataFrame, min_n: int) -> pl.DataFrame:
    """
    Split cube decisions by gammon_threat quartile, recompute pass threshold.
    Shows how higher gammon threat shifts the take point.
    """
    if "gammon_threat" not in cube.columns or "action_cat" not in cube.columns:
        return pl.DataFrame()

    q25 = cube["gammon_threat"].quantile(0.25)
    q75 = cube["gammon_threat"].quantile(0.75)

    cube = cube.with_columns(
        pl.when(pl.col("gammon_threat") <= q25)
        .then(pl.lit("low gammon"))
        .when(pl.col("gammon_threat") <= q75)
        .then(pl.lit("medium gammon"))
        .otherwise(pl.lit("high gammon"))
        .alias("gammon_bracket")
    )

    results = []
    for (p1, p2, gb), grp in cube.filter(
        pl.col("score_away_p1").is_not_null() & pl.col("score_away_p2").is_not_null()
    ).group_by(["score_away_p1", "score_away_p2", "gammon_bracket"]):

        take  = grp.filter(pl.col("action_cat") == "take")["eval_equity"]
        pass_ = grp.filter(pl.col("action_cat") == "pass")["eval_equity"]

        if len(take) < min_n or len(pass_) < min_n:
            continue

        p90_tk = float(take.quantile(0.90))
        p10_ps = float(pass_.quantile(0.10))
        results.append({
            "score_away_p1": int(p1),
            "score_away_p2": int(p2),
            "gammon_bracket": gb,
            "pass_threshold": (p90_tk + p10_ps) / 2.0,
            "n_take": len(take),
            "n_pass": len(pass_),
        })

    if not results:
        return pl.DataFrame()
    return pl.DataFrame(results).sort(["score_away_p1", "score_away_p2", "gammon_bracket"])


# ---------------------------------------------------------------------------
# Printable reference table
# ---------------------------------------------------------------------------

def format_threshold_table(thresholds: pl.DataFrame,
                             max_away: int = 9) -> str:
    """
    Render a compact printable table: rows = p1 away (1..max), cols = p2 away.
    Each cell: "DT / PT" in equity (e.g. +0.42 / −0.28).
    """
    # Index thresholds
    dt: dict[tuple, float | None] = {}
    pt: dict[tuple, float | None] = {}
    for row in thresholds.iter_rows(named=True):
        key = (int(row["score_away_p1"]), int(row["score_away_p2"]))
        dt[key] = row.get("double_threshold")
        pt[key] = row.get("pass_threshold")

    actual_max = min(max_away, max((k[0] for k in dt), default=1),
                     max((k[1] for k in dt), default=1))

    lines = [
        "\n  Double Threshold  (equity above which doubling is correct)\n",
        "  away_p2 →  " + "".join(f"{p2:>8}" for p2 in range(1, actual_max + 1)),
        "  away_p1",
        "  " + "─" * (12 + 8 * actual_max),
    ]
    for p1 in range(1, actual_max + 1):
        row_str = f"  {p1:>8}  │"
        for p2 in range(1, actual_max + 1):
            v = dt.get((p1, p2))
            row_str += f"  {v:>+5.2f} " if v is not None else "    .   "
        lines.append(row_str)

    lines += [
        "\n  Pass Threshold  (equity below which passing is correct for receiver)\n",
        "  away_p2 →  " + "".join(f"{p2:>8}" for p2 in range(1, actual_max + 1)),
        "  away_p1",
        "  " + "─" * (12 + 8 * actual_max),
    ]
    for p1 in range(1, actual_max + 1):
        row_str = f"  {p1:>8}  │"
        for p2 in range(1, actual_max + 1):
            v = pt.get((p1, p2))
            row_str += f"  {v:>+5.2f} " if v is not None else "    .   "
        lines.append(row_str)

    return "\n".join(lines)


def format_kazaross_tp_table() -> str:
    """Render Kazaross 2-cube live take-point reference table."""
    n_rows = len(TP2_LIVE)
    n_cols = len(TP2_LIVE[0])
    lines = [
        "\n  Kazaross-XG2 Take Points — 2-cube, live game (%)  "
        "(rows=taker_away, cols=doubler_away)\n",
        "  doubler →  " + "".join(f"{j+1:>7}" for j in range(n_cols)),
        "  taker",
        "  " + "─" * (12 + 7 * n_cols),
    ]
    for i, row in enumerate(TP2_LIVE):
        row_str = f"  {i+1:>8}  │"
        for v in row:
            row_str += f"  {v:>4.1f} "
        lines.append(row_str)
    lines.append(f"\n  Money game reference: {MONEY_TAKE_POINT_PCT:.1f}%")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(thresholds: pl.DataFrame,
                  gammon_df: pl.DataFrame,
                  output_path: Path,
                  n_total: int) -> None:
    lines = [
        "S3.3 — Cube Equity Thresholds by Score",
        "=" * 66, "",
        f"Cube decisions analysed : {n_total:,}",
        f"Score cells with data   : {len(thresholds):,}",
        "",
        "Definitions:",
        "  Double threshold : equity above which doubling is optimal (for the doubler).",
        "  Pass threshold   : equity below which passing is optimal (for the receiver).",
        "  Equity scale     : −1 = total loss, 0 = neutral, +1 = total win.",
        "",
        "Money-game references:",
        f"  Double threshold  : {MONEY_DOUBLE_THRESHOLD_EQ:+.2f}",
        f"  Pass threshold    : {MONEY_PASS_THRESHOLD_EQ:+.2f}",
        f"  Take point        : {MONEY_TAKE_POINT_PCT:.1f}% winning chances",
        "",
    ]

    lines.append(format_threshold_table(thresholds, max_away=9))
    lines.append(format_kazaross_tp_table())

    # Deviation between empirical pass threshold and Kazaross
    valid = thresholds.filter(
        pl.col("pass_threshold").is_not_null() &
        pl.col("kazaross_tp_equity").is_not_null()
    )
    if not valid.is_empty():
        valid = valid.with_columns(
            (pl.col("pass_threshold") - pl.col("kazaross_tp_equity"))
            .alias("deviation_from_kazaross")
        )
        mean_dev = valid["deviation_from_kazaross"].mean()
        lines += [
            "",
            "─" * 66,
            f"Empirical pass threshold vs Kazaross (mean deviation): {mean_dev:+.4f} equity",
            "",
            f"  {'away_p1':>8}  {'away_p2':>8}  {'empirical':>10}  "
            f"{'kazaross_eq':>12}  {'dev':>8}  {'kaz_pct':>8}",
            "  " + "-" * 58,
        ]
        for row in valid.sort("deviation_from_kazaross", descending=True).head(20) \
                        .iter_rows(named=True):
            lines.append(
                f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                f"{row['pass_threshold']:>+10.4f}  "
                f"{row['kazaross_tp_equity']:>+12.4f}  "
                f"{row['deviation_from_kazaross']:>+8.4f}  "
                f"{row['kazaross_tp2_live_pct']:>8.1f}%"
            )

    # Gammon interaction
    if not gammon_df.is_empty():
        lines += [
            "",
            "─" * 66,
            "Gammon Interaction — Pass Threshold by Gammon Threat",
            "",
            f"  {'away_p1':>8}  {'away_p2':>8}  {'gammon_bracket':<18}  "
            f"{'pass_threshold':>14}  {'n_take':>8}  {'n_pass':>8}",
            "  " + "-" * 70,
        ]
        for row in gammon_df.head(40).iter_rows(named=True):
            lines.append(
                f"  {row['score_away_p1']:>8}  {row['score_away_p2']:>8}  "
                f"{str(row['gammon_bracket']):<18}  "
                f"{row['pass_threshold']:>+14.4f}  "
                f"{row['n_take']:>8,}  {row['n_pass']:>8,}"
            )

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="S3.3 — Cube Equity Thresholds by Score")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir (matches.parquet)")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=2_000_000,
                    help="Max cube rows to load (default: 2000000)")
    ap.add_argument("--min-n", type=int, default=30,
                    help="Min decisions per (cell × action) to compute threshold (default: 30)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    print("  S3.3 — Cube Equity Thresholds by Score")
    print("=" * 66)
    print(f"  enriched : {args.enriched}")
    print(f"  parquet  : {args.parquet}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,}")
    print(f"  min-n    : {args.min_n}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading cube decisions")
    cube = load_cube(args.enriched, args.parquet, args.sample)
    print(f"  {len(cube):,} cube decisions loaded ({time.time()-t0:.1f}s)")

    if "cube_action_optimal" in cube.columns:
        act_dist = (cube.group_by("cube_action_optimal")
                    .agg(pl.len().alias("n"))
                    .sort("n", descending=True))
        print(f"\n  Optimal action distribution:")
        for row in act_dist.iter_rows(named=True):
            print(f"    {str(row['cube_action_optimal']):<20} : {row['n']:>10,}")
    else:
        print("  [WARN] cube_action_optimal not available")

    cube = classify_action(cube)

    # ------------------------------------------------------------------
    # 1. Threshold estimation
    # ------------------------------------------------------------------
    section("1. Computing double & pass thresholds per score cell")
    thresholds = compute_thresholds(cube, args.min_n)
    print(f"  {len(thresholds):,} cells with enough data for both actions")

    # Quick summary
    if not thresholds.is_empty():
        dt_valid = thresholds.filter(pl.col("double_threshold").is_not_null())
        pt_valid = thresholds.filter(pl.col("pass_threshold").is_not_null())

        if not dt_valid.is_empty():
            print(f"\n  Double threshold — mean={dt_valid['double_threshold'].mean():+.4f}, "
                  f"range [{dt_valid['double_threshold'].min():+.4f}, "
                  f"{dt_valid['double_threshold'].max():+.4f}]")
        if not pt_valid.is_empty():
            print(f"  Pass threshold   — mean={pt_valid['pass_threshold'].mean():+.4f}, "
                  f"range [{pt_valid['pass_threshold'].min():+.4f}, "
                  f"{pt_valid['pass_threshold'].max():+.4f}]")

        print(f"\n  Money-game references:")
        print(f"    Double threshold : {MONEY_DOUBLE_THRESHOLD_EQ:+.2f}")
        print(f"    Pass threshold   : {MONEY_PASS_THRESHOLD_EQ:+.2f}")

        # Show selected common scores
        common = [(3,3),(3,5),(5,3),(5,5),(4,6),(7,7),(2,4),(4,2),(2,2),(1,2)]
        print(f"\n  Common score reference:")
        print(f"  {'Score':>14}  {'DoubleThresh':>13}  {'PassThresh':>11}  "
              f"{'Kaz TP%':>8}  {'Kaz TP eq':>10}")
        print("  " + "-" * 62)
        for p1, p2 in common:
            row_it = thresholds.filter(
                (pl.col("score_away_p1") == p1) & (pl.col("score_away_p2") == p2)
            )
            if row_it.is_empty():
                continue
            r = row_it.row(0, named=True)
            dt_v = r.get("double_threshold")
            pt_v = r.get("pass_threshold")
            kz   = r.get("kazaross_tp2_live_pct")
            kzeq = r.get("kazaross_tp_equity")
            dt_s  = f"{dt_v:>+13.4f}" if dt_v is not None else f"{'n/a':>13}"
            pt_s  = f"{pt_v:>+11.4f}" if pt_v is not None else f"{'n/a':>11}"
            kz_s  = f"{kz:>8.1f}%" if kz is not None else f"{'n/a':>9}"
            kzeq_s = f"{kzeq:>+10.4f}" if kzeq is not None else f"{'n/a':>10}"
            print(f"  p1={p1:>2} p2={p2:>2} away  {dt_s}  {pt_s}  {kz_s}  {kzeq_s}")

    # ------------------------------------------------------------------
    # 2. Kazaross reference display
    # ------------------------------------------------------------------
    section("2. Kazaross-XG2 take point reference (2-cube live, %)")
    print(format_kazaross_tp_table())

    # ------------------------------------------------------------------
    # 3. Gammon interaction
    # ------------------------------------------------------------------
    section("3. Gammon interaction")
    if "gammon_threat" in cube.columns:
        gammon_df = compute_gammon_interaction(cube, args.min_n)
        print(f"  {len(gammon_df):,} (cell × gammon_bracket) entries")

        if not gammon_df.is_empty():
            # Show effect for a few cells
            for p1, p2 in [(3,5),(5,5),(7,7)]:
                sub = gammon_df.filter(
                    (pl.col("score_away_p1") == p1) & (pl.col("score_away_p2") == p2)
                ).sort("gammon_bracket")
                if sub.is_empty():
                    continue
                print(f"\n  Score {p1}away-{p2}away — gammon effect on pass threshold:")
                for row in sub.iter_rows(named=True):
                    print(f"    {str(row['gammon_bracket']):<20}  "
                          f"pass_threshold={row['pass_threshold']:>+8.4f}  "
                          f"(n_take={row['n_take']:,}, n_pass={row['n_pass']:,})")
    else:
        gammon_df = pl.DataFrame()
        print("  [SKIP] gammon_threat not available in enriched data")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    if not thresholds.is_empty():
        p = output_dir / "cube_thresholds.csv"
        thresholds.write_csv(p)
        print(f"  → {p}  ({len(thresholds):,} rows)")

    if not gammon_df.is_empty():
        p = output_dir / "cube_thresholds_gammon.csv"
        gammon_df.write_csv(p)
        print(f"  → {p}  ({len(gammon_df):,} rows)")

    report_path = output_dir / "cube_thresholds_report.txt"
    write_report(thresholds,
                 gammon_df if "gammon_df" in dir() else pl.DataFrame(),
                 report_path, len(cube))
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*66}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*66}")


if __name__ == "__main__":
    main()
