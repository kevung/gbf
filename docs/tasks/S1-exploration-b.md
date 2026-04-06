# S1 — Exploration & Pattern Discovery (Part B: S1.5-S1.8)

## Objective

Deeper explorations: position volatility, dice structures, temporal patterns
within matches, and trajectory graph topology.

## Pre-requisites

S0.4 (feature engineering), S0.7 (trajectory graph for S1.8).

## Sub-steps

### S1.5 — Position Volatility & Complexity Analysis ✅

**Objective**: Study position complexity and its relationship to error
magnitude across game phase, score context, and structural features.

**Implementation**: `scripts/analyze_volatility.py`

**Input**: `positions_enriched` directory (S0.4, checker decisions only).
**Output**: Complexity breakdown CSVs by phase, pip, gammon, leverage.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Note on design**: the `candidates` column was dropped in S0.2 to avoid
nested-struct complexity. True volatility (std dev of candidate equities)
is therefore unavailable. `move_played_error` is used as a proxy for
decision difficulty.

**Complexity classes** (based on `move_played_error`):
- `trivial` (< 0.010): essentially perfect play
- `easy` (0.010–0.025): slight inaccuracy
- `moderate` (0.025–0.050): non-trivial decision
- `difficult` (0.050–0.100): hard position
- `very-difficult` (≥ 0.100): blunder-level complexity

**Analyses implemented**:
1. Overall complexity class distribution (count + mean error)
2. Complexity by game phase (contact / race / bearoff)
3. Complexity by pip count bins (game stage proxy)
4. Complexity by gammon threat level (<10% / 10-25% / 25-40% / ≥40%)
5. Complexity by cube leverage (<0.25 / 0.25-0.50 / 0.50-1.00 / ≥1.00)
6. High-complexity position profile: feature means for error ≥ 0.050
   vs trivial positions — ratios reveal which structures are hardest
7. Complexity by move number within game (early vs late game patterns)

**CSV outputs** (7 files):
`complexity_distribution.csv`, `complexity_by_phase.csv`,
`complexity_by_pip.csv`, `complexity_by_gammon.csv`,
`complexity_by_leverage.csv`, `high_complexity_profile.csv`,
`complexity_by_move_number.csv`

**Usage**:
```bash
python scripts/analyze_volatility.py \
  --enriched data/parquet/positions_enriched \
  [--output data/volatility] [--sample 500000]
```

---

### S1.6 — Dice Structure Analysis ✅

**Objective**: Explore the relationship between dice rolled, position
structure, and decision quality.

**Implementation**: `scripts/analyze_dice.py`

**Input**: `positions_enriched` directory (S0.4, checker decisions with dice).
**Output**: Error/nontrivial-rate breakdown by dice combination and context.
**Dependencies**: S0.4.
**Complexity**: Low-Medium.

**Dice features derived**:
- `combo`: canonical unordered pair label (`[6,1]` → `"61"`, `[1,6]` → `"61"`)
- `is_double`: boolean
- `total_pips`: 2×(a+b) for non-doubles, 4×a for doubles

**Analyses implemented**:
1. Mean error per dice combination (all 21 unordered pairs), sorted by
   mean error — identifies which rolls are systematically harder to play
2. Doubles vs non-doubles: error + nontrivial rate comparison
3. Dice × game phase: doubles/non-doubles error split per phase
   (contact / race / bearoff)
4. Error by total pips moved (movement potential effect)
5. Doubles × gammon threat: does high gammon threat amplify doubles errors?

**CSV outputs** (5 files):
`error_by_dice_combo.csv`, `doubles_vs_nondoubles.csv`,
`dice_by_phase.csv`, `error_by_dice_pips.csv`, `dice_by_gammon.csv`

**Usage**:
```bash
python scripts/analyze_dice.py \
  --enriched data/parquet/positions_enriched \
  [--output data/dice] [--sample 500000]
```

---

### S1.7 — Temporal & Sequential Analysis ✅

**Objective**: Study how play quality evolves within matches and games.

**Implementation**: `scripts/analyze_temporal.py`

