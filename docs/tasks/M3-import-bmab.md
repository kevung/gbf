# M3 — Import BMAB (Progressive) ✅

## Objective

Import the BMAB dataset progressively — one region at a time — with
monitoring, error recovery, and performance tracking. Validated at scale
with 5,000 files (15% of one region).

## Pre-requisites

M2 (multi-format import with dedup).

## Sub-steps

### M3.1 — Directory Traversal ✅

`ImportDirectory(ctx, store, dir, opts)` in `import_dir.go`:
- Recursive walk via `filepath.WalkDir`
- Filters `.xg`, `.sgf`, `.mat`, `.bgf` extensions
- Sorted for deterministic import order
- `ImportOpts.Limit` caps total files (used for progressive testing)

### M3.2 — Transaction Batching ✅

`SQLiteStore` extended with `BeginBatch/CommitBatch/RollbackBatch` via the
`Batcher` interface. SQLiteStore stores an active `*sql.Tx`; all Store
methods use `conn()` which returns the tx when active, or the raw DB.

`ImportDirectory` checks `store.(Batcher)` and wraps each batch of N files
in one transaction. Default batch size: 100.

Performance gain: ~11,300 pos/s vs ~6,900 pos/s without explicit batching
(~64% improvement).

### M3.3 — Progress Tracking ✅

Progress logged every `ProgressInterval` files (default: 1000):
```
progress: 2000/5000 files | 1063663 positions | 11689 pos/s | ~2m16s remaining
```

`ProgressEvent` struct with FilesDone, FilesTotal, Positions, Rate,
Elapsed, Remaining. `ImportOpts.ProgressFn` callback for programmatic use.

### M3.4 — Error Recovery ✅

Journal file (`JournalPath`): one line per successfully imported file.
On restart, paths already in the journal are skipped.
Error log (`ErrorLogPath`): one line per failed file with error message.
Both files are appended atomically with buffered writers and flushed
after each batch.

### M3.5 — Import Report ✅

`DirectoryReport` struct: FilesTotal, FilesImported, FilesSkipped,
FilesFailed, Matches, Games, Moves, Positions, Errors, Elapsed, AvgRate.

CLI tool `cmd/bmab-import/main.go` prints a formatted summary.

### M3.6 — Progressive Region Import ✅

BMAB dataset structure: flat directory `bmab-2025-06-23/` with
166,713 files prefixed by region name:
- asia\_\*: 33,342 files
- europe\_\*: 33,343 files
- middle-east,...\_\*: 33,342 files
- north-america\_\*: 33,343 files
- oceania\_\*: 33,343 files

Validated with 5,000 files (asia prefix, sorted first):

| Metric | Value |
|--------|-------|
| Files imported | 5,000 |
| Matches | 5,000 |
| Games | 42,414 |
| Positions (upsert calls) | 2,586,550 |
| Distinct positions (DB) | 1,567,461 |
| Dedup rate | ~40% |
| Avg rate | 11,334 pos/s |
| Elapsed | 3m48s |
| DB size | 867.6 MB |
| Zobrist lookup (1.5M rows) | **14 µs** (criterion: < 100ms) |

Extrapolation to full 166K files: ~110M positions, ~87h at current rate.
(Batching and WAL optimizations in place; full import feasible.)

## Files Created/Modified

| File | Action | Status |
|------|--------|--------|
| `import_dir.go` | Create (ImportDirectory, ImportOpts, DirectoryReport, Batcher) | ✅ |
| `sqlite/sqlite.go` | Add BeginBatch/CommitBatch/RollbackBatch, conn() | ✅ |
| `cmd/bmab-import/main.go` | Create (CLI import tool) | ✅ |
| `m3_test.go` | Create (unit + functional tests) | ✅ |

## Acceptance Criteria

- [x] ImportDirectory of 5,000 files completes without crash
- [x] Journal file enables resume (verified: 0 re-imports on second run)
- [x] Import report shows plausible numbers (528 pos/file on average)
- [x] Zobrist lookup on 1.5M-row DB: **14 µs** (< 100ms ✓)
- [x] DB size proportional to position count (~554 bytes/position)

## Tests

### Unit Tests (run by default)

**[U] Batch commit** ✅
`TestBatchCommit`: 10 files in batches of 5, all data committed to DB.

**[U] Journal skip** ✅
`TestJournalSkip`: 5 files imported first; second run of 10 skips the 5.

**[U] Error handling** ✅
`TestBatchErrorHandling`: injected error on file 3; 9 imported, 1 failed,
error log has 1 entry.

### Functional Tests (skip in short mode)

Run with `-timeout 120s`, skipped by `go test -short`:

**[F] Import 1000 files** ✅
`TestImport1000BMab`: 1,000 asia files → 528,026 positions, ~12,000 pos/s.

**[F] Resume after interruption** ✅
`TestResumeAfterInterruption`: import 500, restart → 0 new imports,
DB position count unchanged.

**[F] Report accuracy** ✅
`TestImportReportAccuracy`: report matches/games/moves match SQL counts.

## Notes

**Dedup rate**: ~40% of position upsert calls return existing IDs. This is
expected: the standard opening and common mid-game positions appear in many
BMAB matches.

**Throughput bottleneck**: the `INSERT OR IGNORE` + `SELECT id` pattern in
`UpsertPosition` issues 2 queries per position. A future optimization could
cache recently seen Zobrist hashes to avoid the SELECT on duplicate hits.

**Large functional tests**: skipped by `go test -short`. Run explicitly:
```
go test -run TestImport1000BMab -timeout 120s
go test -run TestResumeAfterInterruption -timeout 120s
go test -run TestImportReportAccuracy -timeout 60s
```
