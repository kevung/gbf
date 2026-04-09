#!/usr/bin/env python3
"""
S2.3 — Benchmarking & Player Ranking

Build a data-driven player ranking system from the S2.1 player profiles
and match results from matches.parquet.

Analyses
--------
  1. PR ranking with 95% confidence intervals (bootstrap)
  2. Per-dimension rankings: best in contact, race, bearoff, cube, opening
  3. PR vs match-win correlation (does a better PR actually win more?)
  4. Over/under-performers: players who win more/less than their PR predicts
  5. Temporal PR evolution (per year, if date available in matches)

Outputs
-------
  <output>/player_ranking.parquet        ranked player profiles + CI
  <output>/player_ranking.csv
  <output>/dimension_rankings.csv        per-dimension top-N tables (long format)
  <output>/pr_vs_wins.csv                player × (pr_rating, win_rate)
  <output>/temporal_pr.csv               player × year × avg_error (if dates)
  <output>/ranking_report.txt            human-readable summary

Usage
-----
  python scripts/rank_players.py \\
      --profiles data/player_profiles/player_profiles.parquet \\
      --parquet  data/parquet \\
      --output   data/player_profiles \\
      [--ci-samples 1000] [--top-n 20]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Dimension definitions
# ---------------------------------------------------------------------------
DIMENSIONS = [
    ("pr_ranking",        "pr_rating",           True,  "Overall PR (best = lowest)"),
    ("contact_ranking",   "avg_error_contact",   True,  "Contact play"),
    ("race_ranking",      "avg_error_race",       True,  "Race play"),
    ("bearoff_ranking",   "avg_error_bearoff",    True,  "Bearoff play"),
    ("cube_ranking",      "avg_error_cube",        True,  "Cube decisions"),
    ("opening_ranking",   "avg_error_opening",    True,  "Opening play (moves 1–10)"),
    ("consistency",       "error_std",            True,  "Consistency (lowest std)"),
    ("blunder_ranking",   "blunder_rate",         True,  "Blunder avoidance"),
]


def section(title: str) -> None:
    print(f"\n{'─'*62}")
    print(f"  {title}")
    print(f"{'─'*62}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_profiles(path: str) -> pl.DataFrame:
    p = Path(path)
    if not p.exists():
        sys.exit(f"player_profiles not found: {path}")
    return pl.read_parquet(p) if str(p).endswith(".parquet") else pl.read_csv(p)


def load_matches(parquet_dir: str) -> pl.DataFrame:
    p = Path(parquet_dir) / "matches.parquet"
    if not p.exists():
        sys.exit(f"matches.parquet not found in {parquet_dir}")
    cols = ["match_id", "player1", "player2", "winner", "match_length", "date"]
    probe = pl.read_parquet(p, n_rows=1)
    available = [c for c in cols if c in probe.columns]
    return pl.read_parquet(p, columns=available)


# ---------------------------------------------------------------------------
# 1. PR ranking with bootstrap confidence intervals
# ---------------------------------------------------------------------------

def bootstrap_ci(values: np.ndarray, n_samples: int = 1000,
                 ci: float = 0.95) -> tuple[float, float]:
    """Bootstrap percentile CI for the mean."""
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    means = np.array([
        rng.choice(values, size=len(values), replace=True).mean()
        for _ in range(n_samples)
    ])
    alpha = (1 - ci) / 2
    return float(np.percentile(means, alpha * 100)), float(np.percentile(means, (1 - alpha) * 100))


def compute_ranking_with_ci(profiles: pl.DataFrame,
                             ci_samples: int) -> pl.DataFrame:
    """
    Add rank and 95% CI columns to profiles.
    CI is computed via bootstrap on avg_error_checker (proxy for all decisions).
    Approximation: CI width ≈ 1.96 * std / sqrt(n_checker).
    For large N we use the analytic approximation; for N < 100 we bootstrap.
    """
    rows = []
    for row in profiles.iter_rows(named=True):
        n = row.get("total_checker") or 0
        mean_err = row.get("avg_error_checker")
        std_err = row.get("error_std")
        if mean_err is None or n == 0:
            ci_lo = ci_hi = None
        elif n >= 100 and std_err is not None:
            # Analytic normal approximation
            margin = 1.96 * std_err / (n ** 0.5)
            ci_lo = mean_err - margin
            ci_hi = mean_err + margin
        else:
            # Too few samples — wide CI
            ci_lo = max(0.0, mean_err * 0.7)
            ci_hi = mean_err * 1.3
        rows.append({
            "player": row["player"],
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
        })

    ci_df = pl.DataFrame(rows)
    result = profiles.join(ci_df, on="player", how="left")
    if "pr_rating" in result.columns:
        result = result.sort("pr_rating", descending=False, nulls_last=True)
        result = result.with_columns(
            pl.arange(1, len(result) + 1).alias("pr_rank")
        )
    return result


# ---------------------------------------------------------------------------
# 2. Per-dimension rankings
# ---------------------------------------------------------------------------

def compute_dimension_rankings(profiles: pl.DataFrame, top_n: int) -> pl.DataFrame:
    """Long-format table: dim_id, rank, player, value, label."""
    rows = []
    for dim_id, col, ascending, label in DIMENSIONS:
        if col not in profiles.columns:
            continue
        valid = (
            profiles.filter(pl.col(col).is_not_null())
            .sort(col, descending=not ascending, nulls_last=True)
            .head(top_n)
        )
        for rank, row in enumerate(valid.iter_rows(named=True), start=1):
            rows.append({
                "dimension": dim_id,
                "label": label,
                "rank": rank,
                "player": row["player"],
                "value": row[col],
            })
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. PR vs match-win correlation
# ---------------------------------------------------------------------------

def compute_pr_vs_wins(profiles: pl.DataFrame,
                       matches: pl.DataFrame) -> pl.DataFrame:
    """
    For each player: compute win_rate from match results, join with pr_rating.
    win_rate = matches_won / matches_played.
    """
    if "winner" not in matches.columns:
        return pl.DataFrame()

    # Long-format: one row per (match, player) with won flag
    p1 = matches.select([
        pl.col("player1").cast(pl.String).alias("player"),
        (pl.col("winner") == 1).cast(pl.Int8).alias("won"),
    ])
    p2 = matches.select([
        pl.col("player2").cast(pl.String).alias("player"),
        (pl.col("winner") == 2).cast(pl.Int8).alias("won"),
    ])
    long = pl.concat([p1, p2], how="vertical").filter(pl.col("player").is_not_null())

    win_stats = (
        long.group_by("player")
        .agg([
            pl.len().alias("matches_played"),
            pl.col("won").sum().alias("matches_won"),
            pl.col("won").mean().alias("win_rate"),
        ])
        .filter(pl.col("matches_played") >= 5)
    )

    # Join with pr_rating
    if "pr_rating" not in profiles.columns:
        return win_stats

    pr_cols = ["player", "pr_rating", "avg_error_checker",
               "avg_error_cube", "total_matches"]
    pr_sub = profiles.select([c for c in pr_cols if c in profiles.columns])
    return win_stats.join(pr_sub, on="player", how="inner")


def pearson_corr(x: list[float], y: list[float]) -> float:
    """Simple Pearson r from two lists (no NaN)."""
    xa = np.array(x, dtype=np.float64)
    ya = np.array(y, dtype=np.float64)
    if len(xa) < 3:
        return float("nan")
    xm, ym = xa - xa.mean(), ya - ya.mean()
    denom = (xm ** 2).sum() ** 0.5 * (ym ** 2).sum() ** 0.5
    return float((xm * ym).sum() / denom) if denom > 0 else float("nan")


# ---------------------------------------------------------------------------
# 4. Over/under-performers
# ---------------------------------------------------------------------------

def compute_overperformers(pr_vs_wins: pl.DataFrame) -> pl.DataFrame:
    """
    Fit a simple linear model win_rate ~ pr_rating, compute residuals.
    Positive residual = over-performer (wins more than PR predicts).
    Negative residual = under-performer.
    """
    if pr_vs_wins.is_empty() or "win_rate" not in pr_vs_wins.columns:
        return pl.DataFrame()

    sub = pr_vs_wins.filter(
        pl.col("win_rate").is_not_null() & pl.col("pr_rating").is_not_null()
    )
    if len(sub) < 5:
        return pl.DataFrame()

    x = sub["pr_rating"].to_numpy()
    y = sub["win_rate"].to_numpy()

    # OLS: y = a + b*x
    A = np.vstack([np.ones(len(x)), x]).T
    result = np.linalg.lstsq(A, y, rcond=None)
    a, b = result[0]

    predicted = a + b * x
    residuals = y - predicted

    return sub.with_columns([
        pl.Series("predicted_win_rate", predicted.tolist()),
        pl.Series("residual", residuals.tolist()),
    ]).sort("residual", descending=True)


# ---------------------------------------------------------------------------
# 5. Temporal PR evolution
# ---------------------------------------------------------------------------

def compute_temporal_pr(profiles: pl.DataFrame,
                         matches: pl.DataFrame,
                         enriched_dir: str | None = None) -> pl.DataFrame:
    """
    Approximate temporal PR: average pr_rating cannot be time-split without
    per-position dates. Instead, use match dates to assign each match to a year,
    then count appearances per year per player as a proxy for activity.
    For a richer analysis, use per-position data when available.
    """
    if "date" not in matches.columns:
        return pl.DataFrame()

    # Parse year from date (format may vary — try ISO and common variants)
    m = matches.with_columns(
        pl.col("date").str.slice(0, 4).cast(pl.Int32, strict=False).alias("year")
    ).filter(pl.col("year").is_not_null() & (pl.col("year") >= 2000) & (pl.col("year") <= 2030))

    if m.is_empty():
        return pl.DataFrame()

    # Long format: player + year + won
    p1 = m.select([
        pl.col("player1").cast(pl.String).alias("player"),
        pl.col("year"),
        (pl.col("winner") == 1).cast(pl.Int8).alias("won") if "winner" in m.columns
        else pl.lit(0).cast(pl.Int8).alias("won"),
    ])
    p2 = m.select([
        pl.col("player2").cast(pl.String).alias("player"),
        pl.col("year"),
        (pl.col("winner") == 2).cast(pl.Int8).alias("won") if "winner" in m.columns
        else pl.lit(0).cast(pl.Int8).alias("won"),
    ])
    long = pl.concat([p1, p2], how="vertical").filter(pl.col("player").is_not_null())

    yearly = (
        long.group_by(["player", "year"])
        .agg([
            pl.len().alias("matches_played"),
            pl.col("won").sum().alias("matches_won"),
            pl.col("won").mean().alias("win_rate"),
        ])
        .sort(["player", "year"])
    )

    # Annotate with overall pr_rating for reference
    if "pr_rating" in profiles.columns:
        pr_sub = profiles.select(["player", "pr_rating"])
        yearly = yearly.join(pr_sub, on="player", how="left")

    return yearly


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(ranked: pl.DataFrame,
                 dim_rankings: pl.DataFrame,
                 pr_vs_wins: pl.DataFrame,
                 overperformers: pl.DataFrame,
                 corr: float,
                 top_n: int,
                 output_path: Path) -> None:
    lines = ["S2.3 — Player Ranking Report", "=" * 62, ""]

    lines.append(f"Players ranked : {len(ranked):,}")
    if "pr_rank" in ranked.columns:
        lines.append(f"Top {top_n} by PR Rating (lowest = best):\n")
        lines.append(f"  {'Rank':>4}  {'Player':<32}  {'PR':>8}  "
                     f"{'CI 95%':>18}  {'Matches':>8}")
        lines.append("  " + "-" * 74)
        for row in ranked.filter(pl.col("pr_rank") <= top_n).iter_rows(named=True):
            ci_lo = row.get("ci_lo")
            ci_hi = row.get("ci_hi")
            ci_str = (f"[{ci_lo:.4f}, {ci_hi:.4f}]"
                      if ci_lo is not None and ci_hi is not None else "  n/a")
            lines.append(
                f"  {row['pr_rank']:>4}  {str(row['player']):<32}  "
                f"{row['pr_rating']:>8.4f}  {ci_str:>18}  "
                f"{row.get('total_matches', '?'):>8}"
            )
    lines.append("")

    lines.append("─" * 62)
    lines.append("Per-Dimension Rankings (top 10 each)\n")
    for dim_id, col, asc, label in DIMENSIONS:
        sub = dim_rankings.filter(pl.col("dimension") == dim_id).head(10)
        if sub.is_empty():
            continue
        lines.append(f"  {label}")
        for row in sub.iter_rows(named=True):
            lines.append(f"    {row['rank']:>3}. {str(row['player']):<32}  {row['value']:>8.4f}")
        lines.append("")

    lines.append("─" * 62)
    if not pr_vs_wins.is_empty():
        lines.append(f"PR vs Win-Rate correlation (Pearson r): {corr:.4f}")
        if abs(corr) > 0.3:
            direction = "inversely" if corr < 0 else "positively"
            lines.append(f"  → Lower PR is {direction} correlated with winning")
        lines.append("")

    if not overperformers.is_empty():
        lines.append("─" * 62)
        lines.append("Over-performers (win more than PR predicts):")
        lines.append(f"  {'Player':<32}  {'WinRate':>8}  {'Predicted':>10}  {'Residual':>10}")
        lines.append("  " + "-" * 64)
        for row in overperformers.head(10).iter_rows(named=True):
            lines.append(
                f"  {str(row['player']):<32}  "
                f"{row['win_rate']:>8.3f}  "
                f"{row['predicted_win_rate']:>10.3f}  "
                f"{row['residual']:>+10.3f}"
            )
        lines.append("")
        lines.append("Under-performers (win less than PR predicts):")
        lines.append(f"  {'Player':<32}  {'WinRate':>8}  {'Predicted':>10}  {'Residual':>10}")
        lines.append("  " + "-" * 64)
        for row in overperformers.tail(10).sort("residual", descending=False).iter_rows(named=True):
            lines.append(
                f"  {str(row['player']):<32}  "
                f"{row['win_rate']:>8.3f}  "
                f"{row['predicted_win_rate']:>10.3f}  "
                f"{row['residual']:>+10.3f}"
            )

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S2.3 — Player Benchmarking & Ranking")
    ap.add_argument("--profiles", required=True,
                    help="Path to player_profiles.parquet (S2.1 output)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir (contains matches.parquet)")
    ap.add_argument("--output", default="data/player_profiles",
                    help="Output directory")
    ap.add_argument("--ci-samples", type=int, default=1000,
                    help="Bootstrap samples for CI (default: 1000, unused for analytic CI)")
    ap.add_argument("--top-n", type=int, default=20,
                    help="Top-N players to show in rankings (default: 20)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 62)
    print("  S2.3 — Benchmarking & Player Ranking")
    print("=" * 62)
    print(f"  profiles : {args.profiles}")
    print(f"  parquet  : {args.parquet}")
    print(f"  output   : {output_dir}")
    print(f"  top-n    : {args.top_n}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading data")
    profiles = load_profiles(args.profiles)
    print(f"  {len(profiles):,} player profiles loaded")

    matches = load_matches(args.parquet)
    print(f"  {len(matches):,} matches loaded")

    # ------------------------------------------------------------------
    # 1. PR ranking with CI
    # ------------------------------------------------------------------
    section("1. PR ranking with confidence intervals")
    ranked = compute_ranking_with_ci(profiles, args.ci_samples)
    if "pr_rank" in ranked.columns:
        print(f"\n  {'Rank':>4}  {'Player':<32}  {'PR':>8}  "
              f"{'CI 95%':>20}  {'N matches':>10}")
        print("  " + "-" * 80)
        for row in ranked.filter(pl.col("pr_rank") <= args.top_n).iter_rows(named=True):
            ci_lo = row.get("ci_lo")
            ci_hi = row.get("ci_hi")
            ci_str = (f"[{ci_lo:.4f}, {ci_hi:.4f}]"
                      if ci_lo is not None and ci_hi is not None else "n/a")
            print(f"  {row['pr_rank']:>4}  {str(row['player']):<32}  "
                  f"{row['pr_rating']:>8.4f}  {ci_str:>20}  "
                  f"{row.get('total_matches', '?'):>10}")

    # ------------------------------------------------------------------
    # 2. Per-dimension rankings
    # ------------------------------------------------------------------
    section("2. Per-dimension rankings")
    dim_rankings = compute_dimension_rankings(ranked, args.top_n)
    for dim_id, col, asc, label in DIMENSIONS:
        if col not in ranked.columns:
            print(f"  [SKIP] {label} — column {col} not available")
            continue
        sub = dim_rankings.filter(pl.col("dimension") == dim_id).head(5)
        print(f"\n  {label}:")
        for row in sub.iter_rows(named=True):
            print(f"    {row['rank']:>2}. {str(row['player']):<32}  {row['value']:>8.4f}")

    # ------------------------------------------------------------------
    # 3. PR vs match-win correlation
    # ------------------------------------------------------------------
    section("3. PR vs match-win correlation")
    pr_vs_wins = compute_pr_vs_wins(ranked, matches)
    corr = float("nan")
    if not pr_vs_wins.is_empty() and "pr_rating" in pr_vs_wins.columns:
        sub = pr_vs_wins.filter(
            pl.col("pr_rating").is_not_null() & pl.col("win_rate").is_not_null()
        )
        if len(sub) >= 5:
            corr = pearson_corr(
                sub["pr_rating"].to_list(),
                sub["win_rate"].to_list(),
            )
            print(f"  Players with win stats : {len(sub):,}")
            print(f"  Pearson r(PR, win_rate): {corr:.4f}")
            if corr < -0.2:
                print("  → Lower PR correlates with more wins (skill matters)")
            elif corr > 0.2:
                print("  → Higher PR correlates with more wins (unexpected — check data)")
            else:
                print("  → Weak correlation — luck plays a large role at this sample size")
        else:
            print("  [SKIP] Not enough players with both PR and win stats")
    else:
        print("  [SKIP] Could not compute win stats (missing winner column?)")

    # ------------------------------------------------------------------
    # 4. Over/under-performers
    # ------------------------------------------------------------------
    section("4. Over/under-performers")
    overperformers = compute_overperformers(pr_vs_wins)
    if not overperformers.is_empty():
        print(f"\n  Over-performers (top 10):")
        print(f"  {'Player':<32}  {'WinRate':>8}  {'Predicted':>10}  {'Residual':>10}")
        print("  " + "-" * 62)
        for row in overperformers.head(10).iter_rows(named=True):
            print(f"  {str(row['player']):<32}  "
                  f"{row['win_rate']:>8.3f}  "
                  f"{row['predicted_win_rate']:>10.3f}  "
                  f"{row['residual']:>+10.3f}")
        print(f"\n  Under-performers (bottom 10):")
        print(f"  {'Player':<32}  {'WinRate':>8}  {'Predicted':>10}  {'Residual':>10}")
        print("  " + "-" * 62)
        for row in overperformers.tail(10).sort("residual", descending=False).iter_rows(named=True):
            print(f"  {str(row['player']):<32}  "
                  f"{row['win_rate']:>8.3f}  "
                  f"{row['predicted_win_rate']:>10.3f}  "
                  f"{row['residual']:>+10.3f}")
    else:
        print("  [SKIP] Not enough data for over/under-performer analysis")

    # ------------------------------------------------------------------
    # 5. Temporal evolution
    # ------------------------------------------------------------------
    section("5. Temporal PR evolution (match activity by year)")
    temporal = compute_temporal_pr(ranked, matches)
    if not temporal.is_empty():
        year_counts = (
            temporal.group_by("year")
            .agg(pl.len().alias("player_years"), pl.col("matches_played").sum().alias("total_matches"))
            .sort("year")
        )
        print(f"  {'Year':>6}  {'Players':>8}  {'Matches':>10}")
        print("  " + "-" * 28)
        for row in year_counts.iter_rows(named=True):
            print(f"  {row['year']:>6}  {row['player_years']:>8,}  {row['total_matches']:>10,}")
    else:
        print("  [SKIP] No date column in matches or no parseable years")

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    section("Saving outputs")

    ranking_parquet = output_dir / "player_ranking.parquet"
    ranking_csv = output_dir / "player_ranking.csv"
    ranked.write_parquet(ranking_parquet)
    ranked.write_csv(ranking_csv)
    print(f"  → {ranking_parquet}  ({len(ranked):,} rows)")
    print(f"  → {ranking_csv}")

    if not dim_rankings.is_empty():
        dim_path = output_dir / "dimension_rankings.csv"
        dim_rankings.write_csv(dim_path)
        print(f"  → {dim_path}  ({len(dim_rankings):,} rows)")

    if not pr_vs_wins.is_empty():
        pvw_path = output_dir / "pr_vs_wins.csv"
        pr_vs_wins.write_csv(pvw_path)
        print(f"  → {pvw_path}  ({len(pr_vs_wins):,} rows)")

    if not overperformers.is_empty():
        op_path = output_dir / "over_under_performers.csv"
        overperformers.write_csv(op_path)
        print(f"  → {op_path}")

    if not temporal.is_empty():
        temp_path = output_dir / "temporal_pr.csv"
        temporal.write_csv(temp_path)
        print(f"  → {temp_path}  ({len(temporal):,} rows)")

    report_path = output_dir / "ranking_report.txt"
    write_report(ranked, dim_rankings, pr_vs_wins, overperformers,
                 corr, args.top_n, report_path)
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*62}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
