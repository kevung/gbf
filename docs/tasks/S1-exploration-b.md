# S1 — Exploration & Pattern Discovery (Part B: S1.5-S1.8)

## Objective

Deeper explorations: position volatility, dice structures, temporal patterns
within matches, and trajectory graph topology.

## Pre-requisites

S0.4 (feature engineering), S0.7 (trajectory graph for S1.8).

## Sub-steps

### S1.5 — Position Volatility Analysis

**Objective**: Study volatility (spread between candidate moves) as a
measure of complexity and risk.

**Input**: Positions table with candidate moves.
**Output**: Volatility analysis by game phase, score, structure.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Method**:
1. Volatility = standard deviation of the N candidate move equities
2. Also: gap between best and second-best move (error margin)
3. Correlate volatility with: game phase, pip count, blot count, away score
4. Test hypothesis: do high-volatility positions produce more errors?
5. Identify position configurations that systematically generate high volatility

**Practical value**: high-volatility positions are those requiring the most
thought — a warning signal for players.

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
