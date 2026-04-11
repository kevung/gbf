#!/usr/bin/env python3
"""S1.2 — Feature-error correlation analysis for the backgammon mining study.

Identifies which position and context features are most correlated with
decision error, separately for checker and cube decisions.

Methods
-------
1. Spearman rank correlation — feature vs move_played_error (non-linear)
2. Mutual information — for categorical / low-cardinality features
3. Error by category — game phase, away score bracket, cube ownership
4. Random Forest feature importance — lightweight model for ranking

Outputs (written to --output directory)
----------------------------------------
spearman_checker.csv         Spearman ρ + p-value for checker positions
spearman_cube.csv            Spearman ρ for cube positions (abs equity error)
mutual_info.csv              MI scores for categorical features
rf_importance_checker.csv    Random Forest importance (checker)
rf_importance_cube.csv       Random Forest importance (cube)
error_by_phase.csv           Mean error per game phase
error_by_score_bracket.csv   Mean error by away score bucket
error_by_cube_owner.csv      Mean error by cube ownership

Usage::

    python scripts/correlation_analysis.py \\
        --enriched data/parquet/positions_enriched \\
        [--parquet-dir data/parquet] \\
        [--output data/stats] \\
        [--sample 200000]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_selection import mutual_info_regression
from sklearn.preprocessing import LabelEncoder


# ---------------------------------------------------------------------------
# Feature sets
# ---------------------------------------------------------------------------

# Continuous features available in positions_enriched.
CHECKER_FEATURES = [
    "pip_count_p1", "pip_count_p2", "pip_count_diff",
    "num_blots_p1", "num_blots_p2",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "home_board_strength_p1",
    "longest_prime_p1", "longest_prime_p2",
    "back_anchor_p1", "num_checkers_back_p1",
    "num_builders_p1", "outfield_blots_p1",
    "num_on_bar_p1", "num_on_bar_p2",
    "num_borne_off_p1", "num_borne_off_p2",
    "match_phase",
    "gammon_threat", "gammon_risk", "net_gammon",
    "cube_leverage",
    "score_away_p1", "score_away_p2", "score_differential",
    "eval_win", "eval_equity",
]

CUBE_FEATURES = [
    "pip_count_p1", "pip_count_p2", "pip_count_diff",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "longest_prime_p1", "longest_prime_p2",
    "match_phase",
    "gammon_threat", "gammon_risk", "net_gammon",
    "cube_leverage",
    "score_away_p1", "score_away_p2", "score_differential",
    "eval_win", "cube_value",
]

CATEGORICAL_FEATURES = ["match_phase", "cube_owner", "is_dmp", "dgr"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_enriched(enriched_glob: str, parquet_dir: Path | None, sample: int) -> pl.DataFrame:
    """Load enriched positions, joining with games for score columns if needed."""
    import duckdb
    conn = duckdb.connect()
    conn.execute("SET memory_limit='8GB'")
    conn.execute(f"CREATE VIEW enriched AS SELECT * FROM read_parquet('{enriched_glob}')")

    if parquet_dir:
        games_path = str(parquet_dir / "games.parquet")
        if Path(games_path).exists():
            conn.execute(f"CREATE VIEW games AS SELECT * FROM read_parquet('{games_path}')")

    sample_clause = f"USING SAMPLE {sample}" if sample > 0 else ""
    df = conn.execute(
        f"SELECT * FROM enriched {sample_clause}"
    ).pl()
    conn.close()
    return df


def prepare_array(df: pl.DataFrame, features: list[str], target: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Extract feature matrix X and target y, dropping rows with nulls."""
    available = [f for f in features if f in df.columns]
    subset = df.select(available + [target]).drop_nulls()
    X = subset.select(available).to_numpy().astype(np.float64)
    y = subset[target].to_numpy().astype(np.float64)
    # Replace NaN/inf that slip through.
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    return X[mask], y[mask], available


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def spearman_correlations(
    X: np.ndarray, y: np.ndarray, feature_names: list[str], label: str
) -> pl.DataFrame:
    """Compute Spearman ρ between each feature and target."""
    rows = []
    for i, name in enumerate(feature_names):
        col = X[:, i]
        if col.std() < 1e-10:
            rows.append({"feature": name, "spearman_rho": 0.0, "p_value": 1.0, "abs_rho": 0.0})
            continue
        rho, pval = stats.spearmanr(col, y)
        rows.append({
            "feature": name,
            "spearman_rho": round(float(rho), 4),
            "p_value": float(pval),
            "abs_rho": round(abs(float(rho)), 4),
        })
    df = pl.DataFrame(rows).sort("abs_rho", descending=True)
    return df


