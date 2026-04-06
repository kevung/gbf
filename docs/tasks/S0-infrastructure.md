# S0 — Data Infrastructure

## Objective

Build the complete data pipeline from raw .xg files to an enriched,
queryable analytical dataset. This pipeline is independent from the GBF
binary format — it uses JSONL, Parquet, and DuckDB for analytical workloads.

## Pre-requisites

None (independent from GBF track M0-M10). Shares the `xgparser` library.

## Sub-steps

### S0.1 — Go JSONL Export

**Objective**: Add a JSONL export mode to `xgparser` producing 3 file types.

**Input**: .xg files, xgparser source code.
**Output**: `matches.jsonl`, `games.jsonl`, `positions.jsonl`.
**Dependencies**: None.
**Complexity**: Medium.

**Schema `matches.jsonl`** (one JSON object per line):
```json
{
  "match_id": "hash_unique",
  "player1": "Player Name 1",
  "player2": "Player Name 2",
  "match_length": 7,
  "tournament": "Monte Carlo 2019",
  "date": "2019-05-15",
  "winner": 1,
  "score_final_p1": 7,
  "score_final_p2": 5,
  "num_games": 8
}
```

**Schema `games.jsonl`**:
```json
{
  "game_id": "match_id_game_03",
  "match_id": "hash_unique",
  "game_number": 3,
  "score_away_p1": 4,
  "score_away_p2": 6,
  "crawford": false,
  "post_crawford": false,
  "winner": 2,
  "points_won": 2,
  "gammon": true,
  "backgammon": false
}
```

**Schema `positions.jsonl`**:
```json
{
  "position_id": "game_id_move_017",
  "game_id": "game_id",
  "move_number": 17,
  "player_on_roll": 1,
  "decision_type": "checker",
  "dice": [3, 5],
  "board_p1": [0, 2, 0, ...],
  "board_p2": [0, -2, 0, ...],
  "cube_value": 2,
  "cube_owner": 1,
  "eval_equity": 0.453,
  "eval_win": 0.612,
  "eval_win_g": 0.158,
  "eval_win_bg": 0.008,
  "eval_lose_g": 0.092,
  "eval_lose_bg": 0.003,
  "move_played": "13/8 6/3",
  "move_played_error": 0.034,
  "best_move": "13/10 13/8",
  "best_move_equity": 0.487,
  "candidates": [
    {"move": "13/10 13/8", "equity": 0.487, "win": 0.625, ...},
    {"move": "13/8 6/3", "equity": 0.453, "win": 0.612, ...}
  ]
}
```

**Implementation notes**:
- Deterministic `match_id` = hash(players + date + tournament)
- Board as 26-int array: indices 0 (bar) to 25 (off), positive = player's
  checkers, negative = opponent's. Or 2 separate unsigned arrays.
- Cube decisions: `dice` is null, `decision_type` = "cube", move fields
  replaced by `cube_action_played` and `cube_action_optimal`
- Batch export per .xg file to manage 24 GB without RAM explosion

---

### S0.2 — JSONL to Parquet Conversion

**Objective**: Convert JSONL to partitioned Parquet files optimized for
analytical queries.

**Input**: JSONL files from S0.1.
**Output**: `data/matches.parquet`, `data/games.parquet`,
`data/positions/` (partitioned).
**Dependencies**: S0.1.
**Complexity**: Low.

**Details**:
- Language: Python with `pyarrow` or `polars`
- Partitioning: positions by match_id batch (or tournament), target
  ~100-500 MB per file
- Strict typing: int8 for board, float32 for probabilities, categorical
  string for player/tournament names
- Compression: snappy (default, good speed/size tradeoff)
- Verification: total count of positions, matches, games after conversion

**Script**: `scripts/convert_jsonl_to_parquet.py`

---

### S0.3 — DuckDB Access Layer

**Objective**: Python module exposing SQL queries on Parquet via DuckDB.

**Input**: Parquet files from S0.2.
**Output**: Python module `bgdata.py` with reusable query functions.
**Dependencies**: S0.2.
**Complexity**: Low-Medium.

**Minimal API**:
```python
class BGDatabase:
    def __init__(self, data_dir: str)
    def query(self, sql: str) -> pl.DataFrame
    def get_match(self, match_id: str) -> dict
    def get_positions(self, filters: dict) -> pl.DataFrame
    def get_player_stats(self, player_name: str) -> dict
    def get_tournament_stats(self, tournament: str) -> dict
    def summary(self) -> dict  # counts, basic distributions
```

**Notes**:
- DuckDB reads Parquet directly (no RAM loading)
- LRU cache for frequent queries
- Pre-defined queries for recurring aggregations (by player, score, tournament)

---

### S0.4 — Feature Engineering

**Objective**: Compute ~30 interpretable features from raw board state.

**Input**: Positions table in Parquet.
**Output**: `positions_enriched.parquet` with ~30 additional columns.
**Dependencies**: S0.2.
**Complexity**: Medium-High.

