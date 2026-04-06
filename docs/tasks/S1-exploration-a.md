# S1 — Exploration & Pattern Discovery (Part A: S1.1-S1.4)

## Objective

Produce a comprehensive analytical overview of the dataset: descriptive
statistics, feature-error correlations, position clustering, and anomaly
detection.

## Pre-requisites

S0.4 (feature engineering), S0.5 (data quality validation).

## Sub-steps

### S1.1 — Global Descriptive Statistics ✅

**Objective**: Comprehensive statistical overview of the database.

**Implementation**: `scripts/descriptive_stats.py`

**Input**: Parquet tables (S0.2) + enriched positions (S0.4, optional).
**Output**: Structured console report + CSV summaries in `--output` dir.
**Dependencies**: S0.4, S0.5.
**Complexity**: Low.

**Analyses implemented (11 sections)**:
- Dataset overview: counts per table, decision type split
- Error distribution: mean/std/percentiles (p50–p99), magnitude buckets
  (perfect / tiny / small / medium / blunder >0.100)
- Equity distribution: mean/std/range, histogram by bucket ([-3,+3])
- Game phase distribution: contact/race/bearoff with bar chart
- Away score frequency: top 20 score pairs from games table
- Match & game lengths: min/max/avg/median + match_length distribution
- Top 20 tournaments and top 20 players by position volume
- Temporal evolution: matches and avg games per year
- Cube value distribution + cube action breakdown
- Gammon & backgammon rates + avg gammon threat/risk

**CSV outputs** (for notebooks / S3 / S4):
`error_distribution_checker.csv`, `equity_distribution.csv`,
`phase_distribution.csv`, `score_distribution.csv`,
`match_length_distribution.csv`, `tournament_volumes.csv`,
`player_volumes.csv`, `temporal_evolution.csv`,
`cube_value_distribution.csv`

**Usage**:
```bash
python scripts/descriptive_stats.py \
  --parquet-dir data/parquet \
  [--enriched data/parquet/positions_enriched] \
  [--output data/stats]
```

---

### S1.2 — Feature-Error Correlation Analysis ✅

**Objective**: Identify which position and context features are most
correlated with error magnitude.

**Implementation**: `scripts/correlation_analysis.py`

**Input**: `positions_enriched` table (S0.4).
**Output**: Ranked feature lists + 8 CSV files in `--output` dir.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Methods implemented**:
1. Spearman rank correlation (`scipy.stats.spearmanr`) between each feature
   and `move_played_error` — sorted by `abs_rho` descending
2. Mutual information (`sklearn.feature_selection.mutual_info_regression`)
   with discrete-feature detection (integer columns flagged automatically)
3. Random Forest feature importance (`RandomForestRegressor`, n=50, depth=5,
   n_jobs=-1) — lightweight model trained on `--sample` rows (default 500K)
4. Checker vs cube split: checker target = `move_played_error`;
   cube target = `abs(eval_equity)` (proxy for cube decision magnitude)
5. Error stratification by game phase, away score bracket, cube owner

**Features analyzed (29 checker, 15 cube)**:
- Board structure: pip counts, blots, points made, home board, primes,
  back anchor, builders, outfield blots, checkers on bar/borne off
- Match context: match_phase, gammon_threat/risk/net, cube_leverage
- Score: score_away_p1/p2, score_differential
- Eval: eval_win, eval_equity (confounder analysis)

**Away score brackets**: 1-away / 2-away / 3-4-away / 5-7-away / 8+-away / money

**CSV outputs** (8 files):
`spearman_checker.csv`, `spearman_cube.csv`, `mutual_info_checker.csv`,
`rf_importance_checker.csv`, `rf_importance_cube.csv`,
`error_by_phase.csv`, `error_by_score_bracket.csv`, `error_by_cube_owner.csv`

**Usage**:
```bash
python scripts/correlation_analysis.py \
  --enriched data/parquet/positions_enriched \
  --parquet-dir data/parquet \
  [--output data/stats] [--sample 500000]
```

---

### S1.3 — Position Clustering

**Objective**: Identify position families and characterize each cluster.

**Input**: `positions_enriched` (derived features).
**Output**: Cluster labels per position, cluster profile descriptions.
**Dependencies**: S0.4.
**Complexity**: High.

**Method**:
1. Feature selection: use interpretable features (not raw board), normalize
2. Dimensionality reduction: PCA first (understand variance), then UMAP
   (visualization)
3. Clustering: HDBSCAN (auto-detects cluster count, handles noise)
4. Start on sample (1M positions), extend if patterns are stable
5. Per cluster: average statistics, mean error, prototypical examples

**Expected clusters** (hypotheses to validate):
- Pure race positions
- Blitz positions
- Priming positions
- Back games
- Holding positions
- Bearing off with contact
- Scramble / complex positions

**Important**: cluster checker positions and cube positions separately.

**Deliverable**: annotated UMAP map + cluster descriptions + mean error
per cluster.

---

### S1.4 — Anomaly Detection & Trap Positions

**Objective**: Find positions where human error is systematically highest
— the "trap" positions.

**Input**: `positions_enriched` + clusters (S1.3).
**Output**: Catalogue of trap positions, common pattern analysis.
**Dependencies**: S1.3.
**Complexity**: Medium.

**Method**:
1. Identify positions with error > 0.100 (major blunders)
2. Among these, find those in similar structures (same cluster, close
   features) → recurring blunders vs unique blunders
3. For recurring blunders: extract common pattern (e.g., "incorrect take
   at 3-away 5-away with high gammon threat")
4. Compare move played vs optimal move: what type of error? (too aggressive?
   too defensive? gammon misjudgment?)
5. Isolation Forest or Local Outlier Factor on features to detect
   structurally unusual positions

**Deliverable**: top 50 most frequent blunder patterns with examples and
explanations.
