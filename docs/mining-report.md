# BMAB Mining Study — Final Report

**Dataset**: BMAB 2025-06-23 — 166,713 XG files, 24 GB  
**Pipeline**: S0.1→S3.6 (28 scripts, batched export, DuckDB/Polars/sklearn)  
**Run date**: 2026-04-11

---

## 1. Dataset Volume

| Entity | Count |
|--------|-------|
| .xg files | 166,713 |
| Matches | TBD |
| Games | TBD |
| Positions (total) | TBD |
| Checker decisions | TBD |
| Cube decisions | TBD |
| Unique players (≥20 matches) | TBD |
| Parquet size (raw) | TBD |
| Parquet size (enriched) | TBD |

---

## 2. S0 — Data Infrastructure

### S0.4 Feature Engineering
- 34 features computed per position
- Match phase distribution: TBD contact / TBD race / TBD bearoff

### S0.5 Data Validation
- Referential integrity: TBD
- Probability sanity: TBD
- Board validity: TBD

### S0.6 Position Hashing
- Unique positions (by canonical hash): TBD
- Top convergence: TBD

### S0.7 Trajectory Graph
- Nodes (≥3 matches): TBD
- Edges: TBD

---

## 3. S1 — Exploration

### S1.1 Descriptive Statistics
- Median checker error: TBD
- Median cube error: TBD
- Most common away score: TBD
- Mean match length: TBD games

### S1.2 Feature-Error Correlation
- Top 5 features correlated with error: TBD

### S1.3 Position Clustering
- Checker clusters found: TBD
- Cube clusters found: TBD
- Cluster sizes: TBD

### S1.4 Anomaly Detection
- Blunders (error > 0.100): TBD %
- Structural outliers: TBD

### S1.5 Volatility
- High-complexity positions: TBD %
- Most volatile phase: TBD

### S1.6 Dice
- Hardest dice combo: TBD (avg error TBD)
- Doubles vs non-doubles avg error: TBD vs TBD

### S1.7 Temporal
- Fatigue effect (game N error drift): TBD
- Post-blunder tilt: TBD

### S1.8 Graph Topology
- Most traversed crossroad: TBD
- Louvain communities: TBD

---

## 4. S2 — Player Profiling

### S2.1 Player Profiles
- Players profiled: TBD
- Overall avg PR: TBD
- Best player PR: TBD

### S2.2 Player Archetypes
- Clusters found: TBD
- Archetype distribution: TBD

### S2.3 Rankings
- Top-ranked player: TBD (PR: TBD)
- PR vs win-rate correlation: TBD

### S2.4 Strengths/Weaknesses
- Most common weakness zone: TBD
- Most common strength zone: TBD

---

## 5. S3 — Practical Rules

### S3.1 Cube Error Heatmap
- Worst (away_p1, away_p2) cell: TBD (error TBD)
- Number of hot spots: TBD

### S3.2 MET Verification
- Max deviation from Kazaross: TBD pts
- Most biased score zone: TBD

### S3.3 Cube Equity Thresholds
- Avg double threshold: TBD equity
- Avg pass threshold: TBD equity

### S3.4 Heuristics
- Rules extracted: TBD
- Best rule precision: TBD %

### S3.5 Gammon Impact
- Score zone with highest gammon value: TBD
- Dead gammon positions: TBD %

### S3.6 Cube Model
- 4-class accuracy: TBD %
- Top SHAP feature: TBD

---

## 6. Key Findings

> To be filled after pipeline completes.

---

## 7. Pipeline Performance

| Step | Duration | Notes |
|------|----------|-------|
| S0.1+S0.2 (export+convert, 34 batches) | TBD min | 166K files, 5000/batch |
| S0.4 (features) | TBD min | 100K chunk-rows |
| S0.5 (validation) | TBD sec | DuckDB queries |
| S0.6 (hashing) | TBD min | xxhash64, 200K chunks |
| S0.7 (graph) | TBD min | threshold=3 |
| S1.1–S1.8 | TBD min | 500K samples |
| S2.1–S2.4 | TBD min | 5–10M samples |
| S3.1–S3.6 | TBD min | 500K–5M samples |
| **Total** | **TBD** | |

---

## 8. Disk Usage

| Directory | Size |
|-----------|------|
| data/parquet/ | TBD |
| data/parquet/positions_enriched/ | TBD |
| data/clusters/ | TBD |
| data/player_profiles/ | TBD |
| data/cube_analysis/ | TBD |
| data/stats/ | TBD |
| **Total** | **TBD** |
