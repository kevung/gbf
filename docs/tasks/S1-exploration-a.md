# S1 — Exploration & Pattern Discovery (Part A: S1.1-S1.4)

## Objective

Produce a comprehensive analytical overview of the dataset: descriptive
statistics, feature-error correlations, position clustering, and anomaly
detection.

## Pre-requisites

S0.4 (feature engineering), S0.5 (data quality validation).

## Sub-steps

### S1.1 — Global Descriptive Statistics

**Objective**: Comprehensive statistical overview of the database.

**Input**: Enriched tables (S0.4).
**Output**: Jupyter notebook with visualizations + summary report.
**Dependencies**: S0.4, S0.5.
**Complexity**: Low.

**Analyses**:
- Error distribution (histogram): by type (checker vs cube), by magnitude
- Equity distribution across all positions
- Game phase distribution (contact/race/bearoff) in the corpus
- Away score frequency across matches
- Match length distribution (number of games) and game length (number of moves)
- Top tournaments by volume, top players by match count
- Temporal evolution (if dates span multiple years)
- Cube value distribution when cube decisions occur

---

### S1.2 — Feature-Error Correlation Analysis

**Objective**: Identify which position and context features are most
correlated with error magnitude.

**Input**: `positions_enriched` table.
**Output**: Correlation matrix, feature importance ranking, visualizations.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Method**:
1. Spearman correlation (non-linear) between each feature and `move_played_error`
2. Mutual information between categorical features and error
3. Separate analysis: checker errors vs cube errors (very different mechanisms)
4. Watch for confounders: pip count correlates with game phase, which
   correlates with error → multivariate analysis needed
5. Random Forest feature importance as complement (lightweight model,
   goal = interpretability)

**Visualizations**:
- Correlation heatmap between all features
- Scatter plots of top 5 features vs error
- Box plots of error by category (game phase, away score bracket, cube owner)

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
