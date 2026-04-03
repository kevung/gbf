# M1 — Import XG

## Objective

Build a working import pipeline that reads a single XG file, converts it
to GBF records, and stores all data (positions, analyses, match structure)
in the SQLite database.

## Pre-requisites

M0 (foundations: Store interface, SQLiteStore, data structures).

## Sub-steps

### M1.1 — Integrate xgparser

Add `github.com/kevung/xgparser` to `go.mod`. Create `convert/xg.go`
by porting from `legacy/convert_xg.go`. Adapt to use new package
structures (non-legacy BaseRecord, Match, etc.).

### M1.2 — Convert XG Match to GBF Records

Implement `ConvertXGMatch(xgMatch) -> Match`:
- Convert each position from XG relative coordinates to GBF absolute
- Compute both Zobrist hashes (context-aware + board-only)
- Compute pip counts, validate integrity (15 checkers per player)
- Extract checker play and cube decision analysis blocks

### M1.3 — Implement UpsertPosition

In `SQLiteStore`:
- Compute board_hash from BaseRecord
- INSERT OR IGNORE into positions table
- Extract indexed columns from BaseRecord (pip, away, cube, bar, borne-off)
- Return position ID (existing or newly inserted)

### M1.4 — Implement UpsertMatch / Game / Move

In `SQLiteStore`:
- `UpsertMatch`: INSERT OR IGNORE on canonical_hash, store metadata
- `InsertGame`: INSERT game boundary with scores, winner, Crawford
- `InsertMove`: INSERT move with position_id, move_type, dice, move_string
- Extract analysis columns: `equity_diff`, `best_equity`, `played_equity`
  from CheckerPlayAnalysis block (first move = best, played = last matching)
- `AddAnalysis`: INSERT analysis block with engine_name and raw payload

### M1.5 — End-to-end Import

Implement `ImportFile(store Store, path string) error`:
- Detect format (here, .xg only)
- Parse with xgparser
- Convert to Match
- Call store methods to persist everything
- Return error with context on failure

### M1.6 — Error Logging

- Log parse errors with file path and position index
- Log conversion errors (e.g., integrity check failures)
- Continue on non-fatal errors (skip bad positions, log warning)
- Fatal errors (can't open file, can't parse header) return error

## Files to Create/Modify

| File | Action |
|------|--------|
| `go.mod` | Add xgparser dependency |
| `convert/xg.go` | Create (port from legacy) |
| `import.go` | Create (ImportFile function) |
| `sqlite/sqlite.go` | Add Upsert/Insert methods |

## Acceptance Criteria

- [ ] `ImportFile(store, "data/test.xg")` succeeds
- [ ] All 5 tables populated with correct data
- [ ] Zobrist hashes match legacy computation
- [ ] Analysis blocks stored with correct engine_name
- [ ] equity_diff column populated on moves with analysis

## Tests

### Unit Tests

**[U] XG position conversion**
Convert a known XG position (standard opening). Verify: board array,
bar, borne-off, cube, away scores match expected values.
Success: all fields match.

**[U] XG analysis conversion**
Convert a move with checker play analysis (3 candidates). Verify:
equity, win_rate, gammon_rate, move encoding for each candidate.
Success: all values within 1 unit of expected (rounding tolerance).

**[U] UpsertPosition — insert then dedup**
Insert a position, get ID. Insert same position again (same zobrist_hash).
Success: same ID returned, COUNT(*) = 1 in positions table.

**[U] UpsertMatch — canonical hash dedup**
Import a match, get ID. Import same match again.
Success: same ID, COUNT(*) = 1 in matches table.

**[U] equity_diff extraction**
Import a move with checker play analysis. Verify equity_diff column
equals the difference between best move equity and played move equity.
Success: value matches expected (x10000 scale).

### Functional Tests

**[F] Import test.xg — full pipeline**
Import `data/test.xg`. Query: count matches, games, moves, positions.
Success: counts > 0, matches count = 1, games count >= 1.

**[F] Import idempotent**
Import `data/test.xg` twice. Query counts after each import.
Success: all counts identical after second import (dedup works).

**[F] Import corrupt file**
Attempt to import a truncated or empty file.
Success: error returned (not panic), error message includes file path.

**[F] Zobrist consistency with legacy**
Import `data/test.xg` with both legacy and new code. Compare all
zobrist_hash values.
Success: 100% match.