**Input**: `positions_enriched` directory (S0.4) + `games.parquet` (S0.2).
**Output**: 6 CSV files + autocorrelation summary in `--output` directory.
**Dependencies**: S0.3, S0.4.
**Complexity**: Medium.

**Analyses implemented**:
1. Error by game number within match: fatigue (degradation over games)
   vs warm-up (improvement). Grouped by game_number, showing mean/median
   error, nontrivial rate, and blunder rate.
2. Error by move number within game: binned in 5-move intervals.
   Early vs late game error patterns.
3. Post-blunder tilt: for each position, look up the same player's
   previous move (move_number - 2, since players alternate). Compare
   error after a blunder (≥ 0.100) vs after a normal move. Includes
   severity breakdown of the triggering blunder.
4. Post-loss effect: join positions with games table to determine if
   the on-roll player lost the previous game. Compare error for
   "lost_prev" / "won_prev" / "first_game". Includes breakdown by
   game number (does post-loss effect worsen in late games?).
5. Score deficit effect: using score_differential (or computed from
   score_away fields), bucket positions by deficit level from
   "big deficit (≤-4)" to "big lead (≥+4)". Error comparison
   across brackets.
6. Error autocorrelation: lag-1 Pearson correlation of consecutive
   errors by the same player in the same game. Plus bucketed analysis:
   mean next error given previous error level.

**CSV outputs** (6 files):
`error_by_game_number.csv`, `error_by_move_number.csv`,
`post_blunder_tilt.csv`, `post_loss_effect.csv`,
`score_deficit_effect.csv`, `error_autocorrelation.csv`

**Usage**:
```bash
python scripts/analyze_temporal.py \
  --enriched data/parquet/positions_enriched \
  --parquet data/parquet \
  [--output data/temporal] [--sample 500000]
```

---

### S1.8 — Convergence & Graph Topology ✅

**Objective**: Explore the trajectory graph structure — crossroads,
convergence, divergence, and topological metrics.

**Implementation**: `scripts/analyze_graph_topology.py`

**Input**: Trajectory graph (S0.7), position clusters (S1.3, optional).
**Output**: 9 CSV files in `--output` directory.
**Dependencies**: S0.7, S1.3.
**Complexity**: High.

**Game crossroads**:
- Identify positions traversed by the most distinct matches
- Characterize crossroads: concentrated in openings? Do some exist in
  mid-game? (avg_move_number per hash)
- For each crossroad: what is the continuation range? (move_entropy)
- Correlation between crossroad frequency and average error: are familiar
  positions played better? (Spearman ρ + binned table)

**Divergence analysis**:
- From top 20 crossroads, track successor hashes at horizons H=3, 5, 10
- divergence_rate = distinct successors / total games at each horizon
- cluster_retention = fraction of trajectories still in the same S1.3 cluster

**Convergence analysis**:
- Convergence attractors: nodes with high in_degree / out_degree ratio
- Enriched with dominant S1.3 cluster label

**Graph topological metrics**:
- Degree distribution (in/out), power-law indicators → `degree_distribution.csv`
- Weakly/strongly connected components
- Approximate betweenness centrality on k-core subgraph (k=200 samples)
  → `betweenness_centrality.csv`
- Louvain communities + cross-table vs S1.3 clusters
  → `louvain_communities.csv`, `community_vs_cluster.csv`

**Paths**:
- Most frequent 3-5 move n-grams from game trajectories → `frequent_paths.csv`
- Edge frequency bins: highway (≥10 traversals) vs trail → `path_categories.csv`

**CSV outputs** (9 files):
`top_crossroads.csv`, `crossroads_error_correlation.csv`,
`degree_distribution.csv`, `betweenness_centrality.csv`,
`louvain_communities.csv`, `community_vs_cluster.csv`,
`frequent_paths.csv`, `path_categories.csv`,
`divergence_analysis.csv`, `convergence_attractors.csv`

**Usage**:
```bash
python scripts/analyze_graph_topology.py \
  --graph-dir data/parquet \
  --parquet-dir data/parquet \
  --clusters-dir data/clusters \
  [--output data/graph_topology] [--max-traj 50000]
```
