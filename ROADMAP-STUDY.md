# Backgammon Mining Study — Roadmap

## Current Status — 2026-04-07

| Phase | Status | Fiches | Notes |
|-------|--------|--------|-------|
| S0 Data Infrastructure  | ✅ Complete | S0.1-S0.7 | All 7 fiches done — JSONL→Parquet→DuckDB→Features→Validation→Hashing→Graph |
| S1 Exploration           | 🔄 In Progress | S1.1-S1.8 | S1.1 ✅ S1.2 ✅ (correlation_analysis.py); S1.3-S1.8 planned |
| S2 Player Profiling      | ⬜ Planned | S2.1-S2.4 | Metrics, clustering, ranking, strengths/weaknesses |
| S3 Practical Rules       | ⬜ Planned | S3.1-S3.6 | Cube heatmaps, MET, thresholds, heuristics, gammon, model |
| S4 Web Dashboard         | ⬜ Planned | S4.1-S4.7 | Views, architecture, board component, API, frontend, trajectories |

## Overview

32 fiches across 5 phases. A parallel research track that mines 24 GB of
XG files (166K matches, ~160M positions) using a Python/Polars/DuckDB
pipeline **independent from the GBF format** (M0-M10).

**Source**: `plan_backgammon_mining.md` (original plan in French)

**Priorities**: (1) Pattern discovery / exploratory research, (2) Player
profiling, (3) Practical rules for play.

**Relationship to GBF**: The study shares the `xgparser` library with the
GBF pipeline but uses its own data path (Go JSONL export → Parquet → DuckDB).
Findings from S1-S3 will inform future GBF schema revisions.

## Dependency Graph

```
S0 Data Infrastructure
  S0.1 JSONL Export
    └→ S0.2 Parquet Conversion
        ├→ S0.3 DuckDB Access Layer
        ├→ S0.4 Feature Engineering
        │   ├→ S0.5 Data Quality Validation
        │   │
        │   ├→ S1 Exploration
        │   │   ├→ S1.1 Descriptive Statistics
        │   │   ├→ S1.2 Feature-Error Correlation
        │   │   ├→ S1.3 Position Clustering
        │   │   │   ├→ S1.4 Anomaly Detection
        │   │   │   ├→ S3.4 Position Heuristics
        │   │   │   └→ S1.8 Graph Topology (+ needs S0.7)
        │   │   ├→ S1.5 Volatility Analysis
        │   │   ├→ S1.6 Dice Analysis
        │   │   └→ S1.7 Temporal Analysis
        │   │
        │   ├→ S2 Player Profiling
        │   │   ├→ S2.1 Player Metrics
        │   │   │   ├→ S2.2 Player Clustering
        │   │   │   ├→ S2.3 Benchmarking
        │   │   │   └→ S2.4 Strengths/Weaknesses
        │   │
        │   └→ S3 Practical Rules
        │       ├→ S3.1 Cube Error Heatmap
        │       ├→ S3.2 MET Verification
        │       ├→ S3.3 Cube Equity Thresholds
        │       ├→ S3.5 Gammon Impact
        │       └→ S3.6 Predictive Model (+ needs S1.2)
        │
        ├→ S0.6 Position Hashing
        │   └→ S0.7 Trajectory Graph
        │       └→ S1.8 Graph Topology
        │           └→ S4.7 Position Map Component
        │
        └→ S4 Web Dashboard
            ├→ S4.1 View Definitions
            │   └→ S4.2 Architecture
            ├→ S4.3 Board Component (parallelizable)
            ├→ S4.4 Data API
            ├→ S4.7 Position Map & Trajectories
            └→ S4.5 Frontend → S4.6 Deployment
```

## Effort Estimates

| Phase | Fiches | Complexity | Est. days (with Claude Code) |
|-------|--------|-----------|------------------------------|
| S0    | 7      | Medium-High | 8-12 |
| S1    | 8      | High        | 12-18 |
| S2    | 4      | Medium      | 5-8 |
| S3    | 6      | High        | 8-12 |
| S4    | 7      | Very High   | 18-25 |
| **Total** | **32** | | **51-75** |

## Execution Recommendations

1. **Start with S0** — nothing is possible without exploitable data
2. **S1, S2, S3 are largely parallelizable** once S0 is complete
3. **S4 must wait for results** — dashboard views depend on S1-S3 findings
4. **Iterate**: each fiche may reveal unexpected leads
5. **Start small**: prototype on 1% sample (~1.6M positions) before scaling
6. **Versioning**: dedicated repo for pipeline/analysis, separate from GBF

