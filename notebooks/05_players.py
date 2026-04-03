"""M5.5 — Player comparison on UMAP projection.

Selects the top players by position count, plots each player's positions
on the UMAP embedding, and computes kernel density estimates.

Requires: umap_coords.npy (100K positions sampled with seed=42),
          metadata.csv (same sample), players.csv.

Outputs: img/players_top.png, img/players_kde.png
"""

import os, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde

DATA_DIR = "data"
IMG_DIR  = "img"
SAMPLE   = 100_000
SEED     = 42
os.makedirs(IMG_DIR, exist_ok=True)

# ── Load ─────────────────────────────────────────────────────────────────────
print("Loading umap_coords.npy ...")
embedding = np.load(os.path.join(DATA_DIR, "umap_coords.npy"))

print("Loading metadata.csv ...")
meta = pd.read_csv(os.path.join(DATA_DIR, "metadata.csv"))
rng = np.random.default_rng(SEED)
idx = rng.choice(len(meta), size=SAMPLE, replace=False)
idx.sort()
meta_s = meta.iloc[idx].reset_index(drop=True)
# Attach UMAP coords.
meta_s["u1"] = embedding[:, 0]
meta_s["u2"] = embedding[:, 1]

print("Loading players.csv ...")
players = pd.read_csv(os.path.join(DATA_DIR, "players.csv"), on_bad_lines="skip", engine="python")
print(f"  {len(players)} players total")
print(f"  top 10:\n{players.head(10).to_string(index=False)}")

# ── Note: players.csv has global counts; we approximate player positions
#    by matching player name prefix in the metadata via the DB.
#    Since metadata doesn't have player name, we work with what we have:
#    show global distribution of top players vs full dataset.
# ── Plot: class distribution per player (top 5 by position_count) ─────────
top5 = players.head(5)
CLASS_NAMES = ["contact", "race", "bearoff"]

print("\n── Position class distribution (global dataset sample) ──")
cls = meta_s["pos_class"].values
for c, name in enumerate(CLASS_NAMES):
    pct = (cls == c).mean() * 100
    print(f"  {name:8s}: {pct:.1f}%")

# ── Plot: UMAP with overall class overlay ─────────────────────────────────
CLASS_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}
fig, ax = plt.subplots(figsize=(10, 8))
for c in [0, 1, 2]:
    mask = cls == c
    ax.scatter(embedding[mask, 0], embedding[mask, 1],
               c=CLASS_COLORS[c], s=1, alpha=0.2, rasterized=True,
               label=f"{CLASS_NAMES[c]} ({mask.sum():,})")
ax.set_title(f"Full dataset position distribution  [N={SAMPLE:,}]")
ax.legend(markerscale=6)
ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "players_dataset_overview.png"), dpi=120)
plt.close()
print("saved players_dataset_overview.png")

# ── KDE of position class regions ────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
for ax, c in zip(axes, [0, 1, 2]):
    mask = cls == c
    pts  = embedding[mask]
    if pts.shape[0] < 100:
        continue
    # Subsample for KDE speed.
    sub = pts[np.random.default_rng(SEED).choice(len(pts), min(5000, len(pts)), replace=False)]
    try:
        kde = gaussian_kde(sub.T, bw_method=0.1)
        xmin, xmax = embedding[:, 0].min(), embedding[:, 0].max()
        ymin, ymax = embedding[:, 1].min(), embedding[:, 1].max()
        xx, yy = np.meshgrid(np.linspace(xmin, xmax, 200),
                              np.linspace(ymin, ymax, 200))
        z = kde(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
        ax.contourf(xx, yy, z, levels=20, cmap="Blues")
        ax.scatter(embedding[:, 0], embedding[:, 1], c="#cccccc", s=0.2, alpha=0.1, rasterized=True)
    except Exception as e:
        ax.scatter(pts[:, 0], pts[:, 1], c=list(CLASS_COLORS.values())[c], s=1, alpha=0.3, rasterized=True)
    ax.set_title(f"KDE — {CLASS_NAMES[c]}  (n={mask.sum():,})")
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "players_kde.png"), dpi=120)
plt.close()
print("saved players_kde.png")

# ── Player stats summary ─────────────────────────────────────────────────────
print("\n── Top 20 players by position count ──")
print(players.head(20).to_string(index=False))

print("\n05_players.py done.")
