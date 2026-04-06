#!/usr/bin/env python3
"""
S1.3 — Position Clustering
PCA → UMAP → HDBSCAN on enriched positions.
Outputs cluster labels, UMAP coordinates, and cluster profile CSVs.
"""

import argparse
import time
import sys
import warnings
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import umap
import hdbscan

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Features used for clustering (interpretable, no raw board, no eval leakage)
CLUSTER_FEATURES = [
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
    "score_away_p1", "score_away_p2",
]

CLUSTER_NAMES = {
    # Will be auto-named by dominant feature; these are hypothesis labels
}


def load_enriched(enriched_dir: str, decision_type: str, sample: int) -> pl.DataFrame:
    """Load enriched positions, filtering by decision_type, dropping nulls."""
    paths = list(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files found in {enriched_dir}")

    frames = []
    total = 0
    cols = CLUSTER_FEATURES + ["position_id", "move_played_error", "eval_equity",
                                "eval_win", "decision_type"]

    for p in sorted(paths):
        try:
            df = pl.read_parquet(p, columns=[c for c in cols
                                              if c in pl.read_parquet(p, n_rows=1).columns])
        except Exception:
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == decision_type)
        # Drop rows with any null in cluster features
        available = [f for f in CLUSTER_FEATURES if f in df.columns]
        df = df.drop_nulls(available)
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        return pl.DataFrame()

    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def run_pca(X: np.ndarray, n_components: int = 20) -> tuple[np.ndarray, PCA]:
    """PCA with variance explanation report."""
    n_comp = min(n_components, X.shape[1], X.shape[0] - 1)
    pca = PCA(n_components=n_comp, random_state=42)
    X_pca = pca.fit_transform(X)

    cumvar = np.cumsum(pca.explained_variance_ratio_)
    n90 = int(np.searchsorted(cumvar, 0.90)) + 1
    n95 = int(np.searchsorted(cumvar, 0.95)) + 1

    print(f"  PCA: {n_comp} components explain {cumvar[-1]*100:.1f}% variance")
    print(f"  → 90% at {n90} components, 95% at {n95} components")
    print(f"  Top-5 components: {pca.explained_variance_ratio_[:5]*100}")
    return X_pca, pca


def run_umap(X_pca: np.ndarray, n_neighbors: int = 15,
             min_dist: float = 0.1) -> np.ndarray:
    """UMAP dimensionality reduction to 2D."""
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric="euclidean",
        random_state=42,
        low_memory=True,
        verbose=False,
    )
    return reducer.fit_transform(X_pca)


def run_hdbscan(X_umap: np.ndarray, min_cluster_size: int,
                min_samples: int) -> np.ndarray:
    """HDBSCAN clustering on UMAP coordinates."""
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method="eom",
        prediction_data=True,
    )
    labels = clusterer.fit_predict(X_umap)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    noise_pct = (labels == -1).mean() * 100
    print(f"  HDBSCAN: {n_clusters} clusters, {noise_pct:.1f}% noise points")
    return labels


def cluster_profiles(df: pl.DataFrame, labels: np.ndarray,
                     features: list[str]) -> pl.DataFrame:
    """Compute per-cluster statistics."""
    df = df.with_columns(pl.Series("cluster", labels))
    available = [f for f in features if f in df.columns]
    agg_exprs = [pl.len().alias("count")]
    for f in available:
        agg_exprs.append(pl.col(f).mean().alias(f"mean_{f}"))
    if "move_played_error" in df.columns:
        agg_exprs.append(pl.col("move_played_error").mean().alias("mean_error"))
        agg_exprs.append(pl.col("move_played_error").median().alias("median_error"))
    if "eval_equity" in df.columns:
        agg_exprs.append(pl.col("eval_equity").mean().alias("mean_equity"))

    profiles = df.group_by("cluster").agg(agg_exprs).sort("cluster")
    return profiles


def label_cluster(row: dict, features: list[str]) -> str:
    """Heuristic cluster label from dominant feature values."""
    def _g(key, default=0): v = row.get(key); return default if v is None else v
    phase = _g("mean_match_phase")
    pip1 = _g("mean_pip_count_p1", 100)
    pip2 = _g("mean_pip_count_p2", 100)
    bar1 = _g("mean_num_on_bar_p1")
    bar2 = _g("mean_num_on_bar_p2")
    off1 = _g("mean_num_borne_off_p1")
    back = _g("mean_back_anchor_p1")
    prime1 = _g("mean_longest_prime_p1")
    prime2 = _g("mean_longest_prime_p2")
    blots1 = _g("mean_num_blots_p1")
    back_p1 = _g("mean_num_checkers_back_p1")

    if phase > 1.5:
        if off1 > 8:
            return "bearoff-advanced"
        return "bearoff"
    if phase > 0.5:
        return "race"
    # contact
    if back_p1 > 2 and back < 20:
        return "back-game"
    if prime1 >= 4 or prime2 >= 4:
        return "priming"
    if bar1 > 0.3 or bar2 > 0.3:
        return "blitz"
    if blots1 > 2 and back_p1 > 1:
        return "scramble"
    return "holding"


