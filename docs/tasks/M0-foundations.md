# M0 — Foundations + Validation

## Objective

Set up the repository structure, core interfaces, and database schema.
Run 4 validation experiments to test fundamental assumptions before
committing to the full implementation.

## Pre-requisites

None (first milestone).

## Sub-steps

### M0.1 — Repository Restructure

Create the Go module and package structure:

```
gbf/
  go.mod              (new module: github.com/kevung/gbf)
  gbf.go              (core types: BaseRecord, Match, Game, Move, etc.)
  zobrist.go           (context-aware + board-only hash)
  record.go            (marshal/unmarshal)
  hash.go              (match hashing: SHA256, canonical)
  store.go             (Store interface definition)
  sqlite/
    sqlite.go          (SQLiteStore implementation)
    schema.sql         (DDL)
  convert/
    xg.go, gnubg.go, bgf.go  (format converters)
  legacy/              (unchanged, reference only)
  docs/tasks/          (this directory)
  data/                (test files, BMAB dataset)
```

Port data structures from `legacy/gbf.go`. Keep legacy/ intact.

### M0.2 — Store Interface

Define the minimal `Store` interface in `store.go`:
- `UpsertPosition(ctx, BaseRecord, boardHash) (int64, error)`
- `QueryByZobrist(ctx, uint64) ([]Position, error)`
- `Close() error`

Start with 3 methods. Grow in later milestones.

### M0.3 — SQL Schema (DDL)

Write `sqlite/schema.sql` with the 5 tables from ARCHITECTURE.md:
positions, analyses, matches, games, moves.

Include all indexes defined in the architecture.

### M0.4 — SQLiteStore

Implement `SQLiteStore` in `sqlite/sqlite.go`:
- `NewSQLiteStore(path string) (*SQLiteStore, error)` — open/create DB, run DDL
- `Close() error`
- WAL mode enabled by default

### M0.5 — Board-Only Zobrist Hash

Add `ComputeBoardOnlyZobrist(BaseRecord) uint64` to `zobrist.go`.
Same PRNG seed and key tables as the context-aware hash, but skip
XOR contributions from: side_to_move, cubeLog2, cubeOwner, awayX, awayO.

### M0.6 — Port Data Structures

Copy and adapt from `legacy/gbf.go`:
- BaseRecord, AnalysisBlock, Match, Game, Move, PositionState
- CheckerPlayAnalysis, CubeDecisionAnalysis, EngineMetadata
- MoveEncoding, GameBoundary, MatchMetadata

Preserve all constants (block types, move encoding, cube actions).

### M0.7 — Validation Experiments

**Exp 1: Schema vs Target Queries**

Import 10 test XG files manually (can use legacy code as a script).
Execute the 3 target queries in raw SQL:
- Position lookup by zobrist_hash with analysis join
- Error analysis: moves WHERE equity_diff > 1000 AND away_x = 3
- Structural: positions WHERE bar_o > 0 GROUP BY away_x, away_o

Success: all 3 queries are expressible and return sensible results.

**Exp 2: Double Zobrist Relevance**

On the 10 imported files, run:
```sql
SELECT board_hash, COUNT(DISTINCT zobrist_hash) as variants
FROM positions
GROUP BY board_hash
HAVING variants > 1
```

Measure what percentage of board positions have multiple context variants.
Document the finding — it determines whether board_hash is worth indexing.

**Exp 3: UMAP Readability**

Export ~10K positions as numpy array (34 dimensions: 24 point counts +
bar_x, bar_o, borne_off_x, borne_off_o, pip_x, pip_o, cube_log2,
cube_owner, away_x, away_o). Run UMAP-2D with default parameters.
Color by pip difference and by contact/race classification.

Success: visible clusters or gradients in the scatter plot.

**Exp 4: Performance at Scale**

Import 1000 XG files. Measure:
- Total import time (seconds)
- Positions per second
- Query time for zobrist_hash lookup (average over 100 queries)

Extrapolate to 166K files. Flag if import > 24h or query > 5s.

## Files to Create/Modify

| File | Action |
|------|--------|
| `go.mod` | Create (new module) |
| `gbf.go` | Create (port from legacy) |
| `zobrist.go` | Create (port + board-only hash) |
| `record.go` | Create (port from legacy) |
| `hash.go` | Create (port from legacy) |
| `store.go` | Create (Store interface) |
| `sqlite/sqlite.go` | Create (SQLiteStore) |
| `sqlite/schema.sql` | Create (DDL) |

## Acceptance Criteria

- [ ] `go build ./...` succeeds
- [ ] `SQLiteStore` opens, creates tables, closes without error
- [ ] Board-only Zobrist: same board with different cube/score → same hash
- [ ] Board-only Zobrist: different boards → different hash
- [ ] All 4 validation experiments completed with documented results

## Tests

### Unit Tests

**[U] SQLiteStore lifecycle**
Open SQLiteStore on temp file, verify all 5 tables exist via
`SELECT name FROM sqlite_master WHERE type='table'`, close.
Success: 5 tables returned, no error.

**[U] Schema constraints**
Insert a position, then insert a duplicate zobrist_hash with
INSERT OR IGNORE. Success: no error, count unchanged.

**[U] Board-only Zobrist — same board, different context**
Create two BaseRecords: identical board/bar/borne-off, but different
CubeLog2, CubeOwner, AwayX, AwayO, SideToMove.
Success: ComputeBoardOnlyZobrist returns the same value for both.

**[U] Board-only Zobrist — different boards**
Create two BaseRecords with different point counts.
Success: ComputeBoardOnlyZobrist returns different values.

**[U] Context-aware Zobrist — preserved from legacy**
Compute Zobrist on the standard opening position using both legacy
and new code. Success: identical hash values.

### Functional Tests

**[F] Full schema creation**
Create SQLiteStore, verify all tables and indexes exist, insert one
row in each table, query it back. Success: round-trip works.

**[F] Validation Exp 1 — queries work**
Import 10 XG files, run the 3 target queries. Success: no SQL errors,
results are non-empty.

**[F] Validation Exp 3 — UMAP produces output**
Export 10K positions, run UMAP. Success: output has 2 columns, no NaN,
file saved as PNG.