def mutual_info_scores(
    df: pl.DataFrame, target: str, features: list[str]
) -> pl.DataFrame:
    """Mutual information between each feature and the target."""
    available = [f for f in features if f in df.columns]
    subset = df.select(available + [target]).drop_nulls()
    X = subset.select(available).to_numpy().astype(np.float64)
    y = subset[target].to_numpy().astype(np.float64)
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[mask], y[mask]

    # Treat integer features as discrete.
    discrete_mask = [
        df[f].dtype in (pl.Boolean, pl.Int8, pl.Int16, pl.Int32)
        for f in available
    ]
    mi = mutual_info_regression(X, y, discrete_features=discrete_mask, random_state=42)
    return pl.DataFrame({
        "feature": available,
        "mutual_info": [round(float(v), 5) for v in mi],
    }).sort("mutual_info", descending=True)


def rf_importance(
    X: np.ndarray, y: np.ndarray, feature_names: list[str],
    n_estimators: int = 50, max_depth: int = 5
) -> pl.DataFrame:
    """Random Forest feature importance (mean decrease in impurity)."""
    if len(y) < 100:
        return pl.DataFrame({"feature": feature_names, "rf_importance": [0.0] * len(feature_names)})
    rf = RandomForestRegressor(
        n_estimators=n_estimators, max_depth=max_depth,
        n_jobs=-1, random_state=42
    )
    rf.fit(X, y)
    return pl.DataFrame({
        "feature": feature_names,
        "rf_importance": [round(float(v), 5) for v in rf.feature_importances_],
    }).sort("rf_importance", descending=True)


def error_by_category(df: pl.DataFrame, col: str, target: str) -> pl.DataFrame:
    """Mean error and count grouped by a categorical column."""
    if col not in df.columns:
        return pl.DataFrame()
    return (
        df.filter(pl.col(target).is_not_null())
        .group_by(col)
        .agg([
            pl.col(target).mean().alias("mean_error"),
            pl.col(target).median().alias("median_error"),
            pl.len().alias("n"),
        ])
        .sort(col)
    )


