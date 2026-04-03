"""M5.4 — Difficulty map: equity_diff projected onto UMAP.

Joins difficulty.csv (avg equity_diff per position) with the UMAP embedding.
equity_diff is stored as int × 10000 in the DB; the CSV exports the raw
average which is also × 10000. Converts to centipawns (equity × 1000 → PPR).

Shows which regions of position-space have the highest average error.

Outputs: img/difficulty_umap.png, img/difficulty_heatmap.png
"""

import os, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

print("Loading difficulty.csv ...")
diff = pd.read_csv(os.path.join(DATA_DIR, "difficulty.csv"))

# Join difficulty onto the sample.
meta_s = meta_s.merge(diff, on="position_id", how="left")
has_diff = meta_s["avg_equity_diff"].notna()
print(f"  positions with equity_diff: {has_diff.sum():,} / {SAMPLE:,}")

# Convert from x10000 units to millipoints (× 10 for readability).
meta_s["equity_loss_mp"] = meta_s["avg_equity_diff"].fillna(0) / 10000 * 1000

# ── Stats by position class ───────────────────────────────────────────────────
CLASS_NAMES = {0: "contact", 1: "race", 2: "bearoff"}
print("\n── Average equity loss (millipawns) by class ──")
for c in [0, 1, 2]:
    mask = (meta_s["pos_class"] == c) & has_diff
    vals = meta_s.loc[mask, "equity_loss_mp"]
    if len(vals) == 0:
        print(f"  {CLASS_NAMES[c]:8s}: no data")
        continue
    print(f"  {CLASS_NAMES[c]:8s}: mean={vals.mean():.1f}  "
          f"median={vals.median():.1f}  p90={vals.quantile(0.9):.1f}  n={len(vals):,}")

# ── Scatter: UMAP colored by equity loss ─────────────────────────────────────
x = embedding[:, 0]
y = embedding[:, 1]
loss = meta_s["equity_loss_mp"].values

# Clamp to 95th percentile for visual range.
vmax = np.percentile(loss[has_diff.values], 95)
loss_clipped = np.clip(loss, 0, vmax)

fig, ax = plt.subplots(figsize=(10, 8))
sc = ax.scatter(x, y, c=loss_clipped, cmap="hot_r",
                s=1, alpha=0.4, rasterized=True)
plt.colorbar(sc, ax=ax, label="avg equity loss (millipawns, clipped at p95)")
ax.set_title(f"UMAP — difficulty map (avg equity loss)  [N={SAMPLE:,}]")
ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "difficulty_umap.png"), dpi=120)
plt.close()
print("\nsaved difficulty_umap.png")

# ── Hexbin heatmap ───────────────────────────────────────────────────────────
has_mask = has_diff.values
fig, axes = plt.subplots(1, 2, figsize=(18, 7))
for ax, c, name in zip(axes, [0, 1], ["contact", "race"]):
    mask = (meta_s["pos_class"].values == c) & has_mask
    if mask.sum() < 100:
        continue
    hb = ax.hexbin(x[mask], y[mask], C=loss[mask],
                   gridsize=60, reduce_C_function=np.mean, cmap="hot_r")
    plt.colorbar(hb, ax=ax, label="mean equity loss (millipawns)")
    ax.set_title(f"Difficulty heatmap — {name} positions")
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
plt.tight_layout()
plt.savefig(os.path.join(IMG_DIR, "difficulty_heatmap.png"), dpi=120)
plt.close()
print("saved difficulty_heatmap.png")

print("\n04_difficulty.py done.")
