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

### S1.6 — Dice Structure Analysis

**Objective**: Explore the relationship between dice rolled, position
structure, and decision quality.

**Input**: `positions_enriched` (checker decisions only).
**Output**: Analysis by dice combination.
**Dependencies**: S0.4.
**Complexity**: Low-Medium.

**Analyses**:
- Average error per dice combination (21 unordered combinations): are some
  rolls systematically played worse?
- Dice x game phase interaction: are doubles played worse in bearing off?
- Dice x structure interaction: do certain combinations on certain prime or
  blot patterns induce more errors?
- Average number of reasonable candidate moves per dice combination
  (decision complexity)

---

### S1.7 — Temporal & Sequential Analysis

**Objective**: Study how play quality evolves within matches and games.

**Input**: Positions, games, matches tables.
**Output**: Evolution curves, fatigue/tilt tests.
**Dependencies**: S0.3.
**Complexity**: Medium.

**Analyses**:
- Average error by game number within match: is there degradation (fatigue)
  or improvement (warm-up)?
- Average error by move number within game: early vs late game
- Post-blunder effect: does a player who makes a blunder play worse on the
  next move? (tilt)
- Post-loss effect: does play quality drop after losing a game?
- Score deficit effect: when trailing significantly, do players play better
  or worse?
- Error autocorrelation: do errors come in series?

---

### S1.8 — Convergence & Graph Topology

**Objective**: Explore the trajectory graph structure — crossroads,
convergence, divergence, and topological metrics.

**Input**: Trajectory graph (S0.7), position clusters (S1.3).
**Output**: Crossroad map, convergence analysis, topological metrics report.
**Dependencies**: S0.7, S1.3.
**Complexity**: High.

**Game crossroads**:
- Identify positions traversed by the most distinct matches
- Characterize crossroads: concentrated in openings? Do some exist in
  mid-game?
- For each crossroad: what is the continuation range? Is there a dominant
  move or genuine diversity?
- Correlation between crossroad frequency and average error: are familiar
  positions played better?

**Divergence analysis**:
- From a given crossroad, follow diverging trajectories: at what horizon
  (number of moves) do two games that were at the same point become
  "structurally different" (cluster change)?
- Measure "divergence rate": are some positions bifurcation points (one
  move changes everything) vs stable positions (trajectories stay similar)?

**Convergence analysis**:
- The inverse: do games from very different positions converge to the same
  positions? (e.g., different openings leading to the same mid-game structures)
- Identify "attractors": positions the game naturally tends toward

**Graph topological metrics**:
- Degree distribution (power law? scale-free?)
- Connected components: is the graph connected or fragmented?
- Betweenness centrality: which positions are mandatory passages?
- Louvain communities: do they correspond to feature clusters (S1.3)?

**Paths and distance**:
- Average distance between two positions (in moves) in the graph
- Most frequent paths (3-5 move sequences most observed)
- Are there "highways" (high-frequency paths) vs "trails" (rare transitions)?

**Deliverable**: topological report + catalogue of top 100 crossroads with
their profile.
