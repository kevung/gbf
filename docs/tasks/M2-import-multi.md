# M2 — Import Multi-format ✅

## Objective

Extend the import pipeline to support GnuBG (SGF, MAT) and BGBlitz
(BGF, TXT) formats. Implement cross-format deduplication so the same
match imported from different sources produces a single match entry.

## Pre-requisites

M1 (XG import pipeline working).

## Sub-steps

### M2.1 — Integrate gnubgparser ✅

`github.com/kevung/gnubgparser v1.2.0` added to `go.mod`.
`convert/gnubg.go` created: `ParseSGFFile`, `ParseMATFile`, and all
internal conversion helpers ported from `legacy/convert_gnubg.go`.

### M2.2 — Integrate bgfparser ✅

`github.com/kevung/bgfparser v1.2.0` added to `go.mod`.
`convert/bgf.go` created: `ParseBGFFile`, BGBlitz text position parsing
(`parseBGFTextFile`), and all internal helpers from `legacy/convert_bgf.go`.

### M2.3 — Format Auto-detection ✅

`convert/import.go` extended to detect format by extension:

| Extension | Format   | Parser       |
|-----------|----------|--------------|
| .xg       | XG       | xgparser     |
| .sgf      | GnuBG    | gnubgparser  |
| .mat      | GnuBG    | gnubgparser  |
| .bgf      | BGBlitz  | bgfparser    |
| .txt      | BGBlitz  | bgfparser    |

Unknown extensions return an error.

### M2.4 — Cross-format Deduplication ✅

`ComputeCanonicalMatchHash` (in `hash.go`) uses the first 10 dice per game
plus sorted player names, match length, and game count — identical across
formats. `UpsertMatch` uses `INSERT OR IGNORE` on `canonical_hash`, so
a second import of the same match (different format) returns the existing
match ID without inserting a new row.

### M2.5 — Cross-format Verification ✅

`charlot1-charlot2_7p_2025-11-08-2305.sgf` and `.mat` are the same match.
Canonical hashes are identical; importing both yields 1 match entry.

## Files Created/Modified

| File | Action | Status |
|------|--------|--------|
| `go.mod` | Add gnubgparser v1.2.0, bgfparser v1.2.0 | ✅ |
| `convert/gnubg.go` | Create (port from legacy + adapt to convert pkg) | ✅ |
| `convert/bgf.go` | Create (port from legacy + adapt to convert pkg) | ✅ |
| `convert/helpers.go` | Create (roundToInt32, roundToUint16 shared helpers) | ✅ |
| `convert/import.go` | Extend with SGF/MAT/BGF/TXT format support | ✅ |
| `convert/m2_test.go` | Unit + functional tests for M2 | ✅ |

## Acceptance Criteria

- [x] Import of .sgf, .mat, .txt files succeeds
- [x] Format auto-detection works for all 5 extensions
- [x] Same match from SGF and MAT produces same canonical_hash
- [x] No duplicate match entries after importing same match in 2 formats
- [x] Positions from different formats share board_hash when applicable

## Tests

### Unit Tests

**[U] Format detection** ✅
`TestFormatDetection`: all known extensions detected, unknown returns error.

**[U] GnuBG position conversion** ✅
`TestGnuBGPositionConversion`: parse test.sgf, verify 15 checkers per
player and stable Zobrist hash.

**[U] MAT position conversion** ✅
`TestMATPositionConversion`: parse test.mat, verify PositionToBaseRecord
succeeds.

**[U] Canonical hash — same match, different format** ✅
`TestCanonicalHashCrossFormat`: charlot1-charlot2 SGF vs MAT → identical
canonical hash.

### Functional Tests

**[F] Import all sample formats** ✅
`TestImportAllFormats`: test.sgf, test.mat, test.txt all import without
error; positions > 0.

**[F] Cross-format dedup** ✅
`TestCrossFormatDedup`: import charlot1-charlot2.sgf then .mat → 1 match
in DB (canonical_hash dedup via INSERT OR IGNORE).

**[F] Board-hash overlap across formats** ✅
`TestBoardHashOverlapCrossFormat`: SGF import produces 193 positions;
MAT import of same match deduplicates to 0 new positions via UpsertPosition.

**[F] All data/ files import without error** ✅
`TestImportAllDataFiles`: all 6 test files (xg, sgf×2, mat×2, txt) import
with zero errors.

## Notes

**BGBlitz .txt format**: Unlike BGF/SGF/MAT which contain full matches,
the .txt format stores a single position + analysis. It is wrapped in a
synthetic 1-game match for storage.

**No .bgf test file available**: .bgf is a binary format (no sample file
in data/). Parser is wired up; tested via format detection only.
