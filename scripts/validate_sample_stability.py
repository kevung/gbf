#!/usr/bin/env python3
"""Validate that subsampled analyses are representative of the full dataset.

Tests two things:
1. Distribution stability: sample vs full dataset feature distributions (KS test)
2. Cluster stability: cluster profiles are consistent across sample sizes

Usage:
    python scripts/validate_sample_stability.py \
        --enriched data/parquet/positions_enriched \
        [--sizes 5000,10000,25000,50000,100000]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats


FEATURES = [
    "pip_count_diff", "num_blots_p1", "num_points_made_p1",
    "home_board_points_p1", "longest_prime_p1", "back_anchor_p1",
    "num_checkers_back_p1", "gammon_threat", "gammon_risk",
    "match_phase",
]


def load_sample(enriched_dir: Path, n: int, seed: int = 42) -> pl.DataFrame:
    files = sorted(enriched_dir.glob("part-*.parquet"))
    per_file = max(1, n // len(files) + 1)
    dfs = []
    for f in files:
        df = pl.read_parquet(f, columns=FEATURES + ["decision_type"])
        df = df.filter(pl.col("decision_type") == "checker")
        if len(df) > per_file:
            df = df.sample(n=per_file, seed=seed)
        dfs.append(df)
    combined = pl.concat(dfs)
    if len(combined) > n:
        combined = combined.sample(n=n, seed=seed)
    return combined.drop("decision_type")


def distribution_stability_test(enriched_dir: Path, sizes: list[int]) -> None:
    """KS test: compare each sample size vs 100K reference sample."""
    print("=" * 60)
    print("  Distribution Stability (KS test vs 100K reference)")
    print("=" * 60)

    ref_size = max(sizes) if max(sizes) >= 100_000 else 100_000
    print(f"  Loading reference sample ({ref_size:,}) ...")
    ref = load_sample(enriched_dir, ref_size, seed=0)

    for feat in FEATURES:
        ref_vals = ref[feat].drop_nulls().to_numpy()
        print(f"\n  Feature: {feat}")
        for n in sizes:
            if n >= ref_size:
                continue
            samp = load_sample(enriched_dir, n, seed=42)
            samp_vals = samp[feat].drop_nulls().to_numpy()
            stat, p = stats.ks_2samp(ref_vals, samp_vals)
            ok = "OK " if p > 0.01 else "DIFF"
            print(f"    n={n:>7,}: KS={stat:.4f}  p={p:.4f}  [{ok}]")


def cluster_stability_test(enriched_dir: Path, sizes: list[int]) -> None:
    """Compare cluster profiles across sample sizes using k-means (fast)."""
    try:
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        print("sklearn not available — skipping cluster stability test")
        return

    print("\n" + "=" * 60)
    print("  Cluster Stability (k-means profiles across sample sizes)")
    print("=" * 60)

    k = 6
    results = {}

    for n in sizes:
        samp = load_sample(enriched_dir, n, seed=42)
        X = samp.select(FEATURES).fill_null(0).to_numpy().astype(np.float32)
        X = StandardScaler().fit_transform(X)
        km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=3)
        labels = km.fit_predict(X)
        sizes_pct = np.bincount(labels) / len(labels) * 100
        results[n] = sorted(sizes_pct, reverse=True)
        print(f"  n={n:>7,}: cluster sizes (%) = {[f'{p:.1f}' for p in results[n]]}")

    # Check that cluster size distribution is stable (max deviation < 10 pp)
    reference = results[max(sizes)]
    print(f"\n  Max deviation vs n={max(sizes):,} reference:")
    for n, sizes_pct in results.items():
        if n == max(sizes):
            continue
        max_dev = max(abs(a - b) for a, b in zip(sizes_pct, reference))
        ok = "STABLE" if max_dev < 10 else "UNSTABLE"
        print(f"    n={n:>7,}: max_dev={max_dev:.1f}pp  [{ok}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched", default="data/parquet/positions_enriched")
    parser.add_argument("--sizes", default="5000,10000,25000,50000,100000")
    args = parser.parse_args()

    enriched_dir = Path(args.enriched)
    if not enriched_dir.exists():
        print(f"ERROR: {enriched_dir} not found", file=sys.stderr)
        sys.exit(1)

    sizes = [int(x) for x in args.sizes.split(",")]
    print(f"Testing sample sizes: {sizes}")
    print(f"Features: {FEATURES}\n")

    distribution_stability_test(enriched_dir, sizes)
    cluster_stability_test(enriched_dir, sizes)


if __name__ == "__main__":
    main()
