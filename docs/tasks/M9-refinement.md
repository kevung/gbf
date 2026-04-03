# M9 — Phase 2 Refinement

## Objective

Optimize the database schema, indexes, and record format based on
findings from Phase 1 exploration (M5). Add derived columns, tune
performance, and finalize the GBF v1.0 specification.

## Pre-requisites

M5 (exploration findings and synthesis report).

## Sub-steps

### M9.1 — Add Derived Columns

Based on M5 findings, add columns to the positions table for the most
discriminant features identified during exploration. Candidates:

```sql
ALTER TABLE positions ADD COLUMN position_class INTEGER;  -- 0=contact, 1=race, 2=bearoff
ALTER TABLE positions ADD COLUMN prime_length_x INTEGER;
ALTER TABLE positions ADD COLUMN prime_length_o INTEGER;
ALTER TABLE positions ADD COLUMN blot_count_x INTEGER;
ALTER TABLE positions ADD COLUMN blot_count_o INTEGER;
ALTER TABLE positions ADD COLUMN anchor_count_x INTEGER;
ALTER TABLE positions ADD COLUMN anchor_count_o INTEGER;
ALTER TABLE positions ADD COLUMN pip_diff INTEGER;
```

Backfill existing rows with a migration script:
```go
func BackfillDerivedColumns(store Store) error
```

Only add columns that M5 showed are frequently used for filtering or
that significantly improve query performance.

### M9.2 — Optimize Indexes

Based on observed query patterns from M5/M6:
- Add composite indexes for common filter combinations
- Drop indexes that are never used (check pg_stat_user_indexes)
- Consider partial indexes (e.g., only positions with equity_diff > 0)

Example candidates:
```sql
CREATE INDEX idx_positions_class_away ON positions(position_class, away_x, away_o);
CREATE INDEX idx_moves_error ON moves(equity_diff) WHERE equity_diff > 500;
```

### M9.3 — BaseRecord Revision (v1.0)

Evaluate whether the 80-byte BaseRecord should change:

**Consider removing**:
- PipX/PipO (4 bytes) — derivable from point counts + bar
- Zobrist (8 bytes) — stored as DB column, not needed in record
- Padding (14 bytes) — reduce if no extension planned

**Consider adding**:
- Board-only Zobrist (8 bytes) — currently computed but not in record

**Decision criteria**:
- If the base record is primarily a DB BLOB, compactness matters
- If it's also an exchange/wire format, alignment matters
- Phase 1 data will show how much storage the padding wastes at scale

Document the decision in SPEC.md. If changed, implement a v0.3→v1.0
migration tool.

### M9.4 — Query Documentation

File: `docs/queries.md`

Document standard queries with full SQL examples:

1. Position lookup (by zobrist, by board_hash)
2. Error analysis (equity_diff threshold + filters)
3. Structural patterns (prime + bar, anchors, blots)
4. Score-state analysis (positions at specific away scores)
5. Player analysis (all positions by a player, grouped by type)
6. Statistical aggregation (equity loss distribution, gammon rates)
7. Visualization queries (projection with filters)

Each query includes:
- Description and use case
- SQL (both SQLite and PostgreSQL dialect if different)
- Expected performance characteristics
- Go API equivalent

### M9.5 — Performance Benchmarks

Benchmark suite measuring:

**Import throughput**:
- Files per second (single worker)
- Files per second (10 workers, PostgreSQL only)
- Positions per second

**Query latency** (on full BMAB dataset):
- Zobrist lookup: p50, p95, p99
- Board hash lookup: p50, p95, p99
- Feature-filtered query (3 filters, limit 100): p50, p95, p99
- Aggregation query: total time
- Projection query (10K points): total time

**Storage efficiency**:
- Bytes per position (total DB size / position count)
- Index overhead percentage
- BLOB vs extracted column space ratio

Document results and compare against target requirements from README.md.

## Files to Create/Modify

| File | Action |
|------|--------|
| `migrate_v1.go` | Create (backfill derived columns, optional format migration) |
| `docs/queries.md` | Create (query documentation) |
| `benchmark_test.go` | Create (performance benchmarks) |
| `SPEC.md` | Update (v1.0 finalization or "unchanged" decision) |
| `sqlite/schema.sql` | Update (derived columns, new indexes) |
| `pg/schema.sql` | Update (same) |

## Acceptance Criteria

- [ ] Derived columns added and backfilled on full BMAB dataset
- [ ] Query performance meets or exceeds README.md targets
- [ ] SPEC.md v1.0 finalized (either revised or confirmed as-is)
- [ ] Query documentation covers all standard use cases
- [ ] Benchmark results documented

## Tests

### Unit Tests

**[U] Derived column correctness**
Backfill 100 known positions. Compare position_class, prime_length,
blot_count with expected values computed by ExtractFeatures.
Success: all values match.

**[U] Composite index used**
Run EXPLAIN QUERY PLAN on a position_class + away query.
Success: index idx_positions_class_away is used.

**[U] Partial index used**
Run EXPLAIN on moves WHERE equity_diff > 500.
Success: partial index idx_moves_error is used (if created).

### Functional Tests

**[F] Backfill full region**
Run BackfillDerivedColumns on a full-region database (~3M positions).
Verify: no NULL values in new columns, all values in valid range.
Success: backfill completes, spot-check 100 random positions correct.

**[F] Query performance regression**
Run the 3 target queries before and after adding derived columns + indexes.
Success: query times improve or stay the same (no regression).

**[F] Benchmark suite passes**
Run all benchmarks on BMAB dataset.
Success: zobrist lookup p99 < 100ms, import > 1000 positions/sec,
filtered query < 1s.

**[F] Query documentation accuracy**
Execute every SQL example from docs/queries.md against test database.
Success: all queries return non-empty results, no SQL errors.

**[F] Format migration (if BaseRecord changed)**
Convert 1000 v0.3 records to v1.0 format. Verify: Zobrist hashes
recomputed correctly, integrity checks pass, round-trip works.
Success: 100% records convert without error.
