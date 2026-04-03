# M0 — Foundations + Validation

## Objective

Set up the repository structure, core interfaces, and database schema.
Run 4 validation experiments to test fundamental assumptions before
committing to the full implementation.

## Pre-requisites

None (first milestone).

## Sub-steps

### M0.1 — Repository Restructure ✅

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

### M0.2 — Store Interface ✅

Define the minimal `Store` interface in `store.go`:
- `UpsertPosition(ctx, BaseRecord, boardHash) (int64, error)`
- `QueryByZobrist(ctx, uint64) ([]Position, error)`
- `Close() error`

Start with 3 methods. Grow in later milestones.

### M0.3 — SQL Schema (DDL) ✅

Write `sqlite/schema.sql` with the 5 tables from ARCHITECTURE.md:
positions, analyses, matches, games, moves.

Include all indexes defined in the architecture.

### M0.4 — SQLiteStore ✅

Implement `SQLiteStore` in `sqlite/sqlite.go`:
- `NewSQLiteStore(path string) (*SQLiteStore, error)` — open/create DB, run DDL
- `Close() error`
- WAL mode enabled by default

### M0.5 — Board-Only Zobrist Hash ✅

Add `ComputeBoardOnlyZobrist(BaseRecord) uint64` to `zobrist.go`.
Same PRNG seed and key tables as the context-aware hash, but skip
XOR contributions from: side_to_move, cubeLog2, cubeOwner, awayX, awayO.

### M0.6 — Port Data Structures ✅

Copy and adapt from `legacy/gbf.go`:
- BaseRecord, AnalysisBlock, Match, Game, Move, PositionState
- CheckerPlayAnalysis, CubeDecisionAnalysis, EngineMetadata
- MoveEncoding, GameBoundary, MatchMetadata

Preserve all constants (block types, move encoding, cube actions).

### M0.7 — Validation Experiments ✅

**Exp 1: Schema vs Target Queries** ✅

10 XG files imported via `convert/xg.go` + `cmd/validate/main.go`.
Results (2026-04-03, 1835 distinct positions):
- Q1 positions+analyses join: 1835 rows — OK
- Q2 blunders (equity_diff>1000, away_x=3): 62 rows — OK
- Q3 bar_o>0 GROUP BY away_x,away_o: 10 groups — OK

**Conclusion**: all 3 target queries expressible and return sensible results. ✓

**Exp 2: Double Zobrist Relevance** ✅

On 10 imported files (1835 distinct positions):
- Board positions with multiple context variants: 21
- Percentage of board_hash with >1 zobrist_hash: 1.1%

**Conclusion**: multi-context variants confirmed at ~1% rate. board_hash index
is WORTH keeping — same board layout can appear with different score/cube
context, making board_hash a useful secondary lookup key.

**Exp 3: UMAP Readability** ✅

1835 positions exported as 35-feature CSV (24 point counts + bar + borne_off
+ pip + cube + away + side_to_move). UMAP-2D run with n_neighbors=15,
min_dist=0.1, random_state=42 via `cmd/validate/umap_viz.py`.

Results:
- Clear gradient by pip difference (left=opponent ahead, right=X ahead)
- Race positions (pip_diff > 30) form a distinct cluster on right side
- Contact positions form a separate cluster on left, more spread

**Conclusion**: visible clusters and gradients confirmed. 35-feature vector
captures discriminant structure. UMAP visualization is viable for M5. ✓

**Exp 4: Performance at Scale** ✅

1000 BMAB files (asia region) imported:
- Files imported: 1000 / 1000 (0 failures)
- Move-positions processed: 363 738
- Distinct positions in DB: 239 138 (34% dedup rate)
- Total time: 52.8s
- Positions/second: ~6 900
- Avg zobrist lookup: 8.5µs (well under 5s limit)
- Extrapolated time for 166K files: ~2h27m ✓ (< 24h limit)

**Conclusion**: import performance within bounds. No architectural changes
needed before M1. Transaction batching (M3) will further improve throughput.

## Files to Create/Modify

| File | Action | Status |
|------|--------|--------|
| `go.mod` | Create (new module) | ✅ |
| `gbf.go` | Create (port from legacy) | ✅ |
| `zobrist.go` | Create (port + board-only hash) | ✅ |
| `record.go` | Create (port from legacy) | ✅ |
| `hash.go` | Create (port from legacy) | ✅ |
| `store.go` | Create (Store interface) | ✅ |
| `sqlite/sqlite.go` | Create (SQLiteStore) | ✅ |
| `sqlite/schema.sql` | Create (DDL) | ✅ |
| `convert/xg.go` | Create (XG converter) | ✅ |
| `cmd/validate/main.go` | Create (validation script) | ✅ |
| `cmd/validate/umap_viz.py` | Create (UMAP script) | ✅ |

## Acceptance Criteria

- [x] `go build ./...` succeeds
- [x] `SQLiteStore` opens, creates tables, closes without error
- [x] Board-only Zobrist: same board with different cube/score → same hash
- [x] Board-only Zobrist: different boards → different hash
- [x] All 4 validation experiments completed with documented results

## Tests

### Unit Tests

**[U] SQLiteStore lifecycle** ✅
Open SQLiteStore on temp file, verify all 5 tables exist via
`SELECT name FROM sqlite_master WHERE type='table'`, close.
Success: 5 tables returned, no error.

**[U] Schema constraints** ✅
Insert a position, then insert a duplicate zobrist_hash with
INSERT OR IGNORE. Success: no error, count unchanged.

**[U] Board-only Zobrist — same board, different context** ✅
Create two BaseRecords: identical board/bar/borne-off, but different
CubeLog2, CubeOwner, AwayX, AwayO, SideToMove.
Success: ComputeBoardOnlyZobrist returns the same value for both.

**[U] Board-only Zobrist — different boards** ✅
Create two BaseRecords with different point counts.
Success: ComputeBoardOnlyZobrist returns different values.

**[U] Context-aware Zobrist — preserved from legacy** ✅
Compute Zobrist on the standard opening position using both legacy
and new code. Success: identical hash values.

### Functional Tests

**[F] Full schema creation** ✅
Create SQLiteStore, verify all tables and indexes exist, insert one
row in each table, query it back. Success: round-trip works.

**[F] Validation Exp 1 — queries work** ✅
Import 10 XG files, run the 3 target queries. Success: no SQL errors,
results are non-empty. (2026-04-03: 1835 positions, all 3 queries returned
non-empty results.)

**[F] Validation Exp 3 — UMAP produces output** ✅
Export positions, run UMAP via `cmd/validate/umap_viz.py`. Success: output
has 2 columns, no NaN, PNG saved. (2026-04-03: 1835 positions, visible
pip-diff gradient and contact/race cluster separation confirmed.)
