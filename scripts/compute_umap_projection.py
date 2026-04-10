"""
compute_umap_projection.py — S4.7 UMAP pre-computation.

Scalable strategy for 160M positions:
  1. Load up to MAX_SAMPLE positions as the fit set.
  2. Fit UMAP (or PaCMAP) on the sample.
  3. Transform ALL positions in batches via umap.transform().
  4. Write (position_hash, umap_x, umap_y, move_played_error, match_phase,
     cluster_id) to data/positions_with_hash.parquet.

Usage:
    python scripts/compute_umap_projection.py \\
        [--data-dir ./data] [--sample 2000000] [--n-components 2] \\
        [--algo umap|pacmap] [--batch-size 500000]
"""
import argparse
import time
from pathlib import Path

import numpy as np
import polars as pl


FEATURES = [
    "pip_count_p1", "pip_count_p2", "blots_p1", "blots_p2",
    "home_board_strength_p1", "home_board_strength_p2",
    "prime_length_p1", "prime_length_p2",
    "checkers_in_home_p1", "checkers_in_home_p2",
    "contact_count", "match_phase",
    "away_p1", "away_p2",
]


def run(
    data_dir: Path,
    sample:   int   = 2_000_000,
    algo:     str   = "umap",
    n_comps:  int   = 2,
    batch:    int   = 500_000,
) -> None:
    t0 = time.time()
    out_path = data_dir / "positions_with_hash.parquet"

    print(f"Loading positions from {data_dir}/positions_enriched/…")
    df = pl.scan_parquet(str(data_dir / "positions_enriched" / "*.parquet"))

    # Select columns we need (features + meta)
    meta_cols  = ["position_hash", "move_played_error", "match_phase", "cluster_id"]
    avail_feat = [c for c in FEATURES if c in df.collect_schema().names()]
    if not avail_feat:
        raise RuntimeError(f"No feature columns found. Expected one of: {FEATURES}")

    all_cols = list(dict.fromkeys(avail_feat + meta_cols))
    df_full  = df.select([c for c in all_cols if c in df.collect_schema().names()]).collect()
    N        = len(df_full)
    print(f"  Total positions: {N:,}")

    # ── Build feature matrix ───────────────────────────────────────────────────
    feat_df = df_full.select(avail_feat).fill_null(0).fill_nan(0)
    X_full  = feat_df.to_numpy().astype(np.float32)

    # Standardise
    mean = X_full.mean(axis=0)
    std  = X_full.std(axis=0) + 1e-8
    X_full = (X_full - mean) / std

    # ── Sample for fitting ────────────────────────────────────────────────────
    n_fit   = min(sample, N)
    idx_fit = np.random.default_rng(42).choice(N, size=n_fit, replace=False)
    X_fit   = X_full[idx_fit]
    print(f"  Fit sample: {n_fit:,}  features: {len(avail_feat)}")

    # ── Fit projection ────────────────────────────────────────────────────────
    if algo == "pacmap":
        try:
            import pacmap
            reducer = pacmap.PaCMAP(n_components=n_comps, random_state=42)
            print("  Fitting PaCMAP…")
            reducer.fit_transform(X_fit)
        except ImportError:
            print("  PaCMAP not installed, falling back to UMAP")
            algo = "umap"

    if algo == "umap":
        try:
            import umap as umap_lib
        except ImportError:
            raise ImportError("Install umap-learn: pip install umap-learn")
        print("  Fitting UMAP…")
        reducer = umap_lib.UMAP(
            n_components=n_comps,
            n_neighbors=15,
            min_dist=0.1,
            metric="euclidean",
            random_state=42,
            low_memory=True,
            verbose=True,
        )
        reducer.fit(X_fit)

    print(f"  Fit done in {time.time()-t0:.1f}s")

    # ── Transform all positions in batches ────────────────────────────────────
    coords = np.zeros((N, n_comps), dtype=np.float32)
    n_batches = (N + batch - 1) // batch
    print(f"  Transforming {N:,} positions in {n_batches} batches…")

    for i in range(n_batches):
        lo, hi = i * batch, min((i + 1) * batch, N)
        if algo == "umap":
            coords[lo:hi] = reducer.transform(X_full[lo:hi])
        else:
            # PaCMAP: incremental transform not supported; use approximate embedding
            coords[lo:hi] = reducer.transform(X_full[lo:hi])
        if (i + 1) % 10 == 0 or i == n_batches - 1:
            print(f"    batch {i+1}/{n_batches}  ({hi:,} done)")

    # ── Build output DataFrame ────────────────────────────────────────────────
    meta_available = [c for c in meta_cols if c in df_full.columns]
    result = df_full.select(meta_available).with_columns([
        pl.Series("umap_x", coords[:, 0]),
        pl.Series("umap_y", coords[:, 1]),
    ])

    result.write_parquet(str(out_path))
    elapsed = time.time() - t0
    print(f"\n✓ Written {len(result):,} rows → {out_path}  ({elapsed:.1f}s)")
    print(f"  UMAP x range: [{float(coords[:,0].min()):.2f}, {float(coords[:,0].max()):.2f}]")
    print(f"  UMAP y range: [{float(coords[:,1].min()):.2f}, {float(coords[:,1].max()):.2f}]")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="UMAP projection for GBF position map")
    p.add_argument("--data-dir",    default="data")
    p.add_argument("--sample",      type=int, default=2_000_000)
    p.add_argument("--algo",        choices=["umap", "pacmap"], default="umap")
    p.add_argument("--n-components",type=int, default=2)
    p.add_argument("--batch-size",  type=int, default=500_000)
    args = p.parse_args()
    run(
        data_dir  = Path(args.data_dir),
        sample    = args.sample,
        algo      = args.algo,
        n_comps   = args.n_components,
        batch     = args.batch_size,
    )
