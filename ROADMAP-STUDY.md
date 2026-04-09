# Backgammon Mining Study — Roadmap

## Current Status — 2026-04-09

| Phase | Status | Fiches | Notes |
|-------|--------|--------|-------|
| S0 Data Infrastructure  | ✅ Complete | S0.1-S0.7 | All 7 fiches done — JSONL→Parquet→DuckDB→Features→Validation→Hashing→Graph |
| S1 Exploration           | ✅ Complete | S1.1-S1.8 | All 8 fiches done — Stats→Correlation→Clustering→Anomaly→Volatility→Dice→Temporal→GraphTopology |
| S2 Player Profiling      | ✅ Complete | S2.1-S2.4 | All 4 fiches done — Metrics→Clustering→Ranking→Strengths/Weaknesses |
| S3 Practical Rules       | 🔄 In progress | S3.1-S3.6 | S3.1-S3.5 ✅, S3.6 planned |
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
| S1.3 ✅ | Position clustering (PCA/UMAP/HDBSCAN) | S0.4 | High |
| S1.4 ✅ | Anomaly detection & trap positions | S1.3 | Medium |
| S1.5 ✅ | Position volatility analysis | S0.4 | Medium |
| S1.6 ✅ | Dice structure analysis | S0.4 | Low-Med |
| S1.7 ✅ | Temporal & sequential analysis (fatigue, tilt) | S0.3 | Medium |
| S1.8 ✅ | Convergence & graph topology | S0.7, S1.3 | High |

**S1.1** — Error/equity/phase distributions, away score frequency, match/game
lengths, top tournaments/players, temporal trends, cube value distribution.

**S1.2** — Spearman + mutual info + Random Forest importance, checker vs cube
split, stratification by phase / away score bracket / cube owner. 8 CSV outputs.

**S1.3** — StandardScaler → PCA (20 comp) → UMAP (2D) → HDBSCAN. Checker and
cube clustered separately. Outputs: labels Parquet, profile CSVs, PCA variance.

**S1.4** — Blunder catalogue (error > 0.100) by cluster, error bucket distribution,
Isolation Forest structural outliers. Per-cluster blunder rate + anomaly score.

**S1.5** — Complexity proxy via move_played_error (candidates dropped in S0.2).
Breakdown by phase, pip bin, gammon threat, cube leverage. High-error profile.

**S1.6** — Mean error per 21 dice combos, doubles vs non-doubles, dice×phase
and dice×gammon-threat interactions. Error by total pips moved.

**S1.7** ✅ — Error by game# (fatigue?), by move# (early/late), post-blunder tilt,
post-loss effect, score deficit effect, error autocorrelation.
Implementation: `scripts/analyze_temporal.py`.

**S1.8** ✅ — Crossroads (most-traversed, continuation diversity, familiarity vs
error), divergence/convergence, degree distribution, betweenness centrality,
Louvain communities, frequent 3-5 move paths, highways vs trails.
Implementation: `scripts/analyze_graph_topology.py`.

---

## S2 — Player Profiling

