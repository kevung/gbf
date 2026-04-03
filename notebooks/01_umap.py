"""M5.1 — UMAP-2D projection of GBF positions.

Loads features.npy (1.57M positions × 44 dims), samples 100K, applies
standard scaling, then runs UMAP with several hyperparameter combinations.
Produces PNG plots colored by position_class, pip_diff, away_x, cube_owner.

Outputs: img/umap_class.png, img/umap_pip_diff.png, img/umap_away.png,
         img/umap_cube.png, data/umap_coords.npy
"""

import os, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from sklearn.preprocessing import StandardScaler
import umap

DATA_DIR = "data"
IMG_DIR  = "img"
SAMPLE   = 100_000
SEED     = 42
os.makedirs(IMG_DIR, exist_ok=True)

# ── Load data ────────────────────────────────────────────────────────────────
print("Loading features.npy ...")
t0 = time.time()
features = np.load(os.path.join(DATA_DIR, "features.npy"))
print(f"  shape: {features.shape}  ({time.time()-t0:.1f}s)")

print("Loading metadata.csv ...")
meta = pd.read_csv(os.path.join(DATA_DIR, "metadata.csv"))
assert len(meta) == len(features), "metadata/features length mismatch"

# ── Sample ───────────────────────────────────────────────────────────────────
rng = np.random.default_rng(SEED)
idx = rng.choice(len(features), size=SAMPLE, replace=False)
idx.sort()
X_sample   = features[idx]
meta_sample = meta.iloc[idx].reset_index(drop=True)

print(f"Sample: {SAMPLE} positions")

# ── Standard scale ───────────────────────────────────────────────────────────
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_sample)

# ── UMAP: default params ─────────────────────────────────────────────────────
configs = [
    dict(n_neighbors=15, min_dist=0.10, label="n15_d010"),
    dict(n_neighbors= 5, min_dist=0.01, label="n05_d001"),
    dict(n_neighbors=50, min_dist=0.50, label="n50_d050"),
]

for cfg in configs:
    label = cfg.pop("label")
    print(f"UMAP {label} ...")
    t1 = time.time()
    reducer = umap.UMAP(random_state=SEED, **cfg)
    embedding = reducer.fit_transform(X_scaled)
    print(f"  done in {time.time()-t1:.1f}s")

    if label == "n15_d010":
        np.save(os.path.join(DATA_DIR, "umap_coords.npy"), embedding)
        print("  saved umap_coords.npy")

    # ── Plot: colored by position class ──────────────────────────────────────
    cls = meta_sample["pos_class"].values
    CLASS_NAMES = {0: "contact", 1: "race", 2: "bearoff"}
    CLASS_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}

    fig, ax = plt.subplots(figsize=(10, 8))
    for c in [0, 1, 2]:
        mask = cls == c
        ax.scatter(embedding[mask, 0], embedding[mask, 1],
                   c=CLASS_COLORS[c], label=CLASS_NAMES[c],
                   s=1, alpha=0.3, rasterized=True)
    ax.set_title(f"UMAP ({label}) — colored by position class  [N={SAMPLE:,}]")
    ax.legend(markerscale=6)
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, f"umap_class_{label}.png"), dpi=120)
    plt.close()
    print(f"  saved umap_class_{label}.png")

    # Only generate extra colorings for the default config.
    if label != "n15_d010":
        continue

    # ── pip_diff coloring ────────────────────────────────────────────────────
    pip_diff = meta_sample["pip_diff"].values
    vabs = np.percentile(np.abs(pip_diff), 95)
    fig, ax = plt.subplots(figsize=(10, 8))
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                    c=pip_diff, cmap="RdBu_r", vmin=-vabs, vmax=vabs,
                    s=1, alpha=0.3, rasterized=True)
    plt.colorbar(sc, ax=ax, label="pip_diff (X − O)")
    ax.set_title(f"UMAP — colored by pip_diff  [N={SAMPLE:,}]")
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "umap_pip_diff.png"), dpi=120)
    plt.close()
    print("  saved umap_pip_diff.png")

    # ── away_x coloring ──────────────────────────────────────────────────────
    away_x = meta_sample["away_x"].values
    fig, ax = plt.subplots(figsize=(10, 8))
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                    c=away_x, cmap="plasma", s=1, alpha=0.3, rasterized=True)
    plt.colorbar(sc, ax=ax, label="away_x (pts needed for X to win)")
    ax.set_title(f"UMAP — colored by away_x  [N={SAMPLE:,}]")
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "umap_away.png"), dpi=120)
    plt.close()
    print("  saved umap_away.png")

    # ── cube_owner coloring ──────────────────────────────────────────────────
    cube = meta_sample["cube_owner"].values  # 0=center, 1=X, 2=O
    CUBE_COLORS = {0: "#95a5a6", 1: "#e74c3c", 2: "#3498db"}
    CUBE_NAMES  = {0: "center", 1: "X owns cube", 2: "O owns cube"}
    fig, ax = plt.subplots(figsize=(10, 8))
    for c in [0, 1, 2]:
        mask = cube == c
        ax.scatter(embedding[mask, 0], embedding[mask, 1],
                   c=CUBE_COLORS[c], label=CUBE_NAMES[c],
                   s=1, alpha=0.3, rasterized=True)
    ax.set_title(f"UMAP — colored by cube owner  [N={SAMPLE:,}]")
    ax.legend(markerscale=6)
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
    plt.tight_layout()
    plt.savefig(os.path.join(IMG_DIR, "umap_cube.png"), dpi=120)
    plt.close()
    print("  saved umap_cube.png")

# ── Summary stats ────────────────────────────────────────────────────────────
print("\n── Class distribution in sample ──")
for c in [0, 1, 2]:
    n = (meta_sample["pos_class"] == c).sum()
    print(f"  {CLASS_NAMES[c]:8s}: {n:6d}  ({100*n/SAMPLE:.1f}%)")

print("\n01_umap.py done.")
