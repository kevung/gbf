#!/usr/bin/env python3
"""
M0.7 Exp 3 — UMAP 2D projection of GBF positions.

Usage:
    python umap_viz.py [--csv /tmp/gbf_validate.db.umap.csv] [--out positions_umap.png]

Requirements:
    pip install umap-learn pandas matplotlib numpy
"""
import argparse
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    import umap
except ImportError:
    print("ERROR: umap-learn not installed. Run: pip install umap-learn", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="/tmp/gbf_validate.db.umap.csv")
    parser.add_argument("--out", default="positions_umap.png")
    args = parser.parse_args()

    print(f"Loading {args.csv} ...")
    df = pd.read_csv(args.csv)
    print(f"  {len(df)} positions, {df.shape[1]} features")

    if df.isnull().any().any():
        print("  WARNING: NaN values found, dropping rows")
        df = df.dropna()

    # Feature matrix: 24 point counts + bar + borne_off + pip + cube + away + side
    feature_cols = [c for c in df.columns]
    X = df[feature_cols].values.astype(np.float32)

    # Derived color: pip difference (pip_x - pip_o)
    pip_diff = df["pip_x"].values - df["pip_o"].values

    # Contact/race classification: no contact if neither player has checkers
    # behind the opponent's rear checker. Simple heuristic: pip_diff magnitude.
    is_race = np.abs(pip_diff) > 30

    print("Running UMAP (n_neighbors=15, min_dist=0.1) ...")
    reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, random_state=42)
    embedding = reducer.fit_transform(X)

    assert embedding.shape[1] == 2, "UMAP output must have 2 columns"
    assert not np.isnan(embedding).any(), "UMAP output contains NaN"

    # Save CSV
    emb_df = pd.DataFrame(embedding, columns=["umap_x", "umap_y"])
    emb_df["pip_diff"] = pip_diff
    emb_df["is_race"] = is_race
    emb_csv = args.out.replace(".png", ".csv")
    emb_df.to_csv(emb_csv, index=False)
    print(f"  Embedding saved to {emb_csv}")

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    sc1 = axes[0].scatter(
        embedding[:, 0], embedding[:, 1],
        c=pip_diff, cmap="RdBu", s=2, alpha=0.5, vmin=-50, vmax=50
    )
    plt.colorbar(sc1, ax=axes[0], label="pip_x - pip_o")
    axes[0].set_title("Colored by pip difference")
    axes[0].set_xlabel("UMAP-1")
    axes[0].set_ylabel("UMAP-2")

    colors = np.where(is_race, "#e74c3c", "#3498db")
    axes[1].scatter(
        embedding[:, 0], embedding[:, 1],
        c=colors, s=2, alpha=0.5
    )
    axes[1].set_title("Colored by contact (blue) vs race (red)")
    axes[1].set_xlabel("UMAP-1")
    axes[1].set_ylabel("UMAP-2")

    plt.suptitle(f"GBF Positions UMAP-2D ({len(df)} positions)", fontsize=13)
    plt.tight_layout()
    plt.savefig(args.out, dpi=150)
    print(f"  Plot saved to {args.out}")
    print("Exp 3: SUCCESS")


if __name__ == "__main__":
    main()
