# S0 — Data Infrastructure

## Objective

Build the complete data pipeline from raw .xg files to an enriched,
queryable analytical dataset. This pipeline is independent from the GBF
binary format — it uses JSONL, Parquet, and DuckDB for analytical workloads.

## Pre-requisites

None (independent from GBF track M0-M10). Shares the `xgparser` library.

## Sub-steps

### S0.1 — Go JSONL Export ✅

**Objective**: Add a JSONL export mode to `xgparser` producing 3 file types.

**Implementation**: `cmd/export-jsonl/main.go`

**Input**: .xg files, xgparser source code.
**Output**: `matches.jsonl`, `games.jsonl`, `positions.jsonl`.
**Dependencies**: None.
**Complexity**: Medium.

**Implementation notes (actual)**:
- `match_id`: SHA256(player1|player2|date|event)[:8] → 16-hex-char deterministic ID
- Board: two separate 26-int unsigned arrays (`board_p1`, `board_p2`), each
  from that player's perspective: index 0=bar, 1-24=points, 25=borne-off
- Cube decisions: `dice` is null, `decision_type`="cube", move fields replaced
  by `cube_action_played` and `cube_action_optimal`
- Parallel parsing with N workers (default: NumCPU), single-threaded writer
- Append mode: safe to resume; each run appends to existing files

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

### S0.2 — JSONL to Parquet Conversion ✅

**Objective**: Convert JSONL to partitioned Parquet files optimized for
analytical queries.

**Implementation**: `scripts/convert_jsonl_to_parquet.py`

**Input**: JSONL files from S0.1.
**Output**: `data/matches.parquet`, `data/games.parquet`,
`data/positions/` (partitioned).
**Dependencies**: S0.1.
**Complexity**: Low.

**Implementation notes (actual)**:
- Polars for JSONL reading and type casting; PyArrow for partitioned writes
- Positions partitioned by `hash(match_id) % N` (default N=16)
- Strict typing: `board_p1`/`board_p2` as `List[Int8]`, probabilities as
  `Float32`, equity as `Float64`, player/tournament as `Categorical`
- Streaming chunk-by-chunk (default 500K rows) — safe for 24 GB datasets
- Compression: snappy; verification step re-reads and asserts counts
- `candidates` column dropped (nested struct — store separately if needed)

**Usage**:
```bash
python scripts/convert_jsonl_to_parquet.py \
  --jsonl-dir data/jsonl \
  --parquet-dir data/parquet \
  [--positions-parts 16] [--chunk-rows 500000]
```

---

### S0.3 — DuckDB Access Layer ✅

**Objective**: Python module exposing SQL queries on Parquet via DuckDB.

**Implementation**: `scripts/bgdata.py`

**Input**: Parquet files from S0.2.
**Output**: Python module `bgdata.py` with reusable query functions.
**Dependencies**: S0.2.
**Complexity**: Low-Medium.

**API implemented**:
```python
class BGDatabase:
    def __init__(self, data_dir: str, cache_size: int = 64)
    def query(self, sql: str, cache: bool = False) -> pl.DataFrame
    def get_match(self, match_id: str) -> dict        # metadata + games
    def get_positions(self, filters: dict) -> pl.DataFrame  # scalar/range/IN
    def get_player_stats(self, player_name: str) -> dict    # wins, avg error
    def get_tournament_stats(self, tournament: str) -> dict # counts, top players
    def summary(self) -> dict                         # counts, distributions
```

**Pre-defined aggregations** (module-level functions):
- `error_by_score(db)` — avg checker error by (away_p1, away_p2)
- `cube_errors_by_score(db)` — cube decision errors by score
- `top_players_by_volume(db)` — players ranked by position count
- `equity_distribution(db)` — equity histogram with avg error per bin

**Notes**:
- DuckDB views over Parquet (no RAM loading), compatible with context manager
- LRU cache (configurable size) for repeated query results
- `get_positions` filters support: scalar (exact), tuple (range), list (IN)

---

### S0.4 — Feature Engineering ✅

**Objective**: Compute ~30 interpretable features from raw board state.

**Implementation**: `scripts/compute_features.py`

**Input**: Positions table in Parquet + games join (for score columns).
**Output**: `positions_enriched/*.parquet` — 33 new columns added.
**Dependencies**: S0.2.
**Complexity**: Medium-High.

**Features implemented (33 columns)**:

Board structure (vectorized Polars expressions):
- `pip_count_p1/p2`, `pip_count_diff`
- `num_blots_p1/p2`, `num_points_made_p1/p2`
- `home_board_points_p1/p2`, `home_board_strength_p1`
- `num_on_bar_p1/p2`, `num_borne_off_p1/p2`
- `num_checkers_back_p1`, `outfield_blots_p1`

Complex board features (map_elements for sequential logic):
- `longest_prime_p1/p2`, `prime_location_p1`
- `back_anchor_p1` (highest made point in opp home board, 19-24)
- `num_builders_p1`

Match context:
- `match_phase` (0=contact, 1=race, 2=bearoff) — contact test: back1+back2>24
- `gammon_threat`, `gammon_risk`, `net_gammon`
- `cube_leverage` (cube_value / max(away))

Score features (joined from games table):
- `leader`, `score_differential`, `is_dmp`, `dgr`
- `is_pre_crawford`, `is_post_crawford`
- `take_point_match` (Janowski approximation — full Kazaross MET deferred)

**Implementation notes**:
- Polars vectorized expressions for all simple features (no Python loops)
- `map_elements` only for sequential logic (prime, anchor, builders)
- DuckDB JOIN positions + games per chunk; streamed chunk-by-chunk
- Output partitioned by hash(game_id[:16]) % N, snappy compression

**Usage**:
```bash
python scripts/compute_features.py \
  --parquet-dir data/parquet \
  --output data/parquet/positions_enriched \
  [--chunk-rows 100000] [--parts 16]
```

---

### S0.5 — Data Quality Validation ✅

**Objective**: Ensure data consistency and quality before analysis.

**Implementation**: `scripts/validate_data.py`

**Input**: All Parquet tables (S0.2) + enriched positions (S0.4, optional).
**Output**: Structured console report; exits 1 if any FAIL-level check fails.
**Dependencies**: S0.2, S0.4.
**Complexity**: Low.

**Checks implemented (8 sections)**:
1. Referential integrity — game_id/match_id foreign keys across tables
2. Probability sanity — eval_win in [0,1], gammon ≤ win rate
3. Equity range — eval_equity in [-3,+3], mean ≈ 0, error in [0,3]
4. Board validity — 15 checkers per player, no negatives, sum=30
5. Completeness — % positions with analysis, cube decisions have action
6. Duplicates — no duplicate position_id or match_id
7. Move ordering — move_number monotone within each game
8. Score coherence — away > 0 for match-play, points_won ≥ 1

Volume statistics: counts by decision type, top tournaments, score pairs.
Enriched features: column presence, pip ≥ 0, match_phase ∈ {0,1,2}, gammon_threat ∈ [0,1].

**Bug fixed (S0.1)**: `score_away_p1/p2` in games.jsonl stored `InitialScore`
(raw points won) instead of away score (`match_length - initial_score`).
Fixed in `cmd/export-jsonl/main.go`.

**Usage**:
```bash
python scripts/validate_data.py \
  --parquet-dir data/parquet \
  [--enriched data/parquet/positions_enriched]
```

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
