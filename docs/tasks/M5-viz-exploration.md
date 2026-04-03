# M5 — Visualization Exploration (Jupyter)

## Objective

Explore the BMAB dataset visually using dimensionality reduction and
clustering. Identify position families, discriminant features, and
tricky position regions. Produce a synthesis report that informs
Phase 2 decisions (M9).

## Pre-requisites

M4 (feature extraction and Parquet export).

## Sub-steps

### M5.1 — UMAP-2D Notebook

File: `notebooks/01_umap.ipynb`

- Load feature matrix from Parquet (~100K positions, sampled)
- Apply standard scaling
- Run UMAP with default parameters (n_neighbors=15, min_dist=0.1)
- Plot 2D scatter, colored by position_class (contact/race/bearoff)
- Try alternative colorings: pip_diff, away_x, cube_owner
- Vary n_neighbors (5, 15, 50) and min_dist (0.01, 0.1, 0.5)
- Document which hyperparameters produce the most readable projections

### M5.2 — PCA Notebook

File: `notebooks/02_pca.ipynb`

- Run PCA on the same feature matrix
- Plot cumulative variance explained vs number of components
- Identify the "elbow" — how many components capture 90% variance?
- Plot PC1 vs PC2, colored by position_class
- Analyze loadings: which features contribute most to each component?
- Compare with UMAP: do the same clusters appear?

### M5.3 — Clustering Notebook

File: `notebooks/03_clustering.ipynb`

- Run HDBSCAN on UMAP-2D coordinates (min_cluster_size=50)
- How many clusters are found?
- Characterize each cluster:
  - Mean feature values (pip, blots, primes, contact/race)
  - Representative positions (closest to centroid)
  - Cluster labels: can we name them? (e.g., "pure race", "back game",
    "mutual holding game", "blitz", "prime vs prime")
- Run k-means (k=5, 10, 20) for comparison
- Silhouette score and cluster stability analysis

### M5.4 — Difficulty Map

File: `notebooks/04_difficulty.ipynb`

- Color UMAP projection by average equity_diff (from moves table)
- Requires joining positions with moves to get equity_diff
- Aggregate: for each position, average equity_diff across all games
- Heatmap view: which regions of position space are hardest?
- Identify the "most tricky" clusters (highest average error)
- Cross-reference with position_class: are contact positions harder?

### M5.5 — Player Comparison

File: `notebooks/05_players.ipynb`

- Select 2-3 players with significant game counts
- Plot their positions on the UMAP projection (different colors)
- Compare distributions: do some players play more back games? More races?
- Kernel density estimation on UMAP coordinates per player
- Difference map: where does player A play that player B doesn't?

### M5.6 — Synthesis Report

File: `notebooks/06_synthesis.md` or final cells of each notebook

Conclusions to document:
- Number and nature of position clusters found
- Most discriminant features (from PCA loadings and cluster analysis)
- Recommended query dimensions for the database schema
- Recommended derived columns for M9 (e.g., position_class as SQL column)
- UMAP hyperparameters that work best
- Difficulty hotspots in position space
- Any surprising findings

## Files to Create

| File | Action |
|------|--------|
| `notebooks/01_umap.ipynb` | Create |
| `notebooks/02_pca.ipynb` | Create |
| `notebooks/03_clustering.ipynb` | Create |
| `notebooks/04_difficulty.ipynb` | Create |
| `notebooks/05_players.ipynb` | Create |
| `notebooks/requirements.txt` | Create (umap-learn, scikit-learn, pandas, plotly, matplotlib, hdbscan) |

## Acceptance Criteria

- [ ] All 5 notebooks run without error end-to-end
- [ ] UMAP produces visible clusters (not a uniform blob)
- [ ] At least 5 distinct clusters identified by HDBSCAN
- [ ] PCA analysis identifies the top contributing features
- [ ] Difficulty map shows non-uniform distribution of equity_diff
- [ ] Synthesis report documents actionable recommendations for M9

## Tests

### Functional Tests

**[F] UMAP on 10K positions**
Run notebook 01 on a 10K sample. Measure execution time.
Success: completes in < 60s, produces a PNG with visible structure.

**[F] PCA variance analysis**
Run notebook 02. Check cumulative variance plot.
Success: first 3 components explain > 50% of variance,
first 10 explain > 80%.

**[F] Clustering produces distinct groups**
Run notebook 03 with HDBSCAN.
Success: at least 5 clusters with > 100 members each,
noise fraction < 30%.

**[F] Difficulty map is informative**
Run notebook 04. Check that equity_diff coloring shows variation.
Success: visual gradient or hot spots visible, not uniform color.

**[F] Player comparison shows differences**
Run notebook 05 with 2 players who have > 1000 positions each.
Success: density maps show distinguishable patterns.

**[F] Full pipeline: Parquet → notebooks**
Export 100K positions to Parquet (M4), run all 5 notebooks.
Success: all notebooks execute without error, all outputs saved.
