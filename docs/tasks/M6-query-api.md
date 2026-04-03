# M6 — Query API ✅

## Objective

Build the complete Go query API and Python helpers that support the 3
validated target queries. Ensure queries perform well on the full BMAB dataset.

## Pre-requisites

M1 (import pipeline, Store interface with basic methods), M9 (derived columns).

## Sub-steps

### M6.1 — Position Lookup Queries ✅

Updated `Store` interface and `SQLiteStore`:

```go
QueryByZobrist(ctx, hash uint64)   ([]PositionWithAnalyses, error)
QueryByBoardHash(ctx, hash uint64) ([]PositionWithAnalyses, error)
```

`PositionWithAnalyses` embeds `Position` (with M9 derived columns) plus
`Analyses []AnalysisBlock`. `QueryByZobrist` now returns `PositionWithAnalyses`
instead of the previous plain `Position`; existing callers are compatible via
struct embedding.

`QueryByBoardHash` returns all context variations (different cube/score) of
the same board layout.

### M6.2 — Match Score Queries ✅

```go
QueryByMatchScore(ctx, awayX, awayO int) ([]PositionSummary, error)
```

`PositionSummary` is a lightweight struct (no base_record blob) suitable for
large result sets. Uses -1 as wildcard for awayX or awayO.

Uses `idx_positions_class_away` composite index.

### M6.3 — Feature-based Queries ✅

```go
type QueryFilter struct {
    PosClass, AwayX, AwayO             *int
    PipDiffMin, PipDiffMax             *int
    PrimeLenXMin, PrimeLenOMin         *int
    CubeLog2, CubeOwner                *int
    BarXMin, BarOMin                   *int
    EquityDiffMin                      *int  // triggers JOIN with moves
    Limit                              int
}

QueryByFeatures(ctx, f QueryFilter) ([]PositionWithMoves, error)
```

SQL is built dynamically in `BuildFeatureQuery` (query.go). All filter values
use `?` placeholders — no SQL injection possible. Setting `EquityDiffMin`
triggers a `JOIN moves` with `DISTINCT` on the positions side.

Convenience helper: `gbf.Ptr(v int) *int` for inline filter construction.

### M6.4 — Aggregation Queries ✅

```go
QueryScoreDistribution(ctx)         ([]ScoreDistribution, error)
QueryPositionClassDistribution(ctx) (map[int]int, error)
```

`ScoreDistribution` includes `AwayX, AwayO, Count, AvgEquityDiff (×10000)`.

### M6.5 — Python Helper ✅

File: `python/gbf_query.py`

```python
class GBFQuery:
    def __init__(self, path: str)          # SQLite path; PG deferred to M7
    def by_zobrist(self, hash_value: int) -> pd.DataFrame
    def by_board_hash(self, hash_value: int) -> pd.DataFrame
    def by_match_score(self, away_x=-1, away_o=-1) -> pd.DataFrame
    def by_features(self, pos_class=None, away_x=None, ...) -> pd.DataFrame
    def error_analysis(self, min_equity_diff=500, **filters) -> pd.DataFrame
    def score_distribution(self) -> pd.DataFrame
    def class_distribution(self) -> pd.DataFrame
```

Returns pandas DataFrames. `error_analysis` joins positions with moves and
adds `equity_diff_f` (float equity = equity_diff / 10000).

### M6.6 — Migration Tool ✅

`cmd/migrate-v1/main.go` — applies M9 schema changes to existing databases:

1. `ALTER TABLE positions ADD COLUMN` (idempotent — skips if already exists)
2. `CREATE INDEX IF NOT EXISTS` (all 4 M9 indexes)
3. `BackfillDerivedColumns` (cursor-based, batch-safe)

Usage: `go run ./cmd/migrate-v1/ -db path/to/gbf.db`

## Files Created/Modified

| File | Status |
|------|--------|
| `store.go` | ✅ Extended Store interface + new types |
| `gbf.go` | ✅ AnalysisBlock.EngineName added |
| `query.go` | ✅ BuildFeatureQuery (dynamic SQL builder) |
| `sqlite/sqlite.go` | ✅ 5 new query methods + updated scanPositions |
| `python/gbf_query.py` | ✅ GBFQuery class, 7 methods |
| `cmd/migrate-v1/main.go` | ✅ Migration tool for existing databases |
| `m6_test.go` | ✅ 11 unit tests |

## New Types

| Type | Description |
|------|-------------|
| `PositionWithAnalyses` | Position + `[]AnalysisBlock` |
| `PositionWithMoves` | Position + `[]MoveRow` |
| `PositionSummary` | Lightweight position (no blob) |
| `MoveRow` | Move record from DB with nullable equities |
| `QueryFilter` | Filter spec for QueryByFeatures |
| `ScoreDistribution` | Aggregated count + avg_equity_diff per score |

## Acceptance Criteria

- [x] All 3 target queries return correct results on test data
- [x] QueryByZobrist on 1.57M-row DB: ~21 µs (M9 benchmark)
- [x] QueryByFeatures with 3 filters: ~35 µs (pip_diff range, M9 benchmark)
- [x] Aggregation queries: complete in < 1s on 1.57M positions
- [x] Python helper returns correct DataFrames (validated on real DB)

## Tests (all pass in -short)

**[U] QueryByZobristWithAnalyses** — insert position, look it up, check struct ✅
**[U] QueryByBoardHash** — same board at 2 scores, returns 2 rows ✅
**[U] QueryByMatchScore** — exact (3,5) filter, wildcard (-1,-1) ✅
**[U] QueryByFeaturesEmpty** — no filter, limit=10 respected ✅
**[U] QueryByFeaturesPosClass** — all rows match requested class ✅
**[U] QueryByFeaturesEquityDiff** — JOIN triggered, returned rows satisfy ≥ 500 ✅
**[U] QueryByFeaturesPipDiff** — BETWEEN [-20, 20] respected ✅
**[U] QueryScoreDistribution** — counts > 0, valid away scores ✅
**[U] QueryPositionClassDistribution** — all 3 classes present after import ✅

## Python Validation (1.57M positions, gbf_m5.db)

```
class_distribution:
  contact: 1,345,906  (85.9%)
  race:      115,959   (7.4%)
  bearoff:   105,596   (6.7%)

score_distribution top entry: away_x=11, away_o=11 → 61,996 positions

by_match_score(1,1): 17,904 DMP positions

error_analysis(min=2000): top errors include 24/23 and bar/22 moves
```

## Notes

**AnalysisBlock.EngineName**: added to the existing struct in `gbf.go` to
avoid redefining the type. The field is empty when AnalysisBlock is read
from binary format; populated when read from the DB.

**Migration for existing DBs**: `NewSQLiteStore` runs DDL with
`CREATE TABLE IF NOT EXISTS` — it does NOT add columns to existing tables.
Use `cmd/migrate-v1` for databases created before M9.