**Task sheet**: [docs/tasks/S2-player-profiling.md](docs/tasks/S2-player-profiling.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S2.1 ✅ | Player profiling metrics (~22 metrics) | S0.4 | Medium |
| S2.2 ✅ | Player clustering by profile (archetypes) | S2.1 | Medium |
| S2.3 ✅ | Benchmarking & player ranking | S2.1 | Medium |
| S2.4 ✅ | Individual strengths/weaknesses analysis | S2.1, S1.3 | Medium |

**S2.1** ✅ — Global performance (avg error, PR rating), phase profile
(contact/race/bearoff/opening/midgame/endgame), cube profile (missed doubles,
wrong takes/passes, error by score bracket), tactical (aggression_index,
risk_appetite), consistency (error_std, streak_tendency).
Implementation: `scripts/analyze_player_profiles.py`.
Outputs: `player_profiles.parquet`, `player_profiles.csv`,
`cube_error_by_score.csv`, `player_summary.txt`. Filter: ≥ 20 matches.

**S2.2** ✅ — Z-score normalization → PCA (up to 10 components) → K-means or
HDBSCAN on up to 14 profile metrics. Archetypes: Steady, Technician, Cubist,
Sprinter, Warrior, Erratic (data-driven naming from centroid characteristics).
Implementation: `scripts/cluster_players.py`.
Outputs: `player_clusters.parquet`, `cluster_profiles.csv`, `cluster_pca.csv`,
`archetype_descriptions.txt`.

**S2.3** ✅ — PR ranking with 95% CI (analytic normal approximation), 8
per-dimension rankings (contact, race, bearoff, cube, opening, consistency,
blunder avoidance), Pearson correlation PR vs win-rate, over/under-performers
(OLS residuals), temporal match-activity by year.
Implementation: `scripts/rank_players.py`.
Outputs: `player_ranking.parquet`, `player_ranking.csv`,
`dimension_rankings.csv`, `pr_vs_wins.csv`, `over_under_performers.csv`,
`temporal_pr.csv`, `ranking_report.txt`.

**S2.4** ✅ — Per-player z-score analysis vs population: (a) by position
cluster (S1.3 labels, joined via position_id), (b) by away-score zone
(DMP / GS / 4-5away / 6-9away / 10+away). z > +1 → weakness, z < -1 →
strength. Auto-generates one .txt report per player with phase profile,
cluster heatmap, and score-zone breakdown.
Implementation: `scripts/analyze_strengths_weaknesses.py`.
Outputs: `player_cluster_errors.parquet`, `player_zone_errors.parquet`,
`strengths_weaknesses.csv`, `reports/<player>.txt`.

---

## S3 — Practical Rules for Play

**Task sheet**: [docs/tasks/S3-practical-rules.md](docs/tasks/S3-practical-rules.md)

| Fiche | Objective | Needs | Complexity |
|-------|-----------|-------|------------|
| S3.1 ✅ | Cube error x away score heatmap | S0.4 | Low |
| S3.2 ✅ | Empirical MET verification | S0.4 | Medium |
| S3.3 ✅ | Cube equity thresholds by score | S0.4 | Med-High |
| S3.4 ✅ | Heuristics by position type | S1.3, S1.4 | High |
| S3.5 ✅ | Gammon impact analysis | S0.4 | Medium |
| S3.6 | Lightweight predictive model | S0.4, S1.2 | High |

**S3.1** ✅ — Cube decisions filtered from enriched, aggregated per
(away_p1, away_p2) cell (min 20 decisions). Error-type breakdown
(missed_double / wrong_take / wrong_pass rates). Per-match-length grids
(5/7/9/11/13-pt). Hot-spot detection (error > mean + 1σ). ASCII grid
report. Score asymmetry check (|error(p1,p2) − error(p2,p1)|).
Implementation: `scripts/analyze_cube_heatmap.py`.
Outputs: `cube_heatmap_global.csv`, `cube_heatmap_by_length.csv`,
`cube_hotspots.csv`, `cube_error_types.csv`, `cube_heatmap_report.txt`.

**S3.2** ✅ — Early-game checker positions (move ≤ 3) used as MET proxy.
Empirical win% = 50×(1+avg_equity) compared to Kazaross-XG2 MET (15×15).
Deviation analysis by score zone (DMP/GS/4-6away/7-10away/money).
On-roll bias quantification (tied-score cells → expected 50%). Full
Kazaross reference tables (MET, take points 2/4-cube live/last, gammon
values 1/2/4-cube) embedded and exported to CSV for S3.3/S3.5.
Implementation: `scripts/verify_met.py`.
Outputs: `met_comparison.csv`, `met_deviations.csv`, `met_report.txt`,
`kazaross_met.csv`, `kazaross_tp*.csv`, `kazaross_gv*.csv`.

**S3.3** ✅ — Double threshold estimated as midpoint(p90(equity|no_double),
p10(equity|double)); pass threshold as midpoint(p90(equity|take),
p10(equity|pass)). Compared with Kazaross-XG2 TP2-live table and Janowski
double threshold (MET-derived). Gammon interaction: pass threshold recomputed
by gammon_threat quartile (low/medium/high). Printable ASCII reference tables.
Implementation: `scripts/compute_cube_thresholds.py`.
Outputs: `cube_thresholds.csv`, `cube_thresholds_gammon.csv`,
`cube_thresholds_report.txt`.

**S3.4** ✅ — DecisionTreeClassifier (depth ≤ 4, class_weight=balanced,
80/20 holdout) trained per cluster (S1.3 labels, min 200 positions) and
per phase (contact/race/bearoff). Target: blunder (error > 0.080).
Rules extracted from danger leaves (precision ≥ 15%, support ≥ 50) and
translated to natural language ("IF your blots > 2 AND prime length ≤ 1
→ blunder risk 23%"). Global tree provides feature importance ranking.
Implementation: `scripts/extract_heuristics.py`.
Outputs: `heuristics.csv`, `tree_feature_importance.csv`,
`heuristics_report.txt`.

**S3.5** ✅ — Four analyses: (1) avg gammon_threat/risk per (away_p1, away_p2)
cell vs Kazaross-XG2 GV1/GV2/GV4 reference tables; (2) board features
predicting high gammon threat (DT importance: home_board_strength, prime
length, opponent blots); (3) DGR — empirically verify that DGR positions
have higher-than-average gammon_threat that is strategically wasted;
(4) free-drop — post-Crawford cube error rate + wrong_take (= missed
free pass) rate by score. Kazaross GV tables embedded from legacy/*.js.
Implementation: `scripts/analyze_gammon_impact.py`.
Outputs: `gammon_value_by_score.csv`, `gammon_features.csv`,
`dead_gammon_analysis.csv`, `free_drop_analysis.csv`, `gammon_report.txt`.

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
