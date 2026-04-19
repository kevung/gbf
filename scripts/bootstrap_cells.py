#!/usr/bin/env python3
"""
BE.2 — Bootstrap Resampling for Cell Statistics

Replaces the single-sample per-cell aggregates from RG.1 with bootstrap-
averaged estimates that carry an uncertainty (std across K sub-samples).

For each draw the script computes per-cell mean values of the P1-POV
barycentric metrics, then aggregates those draw-level means into a final
mean ± std table.  Two sampling modes are supported:

  uniform    — draw draw_size rows from the whole dataset each time
               (cells are represented proportional to their natural frequency)
  stratified — draw exactly stratified_per_cell rows from each cell each
               time (all cells equally represented; reveals per-cell noise)

The crawford_variant column is derived here so this script is independent
of BE.3 (which publishes the canonical cell_keys.parquet for the UI).

Outputs
-------
  <output>                bootstrap_cells.parquet
  <report>                bootstrap_report.txt

Usage
-----
  python scripts/bootstrap_cells.py \\
      --input  data/barycentric/barycentric_v2.parquet \\
      --output data/barycentric/bootstrap_cells.parquet \\
      --report data/barycentric/bootstrap_report.txt \\
      [--k 50] [--draw-size 500000] [--stratified-per-cell 500] \\
      [--min-per-cell 50] [--min-per-cell-draw 10] \\
      [--seed 42] [--modes uniform,stratified] [--with-replacement]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import polars as pl


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

METRICS = [
    "bary_p1_a", "bary_p1_b",
    "disp_p1_a", "disp_p1_b", "disp_magnitude_p1",
    "cubeless_mwc_p1", "cube_gap_p1", "cubeful_equity_p1",
]
CELL_KEYS = ["score_away_p1", "score_away_p2", "crawford_variant"]


# ---------------------------------------------------------------------------
# crawford_variant derivation (mirrors BE.3 rules)
# ---------------------------------------------------------------------------

def add_crawford_variant(df: pl.DataFrame) -> pl.DataFrame:
    """Add a 'crawford_variant' column derived from crawford / is_post_crawford."""
    is_one_away = (
        (pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1)
    )
    variant = (
        pl.when(~is_one_away)
        .then(pl.lit("normal"))
        .when(pl.col("crawford"))
        .then(pl.lit("crawford"))
        .when(pl.col("is_post_crawford"))
        .then(pl.lit("post_crawford"))
        .otherwise(pl.lit("normal"))  # anomalous — fall back silently
    )
    return df.with_columns(variant.alias("crawford_variant"))


# ---------------------------------------------------------------------------
# Per-draw aggregation
# ---------------------------------------------------------------------------

def agg_draw(draw: pl.DataFrame, min_per_cell_draw: int) -> pl.DataFrame:
    """Aggregate one draw into per-cell means + covariance."""
    agg = (
        draw
        .group_by(CELL_KEYS)
        .agg(
            [pl.len().alias("n_draw")]
            + [pl.col(m).mean().alias(f"mean_{m}") for m in METRICS]
            + [pl.cov("bary_p1_a", "bary_p1_b").alias("cov_bary_p1_ab")]
        )
        .filter(pl.col("n_draw") >= min_per_cell_draw)
    )
    return agg


# ---------------------------------------------------------------------------
# Bootstrap loop (one sampling mode)
# ---------------------------------------------------------------------------

def run_mode(
    full: pl.DataFrame,
    n_total_per_cell: pl.DataFrame,  # (CELL_KEYS + ["n_total"])
    mode: str,
    K: int,
    draw_size: int,
    stratified_per_cell: int,
    min_per_cell_draw: int,
    seed: int,
    with_replacement: bool,
) -> pl.DataFrame:
    """Run K draws for one sampling mode; return stacked per-draw aggregates."""
    draw_aggs: list[pl.DataFrame] = []
    n_full = len(full)
    t0 = time.time()

    for k in range(K):
        rng_seed = seed + k

        if mode == "uniform":
            n = min(draw_size, n_full) if not with_replacement else draw_size
            draw = full.sample(n=n, seed=rng_seed, with_replacement=with_replacement)
        else:  # stratified
            # Sample per cell: fixes the random seed per-cell using rng_seed
            draw = (
                full
                .group_by(CELL_KEYS)
                .map_groups(
                    lambda g: g.sample(
                        n=min(stratified_per_cell, len(g)),
                        seed=rng_seed,
                        with_replacement=with_replacement,
                    )
                )
            )

        agg = agg_draw(draw, min_per_cell_draw)
        agg = agg.with_columns(pl.lit(k, dtype=pl.Int32).alias("_draw_k"))
        draw_aggs.append(agg)

        if (k + 1) % 10 == 0 or k == K - 1:
            elapsed = time.time() - t0
            print(f"    [{mode}] draw {k+1:3d}/{K}  ({elapsed:.1f}s)", flush=True)

    stacked = pl.concat(draw_aggs, how="diagonal")

    # Aggregate across draws: mean / std / p05 / p95 of the per-draw cell means
    metric_aggs = []
    for m in METRICS:
        col = f"mean_{m}"
        metric_aggs += [
            pl.col(col).mean().alias(f"{col}_mean"),
            pl.col(col).std(ddof=1).alias(f"{col}_std"),
            pl.col(col).quantile(0.05, interpolation="linear").alias(f"{col}_p05"),
            pl.col(col).quantile(0.95, interpolation="linear").alias(f"{col}_p95"),
        ]

    final = (
        stacked
        .group_by(CELL_KEYS)
        .agg(
            [
                pl.len().alias("n_draws"),
                pl.col("n_draw").mean().alias("mean_n_in_draw"),
            ]
            + metric_aggs
            + [
                pl.col("cov_bary_p1_ab").mean().alias("cov_bary_p1_ab_mean"),
                pl.col("cov_bary_p1_ab").std(ddof=1).alias("cov_bary_p1_ab_std"),
            ]
        )
        .with_columns(pl.lit(mode).alias("sampling_mode"))
    )

    # Join n_total and draw_size
    final = final.join(n_total_per_cell, on=CELL_KEYS, how="left")
    final = final.with_columns(
        pl.lit(draw_size if mode == "uniform" else stratified_per_cell)
        .alias("draw_size")
    )

    return final


# ---------------------------------------------------------------------------
# Post-processing: cell_id, low_support
# ---------------------------------------------------------------------------

def add_cell_id(df: pl.DataFrame) -> pl.DataFrame:
    cell_id = (
        pl.lit("a") + pl.col("score_away_p1").cast(pl.Utf8)
        + pl.lit("_b") + pl.col("score_away_p2").cast(pl.Utf8)
        + pl.lit("_") + pl.col("crawford_variant")
    )
    return df.with_columns(cell_id.alias("cell_id"))


def add_low_support(df: pl.DataFrame, min_per_cell: int, K: int) -> pl.DataFrame:
    low = (
        (pl.col("n_total") < min_per_cell)
        | (pl.col("n_draws") < 0.5 * K)
        | pl.col("n_total").is_null()
    )
    return df.with_columns(low.alias("low_support"))


# ---------------------------------------------------------------------------
# Column ordering
# ---------------------------------------------------------------------------

def ordered_columns(df: pl.DataFrame) -> pl.DataFrame:
    head = ["cell_id", "score_away_p1", "score_away_p2", "crawford_variant",
            "sampling_mode", "n_total", "n_draws", "draw_size",
            "mean_n_in_draw", "low_support"]
    metric_cols = []
    for m in METRICS:
        col = f"mean_{m}"
        metric_cols += [f"{col}_mean", f"{col}_std", f"{col}_p05", f"{col}_p95"]
    tail = ["cov_bary_p1_ab_mean", "cov_bary_p1_ab_std"]

    wanted = head + metric_cols + tail
    present = [c for c in wanted if c in df.columns]
    extra   = [c for c in df.columns if c not in present]
    return df.select(present + extra)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    df: pl.DataFrame,
    path: Path,
    K: int,
    draw_size: int,
    stratified_per_cell: int,
    seed: int,
    modes: list[str],
    min_per_cell: int,
    elapsed: float,
) -> None:
    lines = [
        "BE.2 — Bootstrap Cell Statistics Report",
        "=" * 60, "",
        f"K (draws)           : {K}",
        f"Draw size (uniform) : {draw_size:,}",
        f"Per-cell (strat.)   : {stratified_per_cell}",
        f"Base seed           : {seed}",
        f"Modes               : {', '.join(modes)}",
        f"Min per cell        : {min_per_cell}",
        f"Elapsed             : {elapsed:.1f}s",
        "",
        f"Output rows         : {len(df):,}",
        "",
    ]

    for mode in modes:
        sub = df.filter(pl.col("sampling_mode") == mode)
        n_low = sub.filter(pl.col("low_support"))["low_support"].sum()
        lines += [
            f"── Mode: {mode} ──",
            f"  Cells            : {len(sub)}",
            f"  Low-support cells: {n_low}",
            "",
        ]

        mwc_std_col = "mean_cubeless_mwc_p1_std"
        if mwc_std_col in sub.columns:
            valid = sub.filter(pl.col(mwc_std_col).is_not_null())
            if not valid.is_empty():
                top_noisy = valid.sort(mwc_std_col, descending=True).head(10)
                lines.append(f"  Top 10 noisiest cells ({mwc_std_col}):")
                lines.append(f"  {'a':>4}  {'b':>4}  {'variant':<14}  "
                             f"{'n_total':>8}  {'mwc_mean':>10}  {'mwc_std':>10}")
                lines.append("  " + "-" * 58)
                for row in top_noisy.iter_rows(named=True):
                    lines.append(
                        f"  {row['score_away_p1']:>4}  {row['score_away_p2']:>4}  "
                        f"{row['crawford_variant']:<14}  "
                        f"{row.get('n_total', 0) or 0:>8,}  "
                        f"{row.get('mean_cubeless_mwc_p1_mean', float('nan')):>10.4f}  "
                        f"{row[mwc_std_col]:>10.4f}"
                    )
                lines.append("")

                top_stable = valid.sort(mwc_std_col).head(10)
                lines.append(f"  Top 10 most stable cells ({mwc_std_col}):")
                lines.append(f"  {'a':>4}  {'b':>4}  {'variant':<14}  "
                             f"{'n_total':>8}  {'mwc_mean':>10}  {'mwc_std':>10}")
                lines.append("  " + "-" * 58)
                for row in top_stable.iter_rows(named=True):
                    lines.append(
                        f"  {row['score_away_p1']:>4}  {row['score_away_p2']:>4}  "
                        f"{row['crawford_variant']:<14}  "
                        f"{row.get('n_total', 0) or 0:>8,}  "
                        f"{row.get('mean_cubeless_mwc_p1_mean', float('nan')):>10.4f}  "
                        f"{row[mwc_std_col]:>10.4f}"
                    )
                lines.append("")

        low_rows = sub.filter(pl.col("low_support")).sort(
            ["score_away_p1", "score_away_p2"])
        if not low_rows.is_empty():
            lines.append("  Low-support cells:")
            for row in low_rows.iter_rows(named=True):
                lines.append(
                    f"    {row['score_away_p1']}a-{row['score_away_p2']}a "
                    f"({row['crawford_variant']})  n_total={row.get('n_total')}"
                )
            lines.append("")

    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="BE.2 — Bootstrap Resampling for Cell Statistics")
    ap.add_argument("--input",
                    default="data/barycentric/barycentric_v2.parquet",
                    help="Input barycentric_v2 parquet")
    ap.add_argument("--output",
                    default="data/barycentric/bootstrap_cells.parquet",
                    help="Output parquet")
    ap.add_argument("--report",
                    default="data/barycentric/bootstrap_report.txt",
                    help="Text report")
    ap.add_argument("--k", type=int, default=50,
                    help="Number of bootstrap draws (default: 50)")
    ap.add_argument("--draw-size", type=int, default=500_000,
                    help="Rows per uniform draw (default: 500000)")
    ap.add_argument("--stratified-per-cell", type=int, default=500,
                    help="Rows per cell per stratified draw (default: 500)")
    ap.add_argument("--min-per-cell", type=int, default=50,
                    help="Low-support threshold on n_total (default: 50)")
    ap.add_argument("--min-per-cell-draw", type=int, default=10,
                    help="Skip cell in a draw if fewer rows (default: 10)")
    ap.add_argument("--seed", type=int, default=42,
                    help="Base RNG seed (default: 42)")
    ap.add_argument("--modes", default="uniform,stratified",
                    help="Comma-separated modes: uniform,stratified")
    ap.add_argument("--with-replacement", action="store_true",
                    help="Use sampling with replacement (classical bootstrap)")
    args = ap.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in ("uniform", "stratified"):
            sys.exit(f"Unknown mode: {m!r}. Use 'uniform' and/or 'stratified'.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report)

    print("=" * 60)
    print("  BE.2 — Bootstrap Resampling for Cell Statistics")
    print("=" * 60)
    print(f"  input      : {args.input}")
    print(f"  K          : {args.k}")
    print(f"  draw-size  : {args.draw_size:,}  (uniform)")
    print(f"  strat/cell : {args.stratified_per_cell}  (stratified)")
    print(f"  modes      : {', '.join(modes)}")
    print(f"  seed       : {args.seed}")
    print(f"  replacement: {args.with_replacement}")

    t0 = time.time()

    # 1. Load full dataset into memory
    print("\n  Loading data...")
    needed_cols = (
        ["score_away_p1", "score_away_p2", "crawford", "is_post_crawford"]
        + METRICS
    )
    full = pl.read_parquet(args.input, columns=needed_cols)
    full = add_crawford_variant(full)
    n_full = len(full)
    print(f"  {n_full:,} rows loaded ({time.time()-t0:.1f}s)")

    # 2. Compute n_total per cell (authoritative count from the full dataset)
    n_total_per_cell = (
        full
        .group_by(CELL_KEYS)
        .agg(pl.len().alias("n_total"))
    )
    print(f"  {len(n_total_per_cell)} distinct cells "
          f"(score × crawford_variant)")

    # 3. Run bootstrap for each mode
    all_results: list[pl.DataFrame] = []
    for mode in modes:
        print(f"\n  Running mode={mode} (K={args.k})...")
        result = run_mode(
            full=full,
            n_total_per_cell=n_total_per_cell,
            mode=mode,
            K=args.k,
            draw_size=args.draw_size,
            stratified_per_cell=args.stratified_per_cell,
            min_per_cell_draw=args.min_per_cell_draw,
            seed=args.seed,
            with_replacement=args.with_replacement,
        )
        all_results.append(result)
        print(f"    {len(result)} cells after aggregation")

    # 4. Combine all modes
    combined = pl.concat(all_results, how="diagonal")

    # 5. Post-process
    combined = add_cell_id(combined)
    combined = add_low_support(combined, args.min_per_cell, args.k)
    combined = ordered_columns(combined)
    combined = combined.sort(
        ["sampling_mode", "score_away_p1", "score_away_p2", "crawford_variant"]
    )

    # 6. Write output
    print(f"\n  Writing {len(combined):,} rows to {output_path}...")
    combined.write_parquet(output_path)
    sz = output_path.stat().st_size / 1e6
    print(f"    -> {output_path} ({sz:.1f} MB)")

    # 7. Report
    elapsed = time.time() - t0
    write_report(
        combined, report_path,
        K=args.k, draw_size=args.draw_size,
        stratified_per_cell=args.stratified_per_cell,
        seed=args.seed, modes=modes,
        min_per_cell=args.min_per_cell,
        elapsed=elapsed,
    )
    print(f"    -> {report_path}")

    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
