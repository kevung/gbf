# M7 — PostgreSQL Backend

## Objective

Implement `PGStore` for production SaaS deployment with concurrent writes,
connection pooling, and HASH indexes. Validate data consistency between
SQLite and PostgreSQL backends.

## Pre-requisites

M6 (complete query API on SQLiteStore).

## Sub-steps

### M7.1 — PGStore Implementation

File: `pg/pg.go`

```go
type PGStore struct {
    pool *pgxpool.Pool
}

func NewPGStore(dsn string) (*PGStore, error)
```

- Use `pgx` (github.com/jackc/pgx/v5) for native PostgreSQL driver
- Connection pooling via pgxpool (configurable pool size)
- Run DDL on first connection (CREATE TABLE IF NOT EXISTS)
- Implement all `Store` interface methods

### M7.2 — Dialect Adaptation

Differences handled internally by PGStore:

| Operation | SQLite | PostgreSQL |
|-----------|--------|------------|
| Upsert | INSERT OR IGNORE | INSERT ... ON CONFLICT DO NOTHING |
| Auto-ID | INTEGER PRIMARY KEY | BIGSERIAL PRIMARY KEY |
| Binary | BLOB | BYTEA |
| Parameter | ? | $1, $2, ... |

All SQL is internal to each Store implementation — no shared SQL strings.

### M7.3 — HASH Indexes

After table creation, create HASH indexes for exact lookups:

```sql
CREATE INDEX idx_positions_zobrist USING HASH (zobrist_hash);
CREATE INDEX idx_positions_board USING HASH (board_hash);
```

Keep B-tree indexes for range queries (away_x, away_o, equity_diff).

### M7.4 — Concurrency Tests

Validate that PGStore handles concurrent access:
- Multiple goroutines importing different files simultaneously
- Multiple goroutines querying while imports are running
- Same file imported by 2 goroutines concurrently (dedup under contention)

Use Go's `-race` flag and test with 10+ concurrent workers.

### M7.5 — Data Migration (SQLite to PostgreSQL)

Implement `MigrateStore(src Store, dst Store) error`:
- Read all positions from src, upsert into dst
- Read all matches/games/moves, insert into dst
- Read all analyses, insert into dst
- Batch operations (1000 rows per transaction)
- Progress tracking

Validate: `SELECT COUNT(*) FROM <table>` matches on both backends.

### M7.6 — Optional Partitioning

If query patterns after M5 show heavy filtering by away scores:

```sql
CREATE TABLE positions (
    ...
) PARTITION BY RANGE (away_x);
```

Partition by away_x buckets (0-3, 4-7, 8-11, 12-15) or by (away_x, away_o)
combination. Evaluate query performance improvement.

Only implement if M5 findings justify it.

## Files to Create/Modify

| File | Action |
|------|--------|
| `go.mod` | Add pgx dependency |
| `pg/pg.go` | Create (PGStore) |
| `pg/pg_test.go` | Create (requires test PostgreSQL instance) |
| `migrate.go` | Create (MigrateStore) |

## Implementation Notes (completed 2026-04-03)

- `pg/pg.go`: full `PGStore` implementing `Store` + `Batcher` via `pgxpool`
- `pg/schema.sql`: PostgreSQL DDL with BIGSERIAL, BYTEA, HASH/B-tree indexes
- `migrate_store.go`: `MigrateStore(ctx, src *sql.DB, dst Store, batchSize int)` using posIDMap
- `docker-compose.yml`: PostgreSQL 16 with tmpfs, health check, port 5432
- `toPgParams()`: converts `?` → `$N` for reusing `BuildFeatureQuery`
- `TruncateAll()`: test helper for isolated integration tests

## Acceptance Criteria

- [x] PGStore passes the same test suite as SQLiteStore
- [x] 10 concurrent UpsertPosition goroutines — no races (verified with -race)
- [x] Migration from SQLite to PG produces identical row counts (TestMigrateStoreSQLiteToPG)
- [x] HASH index on board_hash, B-tree on zobrist_hash for ON CONFLICT
- [ ] HASH index lookup < 10ms on 3M+ positions (requires full dataset load)

## Tests

### Unit Tests

**[U] PGStore schema creation**
Connect to test database, create PGStore, verify all 5 tables exist
via `pg_catalog.pg_tables`.
Success: all tables present, PGStore closes cleanly.

**[U] PGStore upsert — insert then dedup**
Insert a position, get ID. Insert same zobrist_hash again.
Success: same ID, count = 1.

**[U] Concurrent upsert — same position**
2 goroutines insert the same position simultaneously.
Success: no error, no deadlock, count = 1.

**[U] Concurrent upsert — different positions**
10 goroutines each insert 100 different positions.
Success: total count = 1000, no errors, race detector clean.

### Functional Tests

**[F] Parallel import — 100 files, 10 workers**
Import 100 XG files with 10 goroutines.
Success: all data consistent, no duplicates, no deadlocks.
Compare position count with sequential import of same 100 files.

**[F] Migration — SQLite to PG**
Import 1000 files into SQLite, migrate to PG.
Success: COUNT(*) identical on all 5 tables.

**[F] Query equivalence**
Run the 3 target queries on both SQLite and PG with same data.
Success: identical result sets (ignoring row order).

**[F] HASH index performance**
Run 1000 zobrist lookups on PG with 3M+ positions.
Measure p50 and p99.
Success: p99 < 10ms.

**[F] Read during write**
One goroutine imports files, another runs queries continuously.
Success: queries always return consistent results (no partial transactions visible).
