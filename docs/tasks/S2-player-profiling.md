# S2 — Player Profiling

## Objective

Define and compute player profiles, group players into archetypes, build
rankings, and identify individual strengths and weaknesses.

## Pre-requisites

S0.4 (feature engineering), S1.3 (position clusters for S2.4).

## Sub-steps

### S2.1 — Player Profiling Metrics ✅

**Objective**: Define and compute ~22 metrics characterizing each player's
profile.

**Implementation**: `scripts/analyze_player_profiles.py`

**Input**: `positions_enriched/` (S0.4), `matches.parquet`, `games.parquet`.
**Output**:
- `player_profiles.parquet` / `.csv` — one row per player, ~22 metrics
- `cube_error_by_score.csv` — cube error × away-score bracket (top 50 players)
- `player_summary.txt` — ranked quick views

**Dependencies**: S0.4, matches.parquet (for player name resolution).
**Complexity**: Medium.

**Usage**:
```
python scripts/analyze_player_profiles.py \
    --enriched data/parquet/positions_enriched \
    --parquet  data/parquet \
    --output   data/player_profiles \
    --min-matches 20
```

**Global performance metrics**:
- `total_matches`, `total_positions`: volume
- `avg_error_checker`: average error on checker decisions
- `avg_error_cube`: average error on cube decisions
- `error_rate`: percentage of positions played with error > 0.02
- `blunder_rate`: percentage of positions with error > 0.08
- `pr_rating`: estimated performance rating (standard XG formula)

**Phase profile**:
- `avg_error_contact`, `avg_error_race`, `avg_error_bearoff`: error by phase
- `avg_error_opening` (first 10 moves), `avg_error_midgame`, `avg_error_endgame`

**Cube profile**:
- `missed_double_rate`: frequency of not doubling when correct
- `wrong_take_rate`: frequency of incorrect takes
- `wrong_pass_rate`: frequency of incorrect passes
- `avg_cube_error_by_score_bracket`: cube error segmented by score zone

**Tactical profile**:
- `aggression_index`: tendency to blitz/attack vs contain/defend (based on
  moves played vs safer alternatives)
- `risk_appetite`: frequency of choosing the most volatile move when
  several options are close

**Consistency**:
- `error_std`: error standard deviation (steady vs erratic player)
- `streak_tendency`: error autocorrelation (series tendency)

**Filter**: only profile players with >= N matches (threshold TBD, probably 20+).

---

### S2.2 — Player Clustering by Profile

**Objective**: Group players into archetypes based on their play profile.

**Input**: `player_profiles` table (S2.1).
**Output**: Player clusters, archetype descriptions.
**Dependencies**: S2.1.
**Complexity**: Medium.

**Method**:
1. Z-score normalization of metrics
2. PCA to identify main variation axes
3. K-means or HDBSCAN for clustering
4. Radar chart (spider chart) per cluster
5. Name archetypes intuitively

**Hypothetical archetypes**:
- "The Technician": low checker error, average cube error
- "The Cubist": good cube play, average checker play
- "The Sprinter": strong in race/bearoff, weak in contact
- "The Warrior": strong in blitz/contact, weak in quiet positions
- "The Steady": consistently low errors
- "The Erratic": alternates between good and bad play

---

### S2.3 — Benchmarking & Player Ranking

**Objective**: Build a data-driven ranking system.

**Input**: `player_profiles` + match data.
**Output**: Rankings, comparisons, evolution over time.
**Dependencies**: S2.1.
**Complexity**: Medium.

**Analyses**:
- PR ranking with confidence intervals
- Per-dimension ranking (best cubist, best in contact, etc.)
- Superimposed radar chart comparisons between players
- If data spans multiple years: PR evolution over time
- PR vs match results correlation: does the analytically better player
  win more often? What is the role of luck?
- Result variance analysis: which players over/under-perform relative
  to their PR?

---

### S2.4 — Individual Strengths/Weaknesses Analysis

**Objective**: For each player, identify specific strengths and weaknesses.

**Input**: `player_profiles` + `positions_enriched`.
**Output**: Individual report template: "strengths/weaknesses of Player X".
**Dependencies**: S2.1, S1.3 (position clusters).
**Complexity**: Medium.

**Method**:
1. For a given player, compute average error per position cluster (S1.3)
2. Compare to the global population average for the same cluster
3. Clusters where the player is significantly above average = weaknesses
4. Clusters where below average = strengths
5. Same analysis for away score zones (personal heatmap vs global heatmap)

**Deliverable**: auto-generatable report template for any player in the
database.
