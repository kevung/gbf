"""M5.3 — HDBSCAN + k-means clustering on UMAP-2D coordinates.

Uses pre-computed UMAP embedding (data/umap_coords.npy) from notebook 01.
Loads the matching metadata slice (first 100K rows sampled with same seed).

Outputs: img/clustering_hdbscan.png, img/clustering_kmeans.png,
         data/cluster_labels.npy
"""

import os, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import silhouette_score

DATA_DIR = "data"
IMG_DIR  = "img"
SAMPLE   = 100_000
SEED     = 42
os.makedirs(IMG_DIR, exist_ok=True)

CLASS_NAMES  = {0: "contact", 1: "race", 2: "bearoff"}
CLASS_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}

# ── Load UMAP coords + matching metadata ────────────────────────────────────
print("Loading umap_coords.npy ...")
embedding = np.load(os.path.join(DATA_DIR, "umap_coords.npy"))
assert len(embedding) == SAMPLE, f"expected {SAMPLE} rows, got {len(embedding)}"

print("Loading metadata.csv ...")
meta = pd.read_csv(os.path.join(DATA_DIR, "metadata.csv"))
rng = np.random.default_rng(SEED)
idx = rng.choice(len(meta), size=SAMPLE, replace=False)
idx.sort()
meta_s = meta.iloc[idx].reset_index(drop=True)
cls = meta_s["pos_class"].values

# ── HDBSCAN ─────────────────────────────────────────────────────────────────
print("Running HDBSCAN (min_cluster_size=200) ...")
t0 = time.time()
hdb = HDBSCAN(min_cluster_size=200, min_samples=50)
labels_hdb = hdb.fit_predict(embedding)
print(f"  done in {time.time()-t0:.1f}s")

n_clusters = len(set(labels_hdb)) - (1 if -1 in labels_hdb else 0)
noise_frac  = (labels_hdb == -1).mean()
print(f"  clusters found: {n_clusters}")
print(f"  noise fraction: {100*noise_frac:.1f}%")

np.save(os.path.join(DATA_DIR, "cluster_labels.npy"), labels_hdb)

# Cluster profiles.
print("\n── HDBSCAN cluster profiles ──")
for cl in sorted(set(labels_hdb)):
    if cl == -1:
        continue
    mask = labels_hdb == cl
    cnt  = mask.sum()
    cls_dist = {c: (cls[mask] == c).mean() for c in [0, 1, 2]}
    dom_cls  = max(cls_dist, key=cls_dist.get)
    pip_diff_mean = meta_s["pip_diff"].values[mask].mean()
    away_x_mean   = meta_s["away_x"].values[mask].mean()
    print(f"  cluster {cl:2d}: {cnt:5d} pts | "
          f"contact={100*cls_dist[0]:.0f}% race={100*cls_dist[1]:.0f}% "
          f"bearoff={100*cls_dist[2]:.0f}% | "
          f"pip_diff={pip_diff_mean:+.0f} away_x={away_x_mean:.0f}")

# Plot HDBSCAN.
fig, ax = plt.subplots(figsize=(10, 8))
noise = labels_hdb == -1
ax.scatter(embedding[noise, 0], embedding[noise, 1],
           c="#cccccc", s=1, alpha=0.2, rasterized=True, label="noise")
unique_cls = [l for l in sorted(set(labels_hdb)) if l != -1]
cmap = plt.cm.get_cmap("tab20", len(unique_cls))
for i, cl in enumerate(unique_cls):
    mask = labels_hdb == cl
    ax.scatter(embedding[mask, 0], embedding[mask, 1],
               c=[cmap(i)], s=1, alpha=0.5, rasterized=True, label=f"cl {cl}")
ax.set_title(f"HDBSCAN: {n_clusters} clusters, {100*noise_frac:.1f}% noise  [N={SAMPLE:,}]")
ax.legend(markerscale=5, ncol=3, fontsize=7, loc="upper right")
ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "clustering_hdbscan.png"), dpi=120)
plt.close()
print("\nsaved clustering_hdbscan.png")

# ── K-means ──────────────────────────────────────────────────────────────────
print("\nRunning K-means (k=10) ...")
t1 = time.time()
km = KMeans(n_clusters=10, n_init=5, random_state=SEED)
labels_km = km.fit_predict(embedding)
print(f"  done in {time.time()-t1:.1f}s")

# Silhouette on 10K subsample (full is too slow).
sub_idx = np.random.default_rng(SEED+1).choice(SAMPLE, 10_000, replace=False)
sil = silhouette_score(embedding[sub_idx], labels_km[sub_idx])
print(f"  silhouette score (10K sample): {sil:.3f}")

fig, ax = plt.subplots(figsize=(10, 8))
cmap_km = plt.cm.get_cmap("tab10", 10)
for k in range(10):
    mask = labels_km == k
    ax.scatter(embedding[mask, 0], embedding[mask, 1],
               c=[cmap_km(k)], s=1, alpha=0.4, rasterized=True, label=f"k={k}")
ax.set_title(f"K-means (k=10), silhouette={sil:.3f}  [N={SAMPLE:,}]")
ax.legend(markerscale=5, ncol=2, fontsize=8)
ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "clustering_kmeans.png"), dpi=120)
plt.close()
print("saved clustering_kmeans.png")

print("\n03_clustering.py done.")
