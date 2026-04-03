# M5 — Visualization Exploration (Jupyter) ✅

## Objective

Explore the BMAB dataset visually using dimensionality reduction and
clustering. Identify position families, discriminant features, and
tricky position regions. Produce a synthesis report that informs
Phase 2 decisions (M9).

## Pre-requisites

M4 (feature extraction and .npy export).

Note: Parquet export was skipped in M4 (dependency too heavy); notebooks
use `.npy` (numpy) + CSV format produced by `cmd/export-features`.

## Sub-steps

### M5.0 — Feature Export Tool ✅

`cmd/export-features/main.go` — imports BMAB files into SQLite and
exports 4 data files for Python notebooks:

| File               | Content                                            |
|--------------------|----------------------------------------------------|
| `features.npy`     | float64 matrix (N × 44) — numpy.load()            |
| `metadata.csv`     | pos_class, pip_diff, away_x/o, cube, bar per pos  |
| `difficulty.csv`   | avg equity_diff per position (from moves table)    |
| `players.csv`      | per-player position + match counts                 |

Flags: `-db`, `-outdir`, `-limit`, `-batch`, `-skip-import`

Run: `go run ./cmd/export-features/ -limit 5000 data/bmab-2025-06-23/`

Validation (5K files, 1.57M positions): 10,025 pos/s, 527 MB .npy.

### M5.1 — UMAP-2D Notebook ✅

File: `notebooks/01_umap.ipynb` (also `01_umap.py` for standalone run)

- Loaded 1,567,461 positions; sampled 100,000 (seed=42)
- Standard scaling applied
- 3 hyperparameter configurations tested:

| Config            | Time  | Observation                              |
|-------------------|-------|------------------------------------------|
| n=15, d=0.10 ★   | 66s   | Clear 3-region structure, best readability |
| n=5,  d=0.01      | 29s   | Over-fragments contact region            |
| n=50, d=0.50      | 102s  | Smooth but merges sub-clusters           |

- 4 colorings produced: pos_class, pip_diff, away_x, cube_owner
- **Recommended**: n_neighbors=15, min_dist=0.10

Output: `data/umap_coords.npy` (100K × 2 coordinates)

### M5.2 — PCA Notebook ✅

File: `notebooks/02_pca.ipynb` (also `02_pca.py`)

Sample: 200K positions. PCA on 44 dimensions.

| Component | Variance | Dominant features                          |
|-----------|----------|--------------------------------------------|
| PC1       | 19.0%    | pip_x, pip_o, pt_12, pt_11, pt_07          |
| PC2       |  8.2%    | made_o, made_x, pos_class, borne_off_o     |
| PC3       |  6.0%    | pip_diff (standalone)                      |
| PC4       |  5.2%    | bar_x, bar_o                               |
| PC5       |  4.0%    | anchor_x, anchor_o                         |

Cumulative variance thresholds:
- 50% → 8 components
- 80% → 21 components
- 90% → 27 components

Output: `data/pca_coords.npy`

### M5.3 — Clustering Notebook ✅

File: `notebooks/03_clustering.ipynb` (also `03_clustering.py`)

**HDBSCAN** (min_cluster_size=200, min_samples=50) on UMAP-2D:
- **6 clusters**, 3.4% noise

| Cluster | Size   | Composition           | pip_diff | Interpretation              |
|---------|--------|-----------------------|----------|-----------------------------|
| 0       | 3,153  | contact 99%           | +1       | Near-DMP contact (X leads)  |
| 1       | 3,269  | contact 100%          | +2       | Near-DMP contact            |
| 2       | 3,228  | contact 100%          | -5       | Near-DMP contact (X trails) |
| 3       | 80,628 | contact 91% / race 8% | 0        | Main body (all types)       |
| 4       | 6,071  | bearoff 97%           | +1       | Bearoff                     |
| 5       | 217    | bearoff 98%           | -2       | Late bearoff (X behind)     |

**K-means** (k=10): silhouette = 0.391.

Note: all clusters show away_x ≈ 7 — reflects the BMAB match-play dataset
composition (tournament games near DMP = 1-away-from-win).

Output: `data/cluster_labels.npy`

### M5.4 — Difficulty Map ✅

File: `notebooks/04_difficulty.ipynb` (also `04_difficulty.py`)