---

## S0 — Data Infrastructure

**Task sheet**: [docs/tasks/S0-infrastructure.md](docs/tasks/S0-infrastructure.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S0.1 | JSONL export from xgparser (matches/games/positions) | — | Medium |
| S0.2 | JSONL → partitioned Parquet (pyarrow/polars) | S0.1 | Low |
| S0.3 | DuckDB access layer (`bgdata.py`) | S0.2 | Low-Med |
| S0.4 | Feature engineering (~30 derived features) | S0.2 | Med-High |
| S0.5 | Data quality validation | S0.2, S0.4 | Low |
| S0.6 | Position hashing + convergence index (xxhash64) | S0.2 | Med-High |
| S0.7 | Trajectory graph (positions as nodes, moves as edges) | S0.6 | High |

**S0.1** — Add JSONL export to xgparser: deterministic match_id, board as
26-int array, batch export per .xg file, cube decisions as separate type.

**S0.2** — Parquet conversion: partitioned positions (~100-500 MB each),
strict typing (int8 board, float32 probs), snappy compression.

**S0.3** — BGDatabase class: query/get_match/get_positions/get_player_stats,
LRU cache, pre-defined aggregations. DuckDB reads Parquet directly.

**S0.4** — Position structure features (pip, blots, prime, anchors, timing),
match context (phase, cube leverage, gammon, volatility, take point), away
score (leader, Crawford, DGR). Vectorized with Polars + Kazaross-XG2 MET.

**S0.5** — Referential integrity, probability sanity (win+lose ≈ 1), board
validity (15 checkers), temporal coherence, duplicates, volume stats.

**S0.6** — Canonical hash (on-roll perspective, xxhash64), convergence index
(occurrence count, distinct matches/games), top 1000 crossroads.

**S0.7** — edges.parquet (from/to hash, dice, move, error), node metrics
(degree, match count, avg error, move entropy), threshold filtering (≥ 3
matches), Parquet + DuckDB queries.

---

## S1 — Exploration & Pattern Discovery

**Task sheets**: [S1-exploration-a.md](docs/tasks/S1-exploration-a.md) (S1.1-S1.4),
[S1-exploration-b.md](docs/tasks/S1-exploration-b.md) (S1.5-S1.8)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S1.1 ✅ | Global descriptive statistics | S0.4, S0.5 | Low |
| S1.2 ✅ | Feature-error correlation analysis | S0.4 | Medium |
| S1.3 | Position clustering (PCA/UMAP/HDBSCAN) | S0.4 | High |
| S1.4 | Anomaly detection & trap positions | S1.3 | Medium |
| S1.5 | Position volatility analysis | S0.4 | Medium |
| S1.6 | Dice structure analysis | S0.4 | Low-Med |
| S1.7 | Temporal & sequential analysis (fatigue, tilt) | S0.3 | Medium |
| S1.8 | Convergence & graph topology | S0.7, S1.3 | High |

**S1.1** — Error/equity/phase distributions, away score frequency, match/game
lengths, top tournaments/players, temporal trends, cube value distribution.

**S1.2** — Spearman + mutual info + Random Forest importance, checker vs cube
split, stratification by phase / away score bracket / cube owner. 8 CSV outputs.

**S1.3** — PCA→UMAP→HDBSCAN on 1M sample, then extend. Expected: race, blitz,
priming, back game, holding, bearoff+contact, scramble. Separate checker/cube.

**S1.4** — Blunders > 0.100, recurring patterns within clusters, error type
classification, Isolation Forest / LOF for structural outliers. Top 50 patterns.

**S1.5** — Volatility = std dev of candidate equities, best/2nd-best gap,
correlation with phase/pip/blots/score, high-volatility → more errors?

**S1.6** — Error per dice combo (21 unordered), dice×phase interaction,
dice×structure interaction, candidate count per combination.

**S1.7** — Error by game# (fatigue?), by move# (early/late), post-blunder tilt,
post-loss effect, score deficit effect, error autocorrelation.

**S1.8** — Crossroads (most-traversed, continuation diversity, familiarity vs
error), divergence/convergence, degree distribution, betweenness centrality,
Louvain communities, frequent 3-5 move paths, highways vs trails.

---

## S2 — Player Profiling

**Task sheet**: [docs/tasks/S2-player-profiling.md](docs/tasks/S2-player-profiling.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S2.1 | Player profiling metrics (~20 metrics) | S0.4 | Medium |
| S2.2 | Player clustering by profile (archetypes) | S2.1 | Medium |
| S2.3 | Benchmarking & player ranking | S2.1 | Medium |
| S2.4 | Individual strengths/weaknesses analysis | S2.1, S1.3 | Medium |

**S2.1** — Global performance (avg error, PR rating), phase profile
(contact/race/bearoff), cube profile (missed doubles, wrong takes/passes),
tactical (aggression, risk), consistency (std dev, streaks). Filter: ≥ 20 matches.

**S2.2** — Z-score normalization, PCA, k-means/HDBSCAN, radar charts.
Archetypes: technician, cubist, sprinter, warrior, steady, erratic.

**S2.3** — PR ranking with confidence intervals, per-dimension ranking,
radar comparisons, temporal evolution, PR vs results, over/under-performers.

**S2.4** — Error per position cluster vs population average, z-score per
cluster → strengths/weaknesses. Same for away score zones. Auto-report template.

---

## S3 — Practical Rules for Play

**Task sheet**: [docs/tasks/S3-practical-rules.md](docs/tasks/S3-practical-rules.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S3.1 | Cube error x away score heatmap | S0.4 | Low |
| S3.2 | Empirical MET verification | S0.4 | Medium |
| S3.3 | Cube equity thresholds by score | S0.4 | Med-High |
| S3.4 | Heuristics by position type | S1.3, S1.4 | High |
| S3.5 | Gammon impact analysis | S0.4 | Medium |
| S3.6 | Lightweight predictive model | S0.4, S1.2 | High |

**S3.1** — Filter cube decisions, aggregate error by (away_p1, away_p2),
separate by error type, per match length heatmaps, identify hot spots.

**S3.2** — Average equity of neutral positions as proxy for match equity,
compare with Kazaross/Woolsey MET, analyze deviations, player level effect.

**S3.3** — Equity thresholds for double/take/pass per score pair, compare
with Janowski, gammon rate interaction. Printable reference tables.

**S3.4** — Shallow decision tree (depth 3-4) per cluster → interpretable
rules ("if home board > 4 AND blots > 2 → blitz"), validate on holdout.

**S3.5** — Gammon value by score, cube threshold modification, gammon-prone
positions, dead gammon verification, free drop quantification.

**S3.6** — Cube decision model (XGBoost/LightGBM), SHAP interpretability,
compare vs S3.3 heuristics. Mental tool, not XG replacement.

---

## S4 — Interactive Dashboard & Web Application

**Task sheet**: [docs/tasks/S4-dashboard.md](docs/tasks/S4-dashboard.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S4.1 | User view definitions (7 views) | S1-S3 results | Medium |
| S4.2 | Web application architecture | S4.1 | Medium |
| S4.3 | Board visualization component | — | Medium |
| S4.4 | Data API endpoints | S0.3, S4.2 | Medium |
| S4.5 | Frontend implementation | S4.1, S4.3, S4.4 | High |
| S4.6 | Testing & deployment | S4.5 | Medium |
| S4.7 | Position map & trajectory explorer | S0.6-7, S1.3, S1.8, S4.3 | Very High |

**S4.1** — 7 views: database explorer, error map (cube heatmap), player
profile (radar + comparison), position catalogue, cube helper, global stats,
trajectory explorer (UMAP map).

**S4.2** — Go/Python (FastAPI) backend, DuckDB embedded, React + D3/Recharts,
SVG/Canvas board, Docker, pre-computed materialized aggregations.

**S4.3** — 24-point + bar board, stacked checkers (counter > 5), cube,
away scores, dice, move arrows, responsive. Parallelizable.

**S4.4** — REST endpoints: players, tournaments, heatmaps, positions,
cube thresholds, stats/rankings, clusters, map/density/trajectories.

**S4.5** — 8 pages: home, explorer, heatmap, player profile, position
catalogue, cube helper, rankings, trajectory map.

**S4.6** — Performance testing on 160M positions, optimization, functional
tests, Dockerization, deployment, minimal docs.

**S4.7** — Multi-scale: tiles (zoom 0-3), hexbins (4-7), points (8+, max
5K visible). deck.gl WebGL. Click → trajectory polylines, board panel on
hover. UMAP on 1-5M sample + transform, tiling pyramid, spatial index.
