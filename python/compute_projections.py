#!/usr/bin/env python3
"""Compute UMAP/PCA projections + HDBSCAN clustering and output CSV.

This script is the batch pipeline that bridges feature extraction (Go/numpy)
and the GBF projection storage. It reads a features .npy file exported by
cmd/export-features, runs dimensionality reduction and clustering, and writes
a CSV ready for import-projections.

Usage:
    python compute_projections.py \
        --features features.npy \
        --ids position_ids.npy \
        --method umap_2d \
        --output projections.csv

Dependencies:
    pip install numpy umap-learn hdbscan scikit-learn

The --ids file contains position IDs (int64) matching each row of --features.
If --ids is not provided, row indices (1-based) are used as position_id.
"""

import argparse
import sys

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Compute projections for GBF positions")
    parser.add_argument("--features", required=True, help="Path to features .npy file (N x D)")
    parser.add_argument("--ids", help="Path to position_ids .npy file (N,) int64")
    parser.add_argument("--method", default="umap_2d", choices=["umap_2d", "pca_2d", "umap_3d", "pca_3d"])
    parser.add_argument("--output", default="projections.csv", help="Output CSV path")
    parser.add_argument("--n-neighbors", type=int, default=15, help="UMAP n_neighbors")
    parser.add_argument("--min-dist", type=float, default=0.1, help="UMAP min_dist")
    parser.add_argument("--min-cluster-size", type=int, default=100, help="HDBSCAN min_cluster_size")
    parser.add_argument("--sample", type=int, default=0, help="Subsample N rows (0 = all)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    print(f"Loading features from {args.features}...")
    features = np.load(args.features)
    print(f"  Shape: {features.shape}")

    if args.ids:
        position_ids = np.load(args.ids)
    else:
        position_ids = np.arange(1, len(features) + 1)

    assert len(position_ids) == len(features), "features and ids length mismatch"

    # Optional subsampling.
    if args.sample > 0 and args.sample < len(features):
        rng = np.random.default_rng(args.seed)
        idx = rng.choice(len(features), size=args.sample, replace=False)
        idx.sort()
        features = features[idx]
        position_ids = position_ids[idx]
        print(f"  Subsampled to {len(features)} rows")

    # Normalize (standard scaling).
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)

    # Dimensionality reduction.
    n_components = 3 if args.method.endswith("3d") else 2

    if args.method.startswith("umap"):
        import umap
        print(f"Running UMAP ({n_components}D, n_neighbors={args.n_neighbors}, min_dist={args.min_dist})...")
        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=args.n_neighbors,
            min_dist=args.min_dist,
            random_state=args.seed,
            verbose=True,
        )
        embedding = reducer.fit_transform(features_scaled)
    else:
        from sklearn.decomposition import PCA
        print(f"Running PCA ({n_components}D)...")
        reducer = PCA(n_components=n_components, random_state=args.seed)
        embedding = reducer.fit_transform(features_scaled)
        print(f"  Explained variance: {reducer.explained_variance_ratio_}")

    # Clustering (on the 2D/3D embedding).
    print(f"Running HDBSCAN (min_cluster_size={args.min_cluster_size})...")
    import hdbscan
    clusterer = hdbscan.HDBSCAN(min_cluster_size=args.min_cluster_size)
    cluster_labels = clusterer.fit_predict(embedding)
    n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    n_noise = (cluster_labels == -1).sum()
    print(f"  {n_clusters} clusters, {n_noise} noise points ({100*n_noise/len(cluster_labels):.1f}%)")

    # Write CSV.
    print(f"Writing {args.output}...")
    has_z = n_components == 3
    with open(args.output, "w") as f:
        if has_z:
            f.write("position_id,x,y,z,cluster_id\n")
        else:
            f.write("position_id,x,y,cluster_id\n")

        for i in range(len(embedding)):
            pid = int(position_ids[i])
            x = embedding[i, 0]
            y = embedding[i, 1]
            cid = int(cluster_labels[i]) if cluster_labels[i] >= 0 else ""
            if has_z:
                z = embedding[i, 2]
                f.write(f"{pid},{x:.6f},{y:.6f},{z:.6f},{cid}\n")
            else:
                f.write(f"{pid},{x:.6f},{y:.6f},{cid}\n")

    print(f"Done. {len(embedding)} points written.")


if __name__ == "__main__":
    main()