def print_profiles(profiles: pl.DataFrame) -> None:
    """Print readable cluster profile table."""
    print(f"\n  {'Cluster':>8} {'Label':<14} {'Count':>7} {'Error':>8} {'Phase':>6} {'Pip1':>5} {'Pip2':>5}")
    print("  " + "-" * 60)
    for row in profiles.iter_rows(named=True):
        cid = row["cluster"]
        if cid == -1:
            label = "noise"
        else:
            label = label_cluster(row, [])
        count = row["count"]
        def _f(key): v = row.get(key); return float("nan") if v is None else v
        err = _f("mean_error")
        phase = _f("mean_match_phase")
        pip1 = _f("mean_pip_count_p1")
        pip2 = _f("mean_pip_count_p2")
        print(f"  {cid:>8} {label:<14} {count:>7,} {err:>8.4f} {phase:>6.2f} {pip1:>5.0f} {pip2:>5.0f}")


def process(decision_type: str, enriched_dir: str, output_dir: Path,
            sample: int, n_neighbors: int, min_dist: float,
            min_cluster_size: int, min_samples: int,
            pca_components: int) -> None:
    label = decision_type
    print(f"\n{'─'*60}")
    print(f"  Clustering — {label.upper()} decisions")
    print(f"{'─'*60}")

    t0 = time.time()
    df = load_enriched(enriched_dir, decision_type, sample)
    if df.is_empty():
        print(f"  No data for decision_type={decision_type}")
        return

    print(f"  Loaded {len(df):,} rows ({time.time()-t0:.1f}s)")

    available_features = [f for f in CLUSTER_FEATURES if f in df.columns]
    X_raw = df.select(available_features).to_numpy().astype(np.float32)

    # Replace NaN with column mean
    col_means = np.nanmean(X_raw, axis=0)
    inds = np.where(np.isnan(X_raw))
    X_raw[inds] = np.take(col_means, inds[1])

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    print(f"  Running PCA ({pca_components} components)...")
    X_pca, pca = run_pca(X_scaled, n_components=pca_components)

    print(f"  Running UMAP (n_neighbors={n_neighbors}, min_dist={min_dist})...")
    t1 = time.time()
    X_umap = run_umap(X_pca, n_neighbors=n_neighbors, min_dist=min_dist)
    print(f"  UMAP done ({time.time()-t1:.1f}s)")

    print(f"  Running HDBSCAN (min_cluster_size={min_cluster_size})...")
    labels = run_hdbscan(X_umap, min_cluster_size, min_samples)

    # Build output dataframe
    id_col = "position_id" if "position_id" in df.columns else None
    out_rows = {
        "cluster": labels.tolist(),
        "umap_x": X_umap[:, 0].tolist(),
        "umap_y": X_umap[:, 1].tolist(),
    }
    if id_col:
        out_rows[id_col] = df[id_col].to_list()

    out_df = pl.DataFrame(out_rows)

    # Save cluster labels + UMAP coords
    labels_path = output_dir / f"clusters_{label}.parquet"
    out_df.write_parquet(labels_path)
    print(f"  → {labels_path}")

    # Cluster profiles
    profiles = cluster_profiles(df.with_columns(
        pl.Series("umap_x", X_umap[:, 0]),
        pl.Series("umap_y", X_umap[:, 1]),
    ), labels, available_features)
    profiles_path = output_dir / f"cluster_profiles_{label}.csv"
    profiles.write_csv(profiles_path)
    print(f"  → {profiles_path}")

    print_profiles(profiles)

    # PCA variance CSV
    pca_df = pl.DataFrame({
        "component": list(range(1, len(pca.explained_variance_ratio_) + 1)),
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
        "cumulative_variance": np.cumsum(pca.explained_variance_ratio_).tolist(),
    })
    pca_path = output_dir / f"pca_variance_{label}.csv"
    pca_df.write_csv(pca_path)
    print(f"  → {pca_path}")

    print(f"  Done in {time.time()-t0:.1f}s")


def main():
    ap = argparse.ArgumentParser(description="S1.3 — Position Clustering")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory (S0.4)")
    ap.add_argument("--output", default="data/clusters",
                    help="Output directory for cluster files")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max rows to sample per decision type (default: 500000)")
    ap.add_argument("--n-neighbors", type=int, default=15,
                    help="UMAP n_neighbors (default: 15)")
    ap.add_argument("--min-dist", type=float, default=0.1,
                    help="UMAP min_dist (default: 0.1)")
    ap.add_argument("--min-cluster-size", type=int, default=200,
                    help="HDBSCAN min_cluster_size (default: 200)")
    ap.add_argument("--min-samples", type=int, default=50,
                    help="HDBSCAN min_samples (default: 50)")
    ap.add_argument("--pca-components", type=int, default=20,
                    help="PCA components before UMAP (default: 20)")
    ap.add_argument("--types", nargs="+", default=["checker", "cube"],
                    help="Decision types to cluster (default: checker cube)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.3 — Position Clustering")
    print("=" * 60)
    print(f"  enriched : {args.enriched}")
    print(f"  output   : {output_dir}")
    print(f"  sample   : {args.sample:,} per type")

    for dtype in args.types:
        process(
            decision_type=dtype,
            enriched_dir=args.enriched,
            output_dir=output_dir,
            sample=args.sample,
            n_neighbors=args.n_neighbors,
            min_dist=args.min_dist,
            min_cluster_size=args.min_cluster_size,
            min_samples=args.min_samples,
            pca_components=args.pca_components,
        )

    print(f"\n{'='*60}")
    print(f"  Clustering complete — outputs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
