"""M5.2 — PCA on GBF feature matrix.

Loads all features (1.57M × 44), fits PCA on a 200K sample, then:
  - Plots cumulative explained variance vs number of components
  - Plots PC1 vs PC2 colored by position_class
  - Prints loadings table for the top 10 components

Outputs: img/pca_variance.png, img/pca_pc1_pc2.png, data/pca_coords.npy
"""

import os, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

DATA_DIR = "data"
IMG_DIR  = "img"
SAMPLE   = 200_000
SEED     = 42
os.makedirs(IMG_DIR, exist_ok=True)

FEATURE_NAMES = [
    *[f"pt_{i:02d}" for i in range(24)],
    "bar_x", "bar_o", "borne_off_x", "borne_off_o",
    "pip_x", "pip_o", "cube_log2", "cube_owner",
    "away_x", "away_o",
    "blot_x", "blot_o", "made_x", "made_o",
    "prime_x", "prime_o", "anchor_x", "anchor_o",
    "pip_diff", "pos_class",
]
assert len(FEATURE_NAMES) == 44

# ── Load ─────────────────────────────────────────────────────────────────────
print("Loading features.npy ...")
t0 = time.time()
features = np.load(os.path.join(DATA_DIR, "features.npy"))
print(f"  shape: {features.shape}  ({time.time()-t0:.1f}s)")

meta = pd.read_csv(os.path.join(DATA_DIR, "metadata.csv"))

rng = np.random.default_rng(SEED)
idx = rng.choice(len(features), size=SAMPLE, replace=False)
idx.sort()
X_sample = features[idx]
meta_s   = meta.iloc[idx].reset_index(drop=True)

# ── Scale + PCA ───────────────────────────────────────────────────────────────
print(f"Fitting PCA on {SAMPLE:,} positions ...")
t1 = time.time()
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_sample)
pca = PCA(n_components=44, random_state=SEED)
coords = pca.fit_transform(X_scaled)
print(f"  done in {time.time()-t1:.1f}s")

np.save(os.path.join(DATA_DIR, "pca_coords.npy"), coords[:, :2])

# ── Cumulative variance ───────────────────────────────────────────────────────
cumvar = np.cumsum(pca.explained_variance_ratio_)
n90 = int(np.searchsorted(cumvar, 0.90)) + 1
n80 = int(np.searchsorted(cumvar, 0.80)) + 1
n50 = int(np.searchsorted(cumvar, 0.50)) + 1

print(f"\nVariance explained:")
print(f"  PC1:          {100*pca.explained_variance_ratio_[0]:.1f}%")
print(f"  PC1+PC2:      {100*cumvar[1]:.1f}%")
print(f"  PC1..PC3:     {100*cumvar[2]:.1f}%")
print(f"  50% variance: {n50} components")
print(f"  80% variance: {n80} components")
print(f"  90% variance: {n90} components")

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(range(1, 45), 100 * cumvar, marker="o", markersize=4)
ax.axhline(90, color="red",    linestyle="--", label="90%")
ax.axhline(80, color="orange", linestyle="--", label="80%")
ax.axhline(50, color="green",  linestyle="--", label="50%")
ax.axvline(n90, color="red",    linestyle=":", alpha=0.6)
ax.axvline(n80, color="orange", linestyle=":", alpha=0.6)
ax.axvline(n50, color="green",  linestyle=":", alpha=0.6)
ax.set_xlabel("Number of components")
ax.set_ylabel("Cumulative variance explained (%)")
ax.set_title(f"PCA — cumulative variance  [N={SAMPLE:,}]")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "pca_variance.png"), dpi=120)
plt.close()
print("saved pca_variance.png")

# ── PC1 vs PC2 colored by class ───────────────────────────────────────────────
cls = meta_s["pos_class"].values
CLASS_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}
CLASS_NAMES  = {0: "contact",  1: "race",    2: "bearoff"}
fig, ax = plt.subplots(figsize=(10, 8))
for c in [0, 1, 2]:
    mask = cls == c
    ax.scatter(coords[mask, 0], coords[mask, 1],
               c=CLASS_COLORS[c], label=f"{CLASS_NAMES[c]} ({mask.sum():,})",
               s=1, alpha=0.3, rasterized=True)
ax.set_xlabel(f"PC1 ({100*pca.explained_variance_ratio_[0]:.1f}%)")
ax.set_ylabel(f"PC2 ({100*pca.explained_variance_ratio_[1]:.1f}%)")
ax.set_title(f"PCA — PC1 vs PC2  [N={SAMPLE:,}]")
ax.legend(markerscale=6)
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "pca_pc1_pc2.png"), dpi=120)
plt.close()
print("saved pca_pc1_pc2.png")

# ── Loadings: top features per component ────────────────────────────────────
print("\n── Loadings: top-5 features per component ──")
for k in range(5):
    top = np.argsort(np.abs(pca.components_[k]))[::-1][:5]
    names_vals = [(FEATURE_NAMES[i], pca.components_[k][i]) for i in top]
    parts = ", ".join(f"{n}={v:+.3f}" for n, v in names_vals)
    print(f"  PC{k+1} ({100*pca.explained_variance_ratio_[k]:.1f}%): {parts}")

print("\n02_pca.py done.")