def away_score_bracket(away: int) -> str:
    """Classify away score into a named bracket."""
    if away <= 0:
        return "money"
    if away == 1:
        return "1-away"
    if away == 2:
        return "2-away"
    if away <= 4:
        return "3-4-away"
    if away <= 7:
        return "5-7-away"
    return "8+-away"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def print_top(df: pl.DataFrame, rank_col: str, n: int = 15):
    """Print top-N rows of a ranking DataFrame."""
    cols = df.columns
    header = "  " + "  ".join(f"{c:>20}" for c in cols)
    print(header)
    for row in df.head(n).iter_rows(named=True):
        line = "  " + "  ".join(
            f"{str(row[c])[:20]:>20}" for c in cols
        )
        print(line)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S1.2: Feature-error correlation analysis"
    )
    parser.add_argument("--enriched", required=True,
                        help="Enriched positions directory (S0.4 output)")
    parser.add_argument("--parquet-dir", default=None,
                        help="Parquet dir for games join (optional)")
    parser.add_argument("--output", default="data/stats",
                        help="Output directory for CSV results")
    parser.add_argument("--sample", type=int, default=0,
                        help="Random sample size (0 = all rows)")
    parser.add_argument("--rf-trees", type=int, default=50,
                        help="Random Forest n_estimators (default 50)")
    args = parser.parse_args()

    enriched_path = Path(args.enriched)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not list(enriched_path.glob("part-*.parquet")):
        print(f"ERROR: no parquet files in {enriched_path}", file=sys.stderr)
        sys.exit(1)

    parquet_dir = Path(args.parquet_dir) if args.parquet_dir else None
    enriched_glob = str(enriched_path / "part-*.parquet")

    t0 = time.time()
    print("=" * 60)
    print("  S1.2 — Feature-Error Correlation Analysis")
    print("=" * 60)

    print(f"\nLoading enriched positions (sample={args.sample or 'all'}) ...")
    df = load_enriched(enriched_glob, parquet_dir, args.sample)
    print(f"  {len(df):,} rows loaded")

    # Split checker vs cube.
    checker_df = df.filter(pl.col("decision_type") == "checker") if "decision_type" in df.columns else df
    cube_df    = df.filter(pl.col("decision_type") == "cube")    if "decision_type" in df.columns else pl.DataFrame()

    # ── Checker: Spearman ─────────────────────────────────────────────────
    section("Spearman Correlation — Checker Decisions")
    if "move_played_error" in checker_df.columns and len(checker_df) > 0:
        X_c, y_c, feats_c = prepare_array(checker_df, CHECKER_FEATURES, "move_played_error")
        print(f"  N = {len(y_c):,}  (non-null checker rows)")
        sp_checker = spearman_correlations(X_c, y_c, feats_c, "checker")
        print_top(sp_checker, "abs_rho")
        sp_checker.write_csv(str(out_dir / "spearman_checker.csv"))
    else:
        print("  (no checker error data available)")
        sp_checker = pl.DataFrame()
        X_c, y_c, feats_c = np.array([[]]), np.array([]), []

    # ── Cube: Spearman on abs(eval_equity as proxy for cube error) ────────
    section("Spearman Correlation — Cube Decisions")
    if len(cube_df) > 0 and "eval_equity" in cube_df.columns:
        cube_df = cube_df.with_columns(
            pl.col("eval_equity").abs().alias("cube_abs_equity")
        )
        X_cu, y_cu, feats_cu = prepare_array(cube_df, CUBE_FEATURES, "cube_abs_equity")
        print(f"  N = {len(y_cu):,}  (non-null cube rows)")
        sp_cube = spearman_correlations(X_cu, y_cu, feats_cu, "cube")
        print_top(sp_cube, "abs_rho")
        sp_cube.write_csv(str(out_dir / "spearman_cube.csv"))
    else:
        print("  (no cube data available)")

    # ── Mutual Information ─────────────────────────────────────────────────
    section("Mutual Information — Checker Decisions")
    if "move_played_error" in checker_df.columns and len(checker_df) > 10:
        mi = mutual_info_scores(checker_df, "move_played_error", CHECKER_FEATURES)
        print_top(mi, "mutual_info")
        mi.write_csv(str(out_dir / "mutual_info.csv"))

    # ── Random Forest importance ───────────────────────────────────────────
    section(f"Random Forest Importance — Checker (n_estimators={args.rf_trees})")
    if len(feats_c) > 0 and len(y_c) >= 50:
        rf_c = rf_importance(X_c, y_c, feats_c, n_estimators=args.rf_trees)
        print_top(rf_c, "rf_importance")
        rf_c.write_csv(str(out_dir / "rf_importance_checker.csv"))

        if len(cube_df) > 50 and "eval_equity" in cube_df.columns:
            section(f"Random Forest Importance — Cube")
            rf_cu = rf_importance(X_cu, y_cu, feats_cu, n_estimators=args.rf_trees)
            print_top(rf_cu, "rf_importance")
            rf_cu.write_csv(str(out_dir / "rf_importance_cube.csv"))

    # ── Error by game phase ────────────────────────────────────────────────
    section("Mean Error by Game Phase (checker)")
    phase_labels = {0: "contact", 1: "race", 2: "bearoff"}
    if "match_phase" in checker_df.columns and "move_played_error" in checker_df.columns:
        phase_df = error_by_category(checker_df, "match_phase", "move_played_error")
        if not phase_df.is_empty():
            phase_df = phase_df.with_columns(
                pl.col("match_phase").map_elements(
                    lambda x: phase_labels.get(x, str(x)), return_dtype=pl.String
                ).alias("phase_name")
            )
            print(f"  {'phase':<12}  {'mean_error':>12}  {'median':>10}  {'n':>8}")
            for row in phase_df.iter_rows(named=True):
                print(
                    f"  {row.get('phase_name','?'):<12}"
                    f"  {row['mean_error']:>12.5f}"
                    f"  {row['median_error']:>10.5f}"
                    f"  {row['n']:>8,}"
                )
            phase_df.write_csv(str(out_dir / "error_by_phase.csv"))

    # ── Error by away score bracket ────────────────────────────────────────
    section("Mean Error by Away Score Bracket (checker)")
    if "score_away_p1" in checker_df.columns and "move_played_error" in checker_df.columns:
        bracket_df = (
            checker_df
            .filter(pl.col("move_played_error").is_not_null())
            .with_columns(
                pl.col("score_away_p1").map_elements(away_score_bracket, return_dtype=pl.String)
                .alias("away_bracket")
            )
            .group_by("away_bracket")
            .agg([
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").median().alias("median_error"),
                pl.len().alias("n"),
            ])
            .sort("mean_error", descending=True)
        )
        print(f"  {'bracket':<12}  {'mean_error':>12}  {'median':>10}  {'n':>8}")
        for row in bracket_df.iter_rows(named=True):
            print(
                f"  {row['away_bracket']:<12}"
                f"  {row['mean_error']:>12.5f}"
                f"  {row['median_error']:>10.5f}"
                f"  {row['n']:>8,}"
            )
        bracket_df.write_csv(str(out_dir / "error_by_score_bracket.csv"))

    # ── Error by cube ownership ────────────────────────────────────────────
    section("Mean Error by Cube Owner (checker)")
    cube_owner_labels = {0: "centered", 1: "on-roll", 2: "opponent"}
    if "cube_owner" in checker_df.columns and "move_played_error" in checker_df.columns:
        co_df = error_by_category(checker_df, "cube_owner", "move_played_error")
        if not co_df.is_empty():
            co_df = co_df.with_columns(
                pl.col("cube_owner").map_elements(
                    lambda x: cube_owner_labels.get(x, str(x)), return_dtype=pl.String
                ).alias("owner_name")
            )
            print(f"  {'owner':<12}  {'mean_error':>12}  {'median':>10}  {'n':>8}")
            for row in co_df.iter_rows(named=True):
                print(
                    f"  {row.get('owner_name','?'):<12}"
                    f"  {row['mean_error']:>12.5f}"
                    f"  {row['median_error']:>10.5f}"
                    f"  {row['n']:>8,}"
                )
            co_df.write_csv(str(out_dir / "error_by_cube_owner.csv"))

    elapsed = time.time() - t0
    print(f"\n{'═' * 60}")
    print(f"  Done in {elapsed:.1f}s — CSVs written to {out_dir}/")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
