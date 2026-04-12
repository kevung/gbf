# Mining Study — Pipeline Architecture

## Overview

The mining study uses a Python/Polars/DuckDB pipeline independent from the
GBF binary format. It shares the `xgparser` library with the GBF pipeline
but follows its own data path optimized for analytical workloads on 160M
positions.

```
.xg files (24 GB, 166K matches)
        |
        v
+-------------------+
|  xgparser (Go)    |  JSONL export mode (S0.1)
+--------+----------+
         |  matches.jsonl, games.jsonl, positions.jsonl
         v
+-------------------+
|  Parquet (S0.2)   |  pyarrow / polars conversion
+--------+----------+
    |         |
    v         v
 DuckDB    Polars
 (S0.3)    (S0.4)
    |         |
    v         v
+-------------------+
|  Enriched Data    |  positions_enriched.parquet (~30 features)
+--------+----------+
    |    |    |    |
    v    v    v    v
  S0.5  S0.6  S1   S2/S3
  QA    Hash  Exploration  Profiling/Rules
         |         |
         v         ├→ S1.9 Themes → S2.5 Player Theme Profiles
+-------------------+
|  Trajectory Graph |  edges.parquet, node metrics (S0.7)
+--------+----------+
         |
         v
    S1.8 Topology
         |
         v
    S4 Dashboard
```

## GBF Pipeline vs Mining Pipeline

| Aspect | GBF Pipeline | Mining Pipeline |
|--------|-------------|-----------------|
| Language | Go | Python (Polars, DuckDB) |
| Storage format | GBF binary 80B records | JSONL → Parquet |
| Database | SQLite / PostgreSQL | DuckDB (on Parquet) |
| Query interface | Go Store API + SQL | DuckDB SQL + Polars expressions |
| Record format | Integer-only, deterministic | Native types (float, string) |
| Hash algorithm | Zobrist (context + board-only) | xxhash64 (canonical position) |
| Primary purpose | Normalized storage + API + SaaS | Analytical exploration + ML |
| Scale target | 110M positions (BMAB) | 160M positions (XG) |

**Shared component**: `xgparser` library (Go) — parses .xg files. The GBF
pipeline converts to BaseRecord; the mining pipeline exports to JSONL.

## Data Schemas

### JSONL Export (S0.1)

Three file types, one JSON object per line:

**matches.jsonl**: match_id (deterministic hash), player names, match length,
tournament, date, winner, final scores, game count.

**games.jsonl**: game_id (match_id + game number), away scores, Crawford
flags, winner, points won, gammon/backgammon flags.

**positions.jsonl**: position_id (game_id + move number), player on roll,
decision type (checker/cube), dice, board state (26-int array per player),
cube state, XG evaluation (equity, win/gammon/backgammon probabilities),
move played + error, best move + equity, candidate list with full evaluations.

### Parquet Storage (S0.2)

- `data/matches.parquet` — single file
- `data/games.parquet` — single file
- `data/positions/` — partitioned by match_id batch (~100-500 MB each)
- `data/positions_enriched.parquet` — with ~30 derived features (S0.4)
- `data/position_hashes.parquet` — canonical hashes (S0.6)
- `data/convergence_index.parquet` — hash occurrence counts (S0.6)
- `data/edges.parquet` — trajectory graph edges (S0.7)

Typing: int8 for board values, float32 for probabilities, categorical
strings for player/tournament names. Snappy compression.

## Feature Engineering (S0.4)

~30 derived features in 3 categories:

**Position structure** (per player, ~16 features): pip count, blots, made
points, home board points/strength, longest prime + location, back anchor,
checkers back, bar, borne off, builders, connectivity, outfield blots, timing.

**Match context** (~9 features): game phase (contact/race/bearoff), cube
leverage, gammon threat/risk/net, take point (money + match), cube
efficiency, volatility.

**Away score** (~7 features): leader, score differential, Crawford proximity,
classic score flags, Crawford phase, dead gammon risk.

All computed in batch with Polars vectorized expressions. The Kazaross-XG2
MET is integrated as a reference table for match take points.

## Position Hashing (S0.6)

**Canonical form**: always encode from on-roll player's perspective.

**Hash function**: xxhash64 on (board_canonical, cube_value,
cube_owner_relative, away_on_roll, away_opponent).

**Convergence index**: group-by on position_hash, compute occurrence count,
distinct matches, distinct games. Stored as Parquet (not in-memory) given
160M positions.

## Trajectory Graph (S0.7)

**Nodes** = unique canonical position hashes.
**Edges** = observed transitions between consecutive positions in a game.

Edge attributes: from_hash, to_hash, game_id, match_id, move_number, dice,
move_played, error, player.

Pre-computed metrics per node: in/out degree, distinct match count, average
error, average equity, move entropy (diversity of outgoing transitions).

Pre-computed metrics per edge: frequency (observation count), proportion
(share of outgoing transitions from source node).

**Size management**: materialize only nodes with >= threshold occurrences
(e.g., >= 3 distinct matches). Rare edges kept in Parquet for point queries
but filtered for visualization. All stored as Parquet, queried via DuckDB.

## Feedback Loop to GBF

The mining study findings will inform future GBF format revisions:

- **New derived columns**: features proven discriminant in S1.2 may become
  derived columns in the GBF schema (as was done with pos_class, pip_diff,
  prime_len in M9)
- **Clustering labels**: if position clusters from S1.3 prove stable, a
  cluster_id column could be added to the GBF positions table
- **Schema extensions**: trajectory data or convergence metrics may justify
  new GBF tables
- **Feature vector changes**: S1.2/S1.3 may identify features to add or
  remove from the GBF feature extraction (M4)

These changes would be implemented as new GBF milestones (M11+) once study
results are validated.
