# GBF Architecture

## Overview

GBF is a 5-layer system that imports backgammon match data from multiple
proprietary formats, normalizes it into a deterministic binary representation,
stores it in an indexed database, and provides query and visualization tools.

```
Source Files (.xg, .sgf, .mat, .bgf, .txt)
        |
        v
+-------------------+
|  Layer 1: Parsers |  xgparser, gnubgparser, bgfparser
+--------+----------+
         |  Normalized PositionState
         v
+-------------------+
|  Layer 2: GBF     |  BaseRecord 80B + analysis blocks
|  Record Format    |  Context-aware + board-only Zobrist
+--------+----------+
         |
         v
+-------------------+
|  Layer 3: Storage |  Store interface
+--------+----------+
    +---------+
    |         |
    v         v
 SQLite    PostgreSQL      --> Parquet export
 (local)   (SaaS/prod)
    |         |
    v         v
+-------------------+
|  Layer 4: Query   |  Go API, Python helpers
+--------+----------+
         |
         v
+-------------------+
|  Layer 5: Viz     |  Feature extraction, UMAP, PCA, clustering
+-------------------+
    |         |
    v         v
 Jupyter   SaaS UI
```

## Design Principles

1. **Determinism**: identical positions produce identical binary encoding and hashes
2. **Integer-only**: no floating-point in the binary format (see SPEC.md)
3. **Hybrid representation**: bitboard layers for structural detection + exact counts
4. **Separation of concerns**: record format != storage engine != query API != viz
5. **Backend-agnostic**: `Store` interface with SQLite and PostgreSQL implementations
6. **Language-agnostic storage**: SQLite and PostgreSQL both accessible from Go and Python

## Layer 1: Source Format Parsers

Three external libraries parse proprietary formats:

| Library       | Formats      | Coordinates          |
|---------------|-------------|----------------------|
| xgparser      | .xg          | Active-player relative |
| gnubgparser   | .sgf, .mat   | Absolute (both players)|
| bgfparser     | .bgf, .txt   | Player-relative        |

All parsers produce a `Match` structure. Each move's `PositionState` is then
converted to a GBF `BaseRecord` through format-specific normalization:

- Point indices remapped to GBF convention (0 = X's 1-point)
- Positive counts = Player X, negative = Player O
- Cube ownership mapped to 0/1/2
- Zobrist hash computed (both context-aware and board-only)

Legacy converter functions: `legacy/convert_xg.go`, `legacy/convert_gnubg.go`,
`legacy/convert_bgf.go`.

## Layer 2: GBF Record Format

See SPEC.md for the full binary specification. Key points:

- **BaseRecord**: 80 bytes, deterministic encoding
- **Analysis blocks**: 5 types (checker play, cube decision, engine metadata,
  match metadata, game boundary)
- **Dual Zobrist hashing**:
  - Context-aware (board + cube + away scores + side to move) — stored in record
  - Board-only (board configuration only) — computed at import, stored as DB column

Legacy implementation: `legacy/gbf.go` (structures), `legacy/record.go`
(marshal/unmarshal), `legacy/zobrist.go` (hash computation).

## Layer 3: Storage

### Store Interface

A minimal Go interface decouples business logic from the storage backend:

```go
type Store interface {
    // Import
    UpsertPosition(ctx context.Context, rec BaseRecord, boardHash uint64) (int64, error)
    AddAnalysis(ctx context.Context, positionID int64, block AnalysisBlock, engine string) error
    ImportMatch(ctx context.Context, match Match) error

    // Query
    QueryByZobrist(ctx context.Context, hash uint64) ([]Position, error)
    QueryByBoardHash(ctx context.Context, hash uint64) ([]Position, error)
    QueryByMatchScore(ctx context.Context, awayX, awayO int) ([]Position, error)

    // Lifecycle
    Close() error
}
```

The interface starts minimal and grows with each milestone.

Two implementations: `SQLiteStore` (local, embedded, exploration) and
`PGStore` (SaaS, concurrent writes, production).

### SQL Schema

```sql
CREATE TABLE positions (
    id          INTEGER PRIMARY KEY,   -- SERIAL in PostgreSQL
    zobrist_hash BIGINT NOT NULL,      -- context-aware (uint64 as int64)
    board_hash  BIGINT NOT NULL,       -- board-only (uint64 as int64)
    base_record BLOB NOT NULL,         -- 80 bytes (BYTEA in PostgreSQL)
    pip_x       INTEGER,
    pip_o       INTEGER,
    away_x      INTEGER,
    away_o      INTEGER,
    cube_log2   INTEGER,
    cube_owner  INTEGER,
    bar_x       INTEGER,
    bar_o       INTEGER,
    borne_off_x INTEGER,
    borne_off_o INTEGER,
    side_to_move INTEGER
);

CREATE TABLE analyses (
    id          INTEGER PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id),
    block_type  INTEGER NOT NULL,
    engine_name TEXT,
    payload     BLOB NOT NULL          -- BYTEA in PostgreSQL
);

CREATE TABLE matches (
    id               INTEGER PRIMARY KEY,
    match_hash       TEXT NOT NULL,     -- SHA256 format-specific
    canonical_hash   TEXT NOT NULL,     -- SHA256 cross-format
    source_file      TEXT,
    source_format    TEXT,
    player1          TEXT,
    player2          TEXT,
    match_length     INTEGER,
    event            TEXT,
    date             TEXT,
    import_timestamp TEXT
);

CREATE TABLE games (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER REFERENCES matches(id),
    game_number INTEGER,
    score_x     INTEGER,
    score_o     INTEGER,
    winner      INTEGER,
    points_won  INTEGER,
    crawford    INTEGER
);

CREATE TABLE moves (
    id          INTEGER PRIMARY KEY,
    game_id     INTEGER REFERENCES games(id),
    move_number INTEGER,
    position_id INTEGER REFERENCES positions(id),
    player      INTEGER,
    move_type   TEXT,
    dice_1      INTEGER,
    dice_2      INTEGER,
    move_string TEXT,
    -- Extracted analysis columns (avoids BLOB deserialization for queries)
    equity_diff     INTEGER,           -- x10000, equity loss of played move
    best_equity     INTEGER,           -- x10000, best move equity
    played_equity   INTEGER            -- x10000, played move equity
);
```

### Indexes

| Index                          | Purpose                          |
|--------------------------------|----------------------------------|
| positions(zobrist_hash)        | Exact position lookup            |
| positions(board_hash)          | Board-only position lookup       |
| positions(away_x, away_o)     | Match score filtering            |
| matches(canonical_hash)        | Cross-format deduplication       |
| matches(player1), matches(player2) | Player-based queries        |
| moves(game_id, move_number)   | Sequential game replay           |
| moves(equity_diff)            | Error analysis queries           |

### SQLite vs PostgreSQL

| Aspect          | SQLite                          | PostgreSQL                       |
|-----------------|----------------------------------|----------------------------------|
| Primary key     | INTEGER PRIMARY KEY              | SERIAL / BIGSERIAL               |
| Binary          | BLOB                             | BYTEA                            |
| 64-bit int      | INTEGER (native 64-bit)          | BIGINT                           |
| Upsert          | INSERT OR IGNORE                 | ON CONFLICT DO NOTHING           |
| Hash index      | Not supported (B-tree only)      | CREATE INDEX ... USING HASH      |
| Concurrency     | Single writer (even WAL mode)    | MVCC, unlimited concurrent writes|
| Partitioning    | Not supported                    | By (away_x, away_o)             |

### Backend Strategy

| Use Case                    | Backend    | Rationale                        |
|-----------------------------|------------|----------------------------------|
| Phase 1 exploration         | SQLite     | Single-file, zero config         |
| Go desktop library          | SQLite     | Embedded, no server dependency   |
| SaaS production             | PostgreSQL | Concurrent imports, multi-user   |
| Tests / CI                  | SQLite     | Fast, ephemeral                  |
| Dataset export / exchange   | SQLite     | Portable single file             |

### PostgreSQL Production Features

- **Connection pooling**: PgBouncer or pgx native pool
- **Read replicas**: separate read (user queries) from write (imports)
- **HASH indexes** on zobrist_hash, board_hash: O(1) exact lookups
- **Partitioning** by (away_x, away_o): up to 256 partitions
- **pg_trgm**: fuzzy search on player names

### Parquet Export

For Python/Jupyter analysis, positions and features can be exported from
SQLite to Parquet files. This enables direct loading into pandas/numpy
without SQL overhead, which is optimal for UMAP/PCA on millions of vectors.

## Layer 4: Query API

### Target Queries

The schema and indexes are designed to support three validated query types:

**1. Position lookup** (cross-engine comparison):
```sql
SELECT p.*, a.engine_name, a.payload
FROM positions p
JOIN analyses a ON a.position_id = p.id
WHERE p.zobrist_hash = ?
```

**2. Error analysis** (equity loss > threshold, filtered):
```sql
SELECT m.*, p.*
FROM moves m
JOIN positions p ON p.id = m.position_id
WHERE m.equity_diff > ?       -- e.g., 1000 = 0.1 equity loss
  AND p.away_x = ? AND p.away_o = ?
```

**3. Structural patterns** (prime + bar, grouped by score):
```sql
SELECT p.away_x, p.away_o, COUNT(*)
FROM positions p
WHERE p.bar_o > 0
  -- prime detection via bitboard analysis in application layer
GROUP BY p.away_x, p.away_o
```

### Interfaces

- **Go API**: `Store` interface methods, backend-agnostic
- **Python**: `sqlite3` stdlib (Phase 1), psycopg2 (production), pandas helpers
- **SaaS**: HTTP server using Go API + PGStore
- **Desktop**: Go library using SQLiteStore

## Layer 5: Visualization and Exploratory Analysis

### Feature Vector Extraction

Each position is transformed into a numeric vector for dimensionality
reduction and clustering. Components (~34-40 dimensions):

**Raw features (from BaseRecord)**:
- 24 point counts (signed: +X / -O)
- bar_x, bar_o (2 values)
- borne_off_x, borne_off_o (2 values)
- pip_x, pip_o (2 values)
- cube_log2, cube_owner (2 values)
- away_x, away_o (2 values)

**Derived features (computed)**:
- Blot count (X and O)
- Made-point count (X and O)
- Max prime length (X and O)
- Anchor count (points in opponent's home board)
- Contact/race/bearoff classification
- Pip count difference (racing advantage)

Total: ~34-40 dimensions.

All features are normalized (min-max or standard scaling) before
dimensionality reduction.

Go function: `ExtractFeatures(BaseRecord) -> []float64`
Export to numpy via Parquet or .npy file.

### Dimensionality Reduction

- **UMAP** (2D/3D): primary tool for non-linear projection, reveals clusters
- **PCA**: linear projection, variance analysis, component selection
- **t-SNE**: alternative non-linear projection for comparison

### Clustering

- **HDBSCAN**: density-based, finds clusters of varying shape and size
- **k-means**: partitional, for comparison with HDBSCAN

### Visualization Modes

**Exploration (Python/Jupyter, Phase 1)**:
- Scatter plots colored by feature (pip count, away score, contact/race)
- Cluster labeling and analysis
- Interactive plots (plotly) for drill-down
- Libraries: matplotlib, plotly, umap-learn, scikit-learn

**SaaS (production, M8)**:
- Pre-computed projections stored in database via versioned *projection runs*
- API endpoints: `/api/viz/projection`, `/api/viz/clusters`, `/api/viz/position/:id`, `/api/viz/runs`
- Dynamic filtering (by score, cube, position class, cluster) via query params
- Decoupled from feature format: API serves (x, y, cluster_id) per run, never raw features

### Projection Run Architecture

The key decoupling mechanism: the API does not know about features. It serves
pre-computed (x, y, cluster_id) coordinates associated with a **projection run**.

```
Features (Python, exploratory)     API (Go, stable)
────────────────────────────       ────────────────
features.npy → UMAP/HDBSCAN  →  projection_runs table  →  /api/viz/projection
                                 projections table
```

**Schema**:
```sql
CREATE TABLE projection_runs (
    id              BIGSERIAL PRIMARY KEY,
    method          TEXT NOT NULL,          -- 'umap_2d', 'pca_2d'
    feature_version TEXT NOT NULL,          -- 'v1.0', 'v2-no-pip'
    params          JSONB/TEXT,             -- hyperparameters
    n_points        INTEGER,
    created_at      TIMESTAMP,
    is_active       BOOLEAN DEFAULT FALSE   -- one active per method
);

CREATE TABLE projections (
    run_id      → projection_runs(id),
    position_id → positions(id),
    x, y, z (REAL), cluster_id (INTEGER)
);
```

**Lifecycle**: when features change (e.g., removing pip_diff from the vector),
a new `projection_run` is created with a new `feature_version`. The old run
stays in the database for comparison. Activating the new run is atomic
(deactivate old → activate new).

### Target Use Cases

1. **Position family clusters**: race, back game, priming game, blitz, bearing off
2. **Difficulty map**: colored by average equity loss — reveals tricky position types
3. **Player comparison**: overlay two players' positions to reveal style differences

## Import Pipeline

1. Detect format by file extension
2. Parse via specialized library (xgparser / gnubgparser / bgfparser)
3. Convert each position to BaseRecord, compute both Zobrist hashes
4. Upsert via Store interface (dialect handled by implementation)
5. Extract equity_diff from analysis blocks into moves columns
6. Deduplicate matches via canonical_hash
7. Batch transactions (e.g., 1000 records per transaction)
8. Log errors, track last imported file for resume capability

In PostgreSQL: parallel imports enabled by MVCC.

## Open Questions (to resolve during Phase 1)

- Which structural features are most discriminant for queries?
- Should derived columns (contact/race, prime length) be in the schema or computed on the fly?
- Is the 80-byte BaseRecord optimal or should it be revised for v1.0?
- Should there be a binary exchange format (GBF export from SQLite) or is SQLite the exchange format?
- UMAP hyperparameters: what n_neighbors/min_dist work best for backgammon positions?
- How many UMAP clusters emerge? Are they meaningful?
