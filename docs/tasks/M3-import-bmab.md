# M3 — Import BMAB (Progressive)

## Objective

Import the BMAB dataset progressively — one region at a time — with
monitoring, error recovery, and performance tracking. Validate that the
system handles ~33K files per region without issues before scaling up.

## Pre-requisites

M2 (multi-format import with dedup).

## Sub-steps

### M3.1 — Directory Traversal

Implement `ImportDirectory(store Store, dir string, opts ImportOpts) (Report, error)`:
- Recursive walk of directory tree
- Filter by supported extensions (.xg for BMAB)
- Sort files for deterministic import order
- `ImportOpts`: batch size, max errors, resume file path

### M3.2 — Transaction Batching

Group inserts into transactions of N files (default: 100).
- Begin transaction before batch
- Import N files
- Commit transaction
- On error within batch: rollback, log failed files, continue with next batch

### M3.3 — Progress Tracking

Report during import:
- Files processed / total
- Positions imported / second
- Matches imported
- Duplicate positions skipped
- Errors encountered
- Estimated time remaining

Output progress every N files (e.g., every 1000) to stdout or logger.

### M3.4 — Error Recovery

Maintain a journal file (`import_journal.txt`):
- One line per successfully imported file
- On restart, skip already-imported files
- Failed files logged in `import_errors.txt` with error message

This enables resume after interruption without re-importing.

### M3.5 — Import Report

At completion, produce a summary:
- Total files processed / skipped / failed
- Total matches, games, positions, analyses
- Unique positions (by zobrist_hash)
- Unique boards (by board_hash)
- Duplicate rate (positions that already existed)
- Total time, average positions/second
- Database file size

### M3.6 — Progressive Region Import

Import order:
1. asia/ (~33,342 files) — first region, validates at scale
2. europe/ (~33,343 files) — check dedup across regions
3. Remaining regions one by one

After each region:
- Run import report
- Check query performance (zobrist lookup)
- Check database size growth rate

## Files to Create/Modify

| File | Action |
|------|--------|
| `import.go` | Add ImportDirectory, batching, journal |
| `report.go` | Create (import report generation) |

## Acceptance Criteria

- [ ] Import of asia/ (~33K files) completes without crash
- [ ] Journal file enables resume after simulated interruption
- [ ] Import report shows plausible numbers (positions > files * ~100)
- [ ] Zobrist lookup on full-region DB returns in < 100ms
- [ ] Database size is proportional to position count

## Tests

### Unit Tests

**[U] Batch transaction — commit**
Import 10 files in a batch of 5. Verify: 2 transactions committed,
all data present.
Success: counts match expected.

**[U] Batch transaction — rollback on error**
Import 10 files where file #7 is corrupt, batch size = 5.
Verify: first batch (5 files) committed, second batch rolled back,
file #7 logged in errors.
Success: 5 files imported, 5 skipped, 1 error logged.

**[U] Journal — skip already imported**
Write 5 file paths to journal, then run import on 10 files.
Verify: only 5 new files imported.
Success: total imported = 5, journal has 10 entries after.

### Functional Tests

**[F] Import 1000 BMAB files**
Import first 1000 files from asia/. Measure time and positions/second.
Success: completes without error, report generated.

**[F] Resume after interruption**
Import 500 files, stop, restart. Verify: no duplicates, 500 new files
imported on second run.
Success: total positions unchanged vs single uninterrupted import.

**[F] Import full region (asia/)**
Import all ~33K files from asia/. Generate report.
Success: report shows > 3M positions, < 24h total time, < 100ms
zobrist lookup on resulting DB.

**[F] Cross-region dedup**
Import asia/ then europe/. Check: some board_hash overlap between regions.
Success: shared positions exist (same opening positions across regions).

**[F] Import report accuracy**
Verify report totals match actual SQL counts:
`SELECT COUNT(*) FROM positions` = reported positions, etc.
Success: all counts match exactly.