**Position structure features (per player)**:
- `pip_count`: weighted sum of checkers x distance to off
- `pip_count_diff`: difference between players
- `num_blots`: isolated checkers (vulnerable)
- `num_points_made`: held points (>= 2 checkers)
- `home_board_points`: held points in home board (1-6)
- `home_board_strength`: weighted home board score (high points worth more)
- `longest_prime`: longest sequence of consecutive held points
- `prime_location`: starting point of longest prime
- `back_anchor`: most advanced held point in opponent's board (0 if none)
- `num_checkers_back`: checkers in opponent's board
- `num_on_bar`: checkers on the bar
- `num_borne_off`: checkers borne off
- `num_builders`: lone checkers adjacent to points to build
- `connectivity`: proximity measure between checkers
- `outfield_blots`: blots between points 7 and 18
- `timing`: ability to maintain a position indicator

**Match context features**:
- `match_phase`: "contact", "race", "bearoff"
- `cube_leverage`: cube_value / remaining points ratio
- `gammon_threat`: combined gammon probability (win_g + win_bg)
- `gammon_risk`: probability of losing gammon (lose_g + lose_bg)
- `net_gammon`: gammon_threat - gammon_risk
- `take_point_money`: 0.25 (constant, for comparison)
- `take_point_match`: calculated from MET and away score
- `cube_efficiency`: equity ratio with/without cube
- `volatility`: std dev of candidate move equities

**Away score features**:
- `leader`: leading player (1, 2, or 0 if tied)
- `score_differential`: away score difference
- `crawford_proximity`: min(away_p1, away_p2) - 1
- `is_2away_2away`, `is_2away_4away`, etc.: classic score flags
- `pre_crawford`, `crawford`, `post_crawford`: match phase
- `dgr` (dead gammon risk): gammon worthless for leader at certain scores

**Implementation notes**:
- Batch compute with Polars (vectorized expressions, no Python loops)
- Prime/contact detection: Python utility functions, then vectorize
- MET: integrate Kazaross-XG2 Match Equity Table as reference
- Output: `positions_enriched.parquet`

---

### S0.5 — Data Quality Validation

**Objective**: Ensure data consistency and quality before analysis.

**Input**: All Parquet tables.
**Output**: Quality report (notebook or markdown).
**Dependencies**: S0.2, S0.4.
**Complexity**: Low.

**Checks**:
- Referential integrity: every game_id in positions exists in games, etc.
- Distributions: no outlier probabilities (win + lose ≈ 1), equities in [-3, +3]
- Completeness: percentage of positions with full analysis, positions without candidates
- Valid boards: 15 checkers per player, no impossible negative values
- Temporal coherence: moves are ordered, scores evolve logically
- Duplicates: no duplicate positions
- Volume statistics: distributions by tournament, player, year

---

### S0.6 — Position Hashing + Convergence Index

**Objective**: Create a canonical hash per position to detect when different
games traverse the same exact position.

**Input**: Positions table in Parquet.
**Output**: `position_hashes.parquet` + `convergence_index.parquet`.
**Dependencies**: S0.2.
**Complexity**: Medium-High.

**Canonicalization**:
1. Normalize: always encode from on-roll player's perspective
2. Hash = `hash(board_canonical, cube_value, cube_owner_relative,
   score_away_on_roll, score_away_opponent)`
3. Use xxhash64 or cityhash for performance on 160M positions

**Output schemas**:

`position_hashes.parquet`:
- position_id (string), position_hash (uint64), game_id, match_id, move_number

`convergence_index.parquet`:
- position_hash (uint64), occurrence_count (int), distinct_matches (int),
  distinct_games (int)

**Preliminary analyses**:
- Hash occurrence distribution: how many positions are unique vs shared?
- Top 1000 most frequent positions (the "crossroads" of the game)
- Convergence rate by game phase: do openings converge more than mid-game?

**Implementation notes**:
- Batch compute with Polars + hashing UDF
- Store hash → position_ids as Parquet with group-by (not in memory)
- Minimum occurrence threshold for trajectory analysis (e.g., ≥ 5 distinct matches)

---

### S0.7 — Trajectory Graph Construction

**Objective**: Model games as trajectories in position space with hashed
positions as nodes and moves as edges.

**Input**: `position_hashes` (S0.6) + positions + games.
**Output**: Transition graph between hashed positions + edge metadata.
**Dependencies**: S0.6.
**Complexity**: High.

**Graph structure**:
- Nodes = position_hash (unique canonical positions)
- Edges = observed transitions between consecutive positions in a game

**Schema `edges.parquet`**:
- from_hash (uint64), to_hash (uint64), game_id, match_id, move_number,
  dice (array), move_played (string), error (float), player (string)

**Pre-computed node metrics**:
- In/out degree (how many transitions arrive/depart)
- Distinct match count through this node
- Average decision error at this node
- Average equity at this node
- Move diversity (entropy of outgoing transitions)

**Pre-computed edge metrics**:
- Frequency: how many times this exact transition was observed
- Proportion: share of all outgoing transitions from from_hash

**Game trajectory**: ordered hash sequence [h0, h1, h2, ..., hn].
A match = set of trajectories.

**Size management**:
- Materialize only nodes with occurrence >= threshold (e.g., >= 3 distinct matches)
- Rare edges (seen once) can be filtered for visualization but kept for queries
- Store as Parquet; use DuckDB for trajectory queries