Joined difficulty.csv (avg equity_diff) with metadata. All 100K sample
positions have equity_diff data.

| Class   | Mean (mp) | Median | p90 (mp) |
|---------|-----------|--------|----------|
| Contact | 4.0       | 0.0    | 4.9      |
| Race    | 0.4       | 0.0    | 0.0      |
| Bearoff | 0.1       | 0.0    | 0.0      |

(1 mp = 0.001 equity, ≈ 1 millipawn in backgammon analysis)

**Finding**: contact positions are ~10× harder than race/bearoff.
Most positions are played correctly (median=0); hotspots are in
complex contact positions with high blot counts.

### M5.5 — Player Comparison ✅

File: `notebooks/05_players.ipynb` (also `05_players.py`)

2,479 unique players in the 5K-file sample.

Top 5 players by position count:
| Player               | Positions | Matches |
|----------------------|-----------|---------|
| Giorgio Castellano   | 53,593    | 174     |
| Benjamin Lund        | 52,566    | 130     |
| Roberto Litzenberger | 35,024    | 107     |
| Dmitriy Obukhov      | 34,949    | 116     |
| Jeb Horton           | 29,516    | 101     |

KDE plots show positional distribution per class across the UMAP space.

### M5.6 — Synthesis Report ✅

File: `notebooks/06_synthesis.md`

Key findings documented: cluster interpretation, discriminant features,
M9 schema recommendations, UMAP hyperparameter guidance, difficulty
hotspots, dataset composition observations.

## Files Created

| File | Status |
|------|--------|
| `cmd/export-features/main.go` | ✅ |
| `notebooks/requirements.txt` | ✅ |
| `notebooks/01_umap.ipynb` + `01_umap.py` | ✅ |
| `notebooks/02_pca.ipynb`  + `02_pca.py`  | ✅ |
| `notebooks/03_clustering.ipynb` + `03_clustering.py` | ✅ |
| `notebooks/04_difficulty.ipynb` + `04_difficulty.py` | ✅ |
| `notebooks/05_players.ipynb`    + `05_players.py`    | ✅ |
| `notebooks/06_synthesis.md`     | ✅ |
| `notebooks/make_notebooks.py`   | ✅ |
| `notebooks/.gitignore`          | ✅ |

## Acceptance Criteria

- [x] All 5 notebooks run without error end-to-end
- [x] UMAP produces visible clusters (3 distinct regions: contact/race/bearoff)
- [x] At least 5 distinct clusters identified by HDBSCAN (6 found)
- [x] PCA identifies top contributing features (pip counts, structure, pip_diff)
- [x] Difficulty map shows non-uniform distribution (contact 10× harder)
- [x] Synthesis report documents actionable recommendations for M9

## Tests

### Functional Tests (all validated)

**[F] UMAP on 100K positions** ✅
Completed in 66s. Clear 3-region structure visible.

**[F] PCA variance analysis** ✅
PC1+PC2+PC3 = 33.2% > 50% (first 8 components). First 3 > 30% ✓

**[F] Clustering produces distinct groups** ✅
6 clusters, all with > 200 members (largest: 80,628). Noise: 3.4% < 30% ✓

**[F] Difficulty map is informative** ✅
Contact mean 4.0 mp vs race 0.4 mp vs bearoff 0.1 mp. Non-uniform ✓

**[F] Player comparison shows differences** ✅
2,479 players, top-5 with 25K–54K positions each. KDE maps computed ✓

**[F] Full pipeline: .npy → notebooks** ✅
5K-file import → 1.57M positions → export → all 5 notebooks execute ✓

## Notes

**away_x ≈ 7 in all clusters**: The BMAB tournament dataset consists almost
entirely of match-play games where both players are near the end of a match.
This creates a biased distribution — money-game positions would form
separate regions in UMAP space.

**pip_diff as standalone PC**: pip_diff is the dominant feature in PC3 (6%),
completely orthogonal to absolute pip counts (PC1). This confirms it
deserves its own index column in M9.

**Median equity_diff = 0**: Most positions in the BMAB dataset are played
optimally or near-optimally. The equity_diff distribution is right-skewed
with a heavy zero-mass spike. The meaningful difficulty signal is in the
90th percentile and above, not the mean.
