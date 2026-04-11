# S3 — Practical Rules for Play

## Objective

Extract actionable knowledge from the data: cube error maps, equity
thresholds, position-type heuristics, gammon impact analysis, and a
lightweight predictive model.

## Pre-requisites

S0.4 (feature engineering), S1.3 (position clusters for S3.4),
S1.2 (feature-error correlation for S3.6).

## Sub-steps

### S3.1 — Cube Error x Away Score Heatmap

**Objective**: Map the score zones where cube errors are maximal.

**Input**: Cube decisions in `positions_enriched`.
**Output**: Interactive heatmap + reference table.
**Dependencies**: S0.4.
**Complexity**: Low.

**Method**:
1. Filter positions with `decision_type = "cube"`
2. Aggregate average cube error per (away_p1, away_p2) pair — for 7-point
   matches, this is a 7x7 grid
3. Separate by error type: missed doubles, wrong takes, wrong passes
4. Produce separate heatmaps per match length (5/7/9/11 pts, etc.)
5. Identify "hot spots": scores where everyone makes mistakes

**Direct application**: "When you are at 3-away 5-away, pay special
attention to cube decisions."

---

### S3.2 — Empirical MET Verification

**Objective**: Compare XG-observed match equity with published MET tables
(Kazaross, Woolsey, etc.).

**Input**: All positions with XG-computed match equity.
**Output**: Theoretical vs empirical MET comparison, divergence zones.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Method**:
1. For each away score, compute average equity of "neutral" positions
   (game start, before first move) as proxy for match equity at that score
2. Compare with published MET values
3. Analyze deviations: are they systematic? In which zones?
4. Explore whether player level affects observed equity (do weaker players
   modify the effective equity?)

---

### S3.3 — Cube Equity Thresholds by Score

**Objective**: Extract practical equity thresholds (double/take/pass) for
each common away score.

**Input**: Cube decisions + enriched positions.
**Output**: Reference table of equity thresholds per score pair.
**Dependencies**: S0.4.
**Complexity**: Medium-High.

**Method**:
1. For each away score pair, collect all cube decisions
2. Identify the equity threshold above which doubling is correct (per XG)
3. Identify the threshold below which passing is correct
4. Build tables: "at 3-away 5-away, double from +0.32, take below -0.18"
5. Compare with existing simplified formulas (Janowski)
6. Verify how gammon rate modifies these thresholds (gammon x score interaction)

**Deliverable**: printable / memorizable threshold tables for common scores.

---

### S3.4 — Heuristics by Position Type

**Objective**: For each position cluster (S1.3), extract simple practical
rules.

**Input**: Clusters + enriched positions + error analyses.
**Output**: Catalogue of practical rules per position type.
**Dependencies**: S1.3, S1.4.
**Complexity**: High.

**Method**:
1. For each position cluster, train a shallow decision tree (max depth 3-4)
   predicting whether best move is offensive/defensive, or whether doubling
   is correct
2. Tree branches give interpretable rules: "If home board > 4 points AND
   opponent blots > 2 THEN blitz"
3. Validate rules on holdout set
4. Formulate in natural language for players
5. Complete with specific analyses: when to slot? when to split? when to
   prime vs blitz?

**Example deliverable**: "In contact with a 4+ point prime and good home
board (4+ points), double as soon as the opponent has a checker on the bar
— the average pass error is X in this configuration."

---

### S3.5 — Gammon Impact Analysis

**Objective**: Quantify how gammon threat/risk modifies optimal decisions
by score.

**Input**: Enriched positions with gammon probabilities.
**Output**: Gammon impact analysis, zones where gammon changes everything.
**Dependencies**: S0.4.
**Complexity**: Medium.

**Analyses**:
- At which scores does the gammon have the most value? (gammon value by
  away score)
- How does gammon consideration modify cube thresholds?
- Which position types generate the most gammons? (features predictive
  of gammon)
- Dead gammon situations: empirically verify when the gammon is irrelevant
- Free drop: quantify the advantage of the "free" pass in post-Crawford
  situations

---

### S3.6 — Lightweight Predictive Model

**Objective**: Train a simple model estimating the correct action from
interpretable features.

**Input**: `positions_enriched` table.
**Output**: Trained model + performance evaluation.
**Dependencies**: S0.4, S1.2.
**Complexity**: High.

**Approach**:
1. Start with a cube decision model: features → {double, no double, take, pass}
2. Gradient Boosting (XGBoost / LightGBM) with interpretable features
3. Evaluate: accuracy, but especially error magnitude when the model is wrong
4. Interpret with SHAP values to understand which features weigh in each
   decision
5. Compare with simple heuristics (S3.3): does the model really add value?

**Goal**: not to replace XG (impossible with simple features), but to create
a mental tool that players can approximate in their head during a game.

---

## Data Limitations — Cube Decisions

**Doubling only; Take/Pass not captured as separate records.**
The XG binary format records each doubling opportunity as a `CubeEntry`.
When the player doubles, the opponent's take/pass response is encoded in the
game state (cube goes up if taken, game ends if passed) but not emitted as a
separate cube position record by the exporter.

Consequence: `decision_type = "cube"` contains only positions where the player
considered doubling (played "No Double" or "Double"). `wrong_take_rate` and
`wrong_pass_rate` cannot be computed from this dataset.

**BestAction derivation (fixed in v2).**
Prior to the fix in `convert/xg.go`, `cube_action_optimal` was incorrectly
derived by taking the maximum of the three cubeful equities (NoDouble,
DoubleTake, DoublePass).  Since DoublePass ≈ +1.0 for most positions, this
inflated "Double/Pass" to 91% of decisions and suppressed "No Double" to 0.3%.

The corrected logic: the opponent minimises the doubler's equity, so the
effective equity when doubling is `min(DoubleTake, DoublePass)`.  Double is
correct iff this exceeds NoDouble; the opponent takes if DoubleTake ≤
DoublePass, else passes.
