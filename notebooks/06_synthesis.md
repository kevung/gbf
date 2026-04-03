# M5 — Synthesis Report

**Dataset**: 5,000 BMAB files → 1,567,461 unique positions (1.57M)
**Sample used for analysis**: 100,000 positions (seed=42)
**Date**: 2026-04-03

---

## Class Distribution

| Class    | Count   | %     |
|----------|---------|-------|
| Contact  | 85,897  | 85.9% |
| Race     | 7,435   |  7.4% |
| Bearoff  | 6,668   |  6.7% |

Contact positions dominate the dataset. Bearoff and race are distinct
minority classes, well-separated in UMAP space.

---

## PCA Findings

| Component | Variance | Top features                                    |
|-----------|----------|-------------------------------------------------|
| PC1       | 19.0%    | pip_x, pip_o, pt_12, pt_11, pt_07 — absolute pip counts |
| PC2       |  8.2%    | made_o, made_x, pos_class, borne_off_o, prime_x — structure/endgame |
| PC3       |  6.0%    | pip_diff — relative race lead                   |
| PC4       |  5.2%    | bar_x, bar_o — checker-on-bar                   |
| PC5       |  4.0%    | anchor_x, anchor_o — anchor ownership           |

Cumulative variance:
- 8 components → 50%
- 21 components → 80%
- 27 components → 90%

**Key insight**: pip counts and point structure explain the first two
principal axes. pip_diff alone is PC3, confirming it as an independently
discriminant dimension.

---

## UMAP Findings

Best hyperparameters: **n_neighbors=15, min_dist=0.10** (default).
- Produces clear separation of contact / race / bearoff.
- n_neighbors=5 (min_dist=0.01): over-fragments contact region.
- n_neighbors=50 (min_dist=0.50): smoother but merges sub-clusters.

UMAP-2D execution time (100K positions): **66 seconds**.

---

## Clustering Findings (HDBSCAN, min_cluster_size=200)

6 clusters identified, 3.4% noise:

| Cluster | Size   | Composition        | pip_diff | Description              |
|---------|--------|--------------------|----------|--------------------------|
| 0       | 3,153  | contact 99%        | +1       | Near-DMP contact games   |
| 1       | 3,269  | contact 100%       | +2       | Near-DMP contact games   |
| 2       | 3,228  | contact 100%       | -5       | Near-DMP, X behind       |
| 3       | 80,628 | contact 91% / race 8% | 0   | Main body (mixed contact/race) |
| 4       | 6,071  | bearoff 97%        | +1       | Bearoff positions         |
| 5       | 217    | bearoff 98%        | -2       | Late bearoff, X behind   |

All clusters have away_x ≈ 7 — this reflects the BMAB dataset composition
(match play, not money games).

K-means (k=10) silhouette score: **0.391** (moderate separation).

---

## Difficulty Findings

Average equity loss by class (millipawns = equity × 1000):

| Class   | Mean | Median | p90 |
|---------|------|--------|-----|
| Contact | 4.0  | 0.0    | 4.9 |
| Race    | 0.4  | 0.0    | 0.0 |
| Bearoff | 0.1  | 0.0    | 0.0 |

**Contact positions are ~10× harder than race/bearoff.** The near-zero
median across all classes indicates that most positions are played correctly
(or near-correctly), while a small fraction of contact positions have high
equity loss. The difficulty map shows hotspots concentrated in the sub-clusters
with high blot counts and mutual holding positions.

---

## Player Stats

- 2,479 unique players in the 5K-file sample.
- Top player: Giorgio Castellano — 53,593 positions, 174 matches.
- Top 5 players: each appear in 25K–54K positions.

---

## Recommendations for M9

### SQL columns to add
1. `pos_class INTEGER` — store ClassifyPosition result directly (avoid
   recomputing from base_record in queries).
2. `pip_diff INTEGER` — indexed for range queries on race advantage.
3. `prime_len_x INTEGER`, `prime_len_o INTEGER` — discriminant for
   prime-vs-prime and backgame detection.

### Index recommendations
- `idx_positions_class` on `pos_class` — filter by game type.
- `idx_positions_pip_diff` on `pip_diff` — range queries (race analyzer).
- Composite `(pos_class, away_x, away_o)` — match-score + game-type queries.

### Query dimensions (M6)
- `QueryByClass(cls int)` — filter by contact/race/bearoff.
- `QueryByPipDiff(lo, hi int)` — race advantage range.
- Aggregate: `AvgEquityLossPerClass()` — difficulty distribution.

### UMAP hyperparameters
- Production: n_neighbors=15, min_dist=0.10 (best separation + readability).
- For sub-cluster analysis: n_neighbors=5, min_dist=0.01 (finer granularity).

### Surprising findings
- The dataset is 86% contact positions — bearoff/race are underrepresented
  for ML training on those game phases.
- All HDBSCAN clusters had away_x ≈ 7 (DMP-vicinity), reflecting the BMAB
  tournament match-play dataset composition. Money-game positions would
  form separate clusters.
- pip_diff is a standalone principal component (PC3, 6%) — justifies it
  as a first-class index column, not just a derived feature.
