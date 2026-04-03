# M2 — Import Multi-format

## Objective

Extend the import pipeline to support GnuBG (SGF, MAT) and BGBlitz
(BGF, TXT) formats. Implement cross-format deduplication so the same
match imported from different sources produces a single match entry.

## Pre-requisites

M1 (XG import pipeline working).

## Sub-steps

### M2.1 — Integrate gnubgparser

Add `github.com/kevung/gnubgparser` to `go.mod`. Create `convert/gnubg.go`
by porting from `legacy/convert_gnubg.go`.

Key conversion details:
- GnuBG uses absolute coordinates for both players
- Player 0 maps directly, Player 1 is mirrored (23 - i)
- Bar is at index 24 in GnuBG
- Handle control moves: setboard, setdice, setcube, setcubepos

### M2.2 — Integrate bgfparser

Add `github.com/kevung/bgfparser` to `go.mod`. Create `convert/bgf.go`
by porting from `legacy/convert_bgf.go`.

Key conversion details:
- BGBlitz uses player-relative indexing (0=24-pt, 23=1-pt)
- Reverse to GBF absolute (0=1-pt, 23=24-pt)
- Green=X, Red=O; Bar: BGF[24]=X, BGF[25]=O
- Handle cube-disguised-as-move pattern

### M2.3 — Format Auto-detection

In `ImportFile(store, path)`, detect format by extension:

| Extension | Format   | Parser       |
|-----------|----------|--------------|
| .xg       | XG       | xgparser     |
| .sgf      | GnuBG    | gnubgparser  |
| .mat      | GnuBG    | gnubgparser  |
| .bgf      | BGBlitz  | bgfparser    |
| .txt      | BGBlitz  | bgfparser    |

Return error for unknown extensions.

### M2.4 — Cross-format Deduplication

Use `ComputeCanonicalMatchHash` (from legacy/hash.go) which hashes:
- First 10 dice per game (format-independent)
- Normalized + sorted player names
- Game count and match length

When importing, check canonical_hash before inserting a new match.
If a match with the same canonical_hash exists, link new analyses
to existing positions but don't duplicate the match/game structure.

### M2.5 — Same Match, Different Formats

Verify that importing the same match from XG and SGF:
- Produces the same canonical_hash
- Results in 1 match entry (not 2)
- Both format-specific match_hash values are stored (as separate match rows
  or as metadata on the same row — TBD based on exact dedup strategy)

## Files to Create/Modify

| File | Action |
|------|--------|
| `go.mod` | Add gnubgparser, bgfparser |
| `convert/gnubg.go` | Create (port from legacy) |
| `convert/bgf.go` | Create (port from legacy) |
| `import.go` | Add format detection switch |
| `hash.go` | Port canonical hash from legacy |

## Acceptance Criteria

- [ ] Import of .sgf, .mat, .bgf, .txt files succeeds
- [ ] Format auto-detection works for all 5 extensions
- [ ] Same match from XG and SGF produces same canonical_hash
- [ ] No duplicate match entries after importing same match in 2 formats
- [ ] Positions from different formats share board_hash when applicable

## Tests

### Unit Tests

**[U] Format detection**
Call format detection with paths: test.xg, test.sgf, test.mat, test.bgf,
test.txt, test.unknown.
Success: correct format for known extensions, error for unknown.

**[U] GnuBG position conversion**
Convert a known GnuBG position (standard opening from SGF).
Success: board array matches expected GBF representation.

**[U] BGBlitz position conversion**
Convert a known BGBlitz position.
Success: board array matches expected GBF representation.

**[U] Canonical hash — same match, different format**
Compute canonical hash for the same match parsed from XG and from SGF.
Success: hashes are identical.

### Functional Tests

**[F] Import all sample formats**
Import all files in data/: test.xg, test.sgf, test.mat, test.txt.
Success: no errors, all tables populated.

**[F] Cross-format dedup**
Import test.xg then test.sgf (same match).
Success: matches count = 1, canonical_hash appears once.

**[F] Board-hash overlap across formats**
Import test.xg and test.sgf. Query positions that share the same
board_hash but came from different source files.
Success: at least some shared board positions found.

**[F] All data/ files import without error**
Import every file in data/ (excluding bmab directory).
Success: zero errors, import report shows all files processed.
