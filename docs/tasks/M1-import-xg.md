# M1 — Import XG ✅

## Objective

Build a working import pipeline that reads a single XG file, converts it
to GBF records, and stores all data (positions, analyses, match structure)
in the SQLite database.

## Pre-requisites

M0 (foundations: Store interface, SQLiteStore, data structures).

## Sub-steps

### M1.1 — Integrate xgparser ✅

`github.com/kevung/xgparser v1.3.0` added to `go.mod`.

### M1.2 — Convert XG Match to GBF Records ✅

`convert/xg.go` ported from `legacy/convert_xg.go` with a critical bug fix:
XG Checkers array is 1-indexed (Checkers[0]=opponent bar, Checkers[1-24]=points,
Checkers[25]=active player bar). Legacy code assumed 0-indexed, causing
checker count overflows on positions with checkers at point 24. Fixed in
the new converter.

### M1.3 — Implement UpsertPosition ✅

Already implemented in M0. Returns existing ID on duplicate zobrist_hash.

### M1.4 — Implement UpsertMatch / Game / Move ✅

Added to `sqlite/sqlite.go`:
- `UpsertMatch`: INSERT OR IGNORE on canonical_hash
- `InsertGame`: INSERT with scores, winner, Crawford flag
- `InsertMove`: INSERT with position_id, dice, move_string, equity columns
- `AddAnalysis`: INSERT OR IGNORE on (position_id, block_type) UNIQUE constraint

`equity_diff`, `best_equity`, `played_equity` populated by matching the
played move encoding against analysis candidates in `findPlayedEquity`.

### M1.5 — End-to-end Import ✅

- `gbf.Importer.ImportMatch` — format-agnostic, takes a parsed Match
- `convert.ImportFile` — detects format (.xg), parses, calls ImportMatch

### M1.6 — Error Logging ✅

Non-fatal errors (invalid positions, bad checker counts) are logged and
skipped. Fatal errors (file not found, parse failure) return error.
`Importer.Logger *log.Logger` field: pass nil to suppress logging.

## Files Created/Modified

| File | Action | Status |
|------|--------|--------|
| `go.mod` | Add xgparser dependency | ✅ (M0.7) |
| `convert/xg.go` | Create (port from legacy + bug fix) | ✅ |
| `convert/import.go` | Create (ImportFile) | ✅ |
| `import.go` | Create (Importer, ImportMatch) | ✅ |
| `sqlite/sqlite.go` | Add UpsertMatch/InsertGame/InsertMove/AddAnalysis | ✅ |
| `sqlite/schema.sql` | Add UNIQUE(position_id,block_type) on analyses | ✅ |
| `store.go` | Extend Store interface (4 new methods) | ✅ |
| `gbf.go` | Add BestEquity/PlayedEquity/EquityDiff to Move | ✅ |
| `sqlite/m1_test.go` | Unit tests for new Store methods | ✅ |
| `convert/import_test.go` | Functional tests for ImportFile | ✅ |

## Acceptance Criteria

- [x] `ImportFile(store, "data/test.xg")` succeeds
- [x] All 5 tables populated with correct data
- [x] Zobrist hashes stable (recomputed == stored, round-trip tested)
- [x] Analysis blocks stored with correct engine_name ("eXtreme Gammon")
- [x] equity_diff column populated on moves with analysis

## Tests

### Unit Tests

**[U] UpsertMatch — canonical hash dedup** ✅
`TestUpsertMatchDedup`: same canonical_hash → same ID returned.

**[U] InsertGame — round-trip** ✅
`TestInsertGame`: gameID > 0 returned.

**[U] InsertMove — equity columns populated** ✅
`TestInsertMoveEquity`: equity_diff, best_equity, played_equity verified in DB.

**[U] AddAnalysis — dedup via UNIQUE constraint** ✅
`TestAddAnalysis`: duplicate insert silently ignored, COUNT = 1.

**[U] XG position conversion** ✅
`TestXGPositionConversion`: Zobrist stable across PositionToBaseRecord +
marshal/unmarshal round-trip.

**[U] equity_diff extraction** ✅
`TestEquityDiffExtraction`: EquityDiff >= 0, BestEquity matches analysis[0].

### Functional Tests

**[F] Import test.xg — full pipeline** ✅
`TestImportTestXG`: matches=1, games>0, moves>0, positions>0. All 5 tables
have > 0 rows.

**[F] Import idempotent** ✅
`TestImportIdempotent`: matches COUNT = 1 after 2 imports.

**[F] Import corrupt file** ✅
`TestImportCorruptFile`: error returned for empty .xg file, no panic.

**[F] Unsupported format** ✅
`TestImportUnsupportedFormat`: error returned for .bgf extension.

## Notes

**XG Checkers encoding bug**: the legacy converter assumed `Checkers[0-23]`
are points 0-23 and `Checkers[24]` is the opponent's bar. The actual encoding
is 1-indexed: `Checkers[0]` = opponent bar, `Checkers[1-24]` = points 1-24,
`Checkers[25]` = active player bar. This was masked in BMAB files where
mid-game positions rarely have checkers at point 24 (Checkers[24]). Fixed
in `convert/xg.go` — loop now iterates 1..24 with gbfIndex = i-1 (PlayerX)
or 24-i (PlayerO).
