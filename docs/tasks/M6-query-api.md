# M6 — Query API

## Objective

Build the complete Go query API and Python helpers that support the 3
validated target queries. Ensure queries perform well on the full
BMAB dataset.

## Pre-requisites

M1 (import pipeline, Store interface with basic methods).

## Sub-steps

### M6.1 — Position Lookup Queries

Add to `Store` interface and implement in `SQLiteStore`:

```go
QueryByZobrist(ctx, hash uint64) ([]PositionWithAnalyses, error)
QueryByBoardHash(ctx, hash uint64) ([]PositionWithAnalyses, error)
```

`PositionWithAnalyses` bundles a position with all its associated
analysis blocks and engine names. The board_hash variant returns all
context variations (different cube/score) of the same board layout.

### M6.2 — Match Score Queries

```go
QueryByMatchScore(ctx, awayX, awayO int) ([]PositionSummary, error)
```

Returns positions filtered by away scores. Supports:
- Exact match: awayX=3, awayO=5
- Wildcard: awayX=-1 means "any"

Uses the composite index on (away_x, away_o).

### M6.3 — Feature-based Queries

```go
type QueryFilter struct {
    AwayX, AwayO       *int
    PipXMin, PipXMax   *int
    PipOMin, PipOMax   *int
    CubeLog2           *int
    CubeOwner          *int
    BarXMin            *int
    BarOMin            *int
    BorneOffXMin       *int
    EquityDiffMin      *int    // on moves table
    Limit              int
}

QueryByFeatures(ctx, filter QueryFilter) ([]PositionWithMoves, error)
```

Builds SQL dynamically from non-nil filter fields. Joins with moves
table when equity_diff filter is set.

This powers the error analysis target query:
```go
filter := QueryFilter{
    AwayX: ptr(3), AwayO: ptr(5),
    EquityDiffMin: ptr(1000),  // > 0.1 equity loss
    Limit: 100,
}
```

### M6.4 — Aggregation Queries

```go
type ScoreDistribution struct {
    AwayX, AwayO int
    Count        int
    AvgEquityDiff float64
}

QueryScoreDistribution(ctx) ([]ScoreDistribution, error)
QueryPositionClassDistribution(ctx) (map[string]int, error)
```

These support statistical analysis:
- How many positions per match score combination?
- Average equity loss per match score
- Position class distribution (contact/race/bearoff)

### M6.5 — Python Helpers

File: `python/gbf_query.py`

Thin wrapper around sqlite3 / psycopg2:

```python
class GBFQuery:
    def __init__(self, db_path_or_dsn: str)
    def by_zobrist(self, hash: int) -> pd.DataFrame
    def by_board_hash(self, hash: int) -> pd.DataFrame
    def by_match_score(self, away_x: int, away_o: int) -> pd.DataFrame
    def by_features(self, **filters) -> pd.DataFrame
    def score_distribution(self) -> pd.DataFrame
    def error_analysis(self, min_equity_diff: int, **filters) -> pd.DataFrame
```

Returns pandas DataFrames. Auto-detects SQLite vs PostgreSQL from
connection string.

## Files to Create/Modify

| File | Action |
|------|--------|
| `store.go` | Extend Store interface |
| `sqlite/sqlite.go` | Implement query methods |
| `query.go` | QueryFilter type, SQL builder |
| `python/gbf_query.py` | Create Python helper |
| `python/setup.py` | Create (minimal package) |

## Acceptance Criteria

- [ ] All 3 target queries return correct results on test data
- [ ] Zobrist lookup on full-region DB < 100ms
- [ ] Feature-based query with 3 filters returns results in < 1s
- [ ] Aggregation queries complete in < 5s on full-region DB
- [ ] Python helper returns correct DataFrames with proper column names

## Tests

### Unit Tests

**[U] QueryByZobrist — known position**
Import test.xg, note a zobrist_hash. Query it.
Success: returns exactly 1 position with correct analysis.

**[U] QueryByBoardHash — multiple contexts**
Import a position that appears at different match scores.
Query by board_hash.
Success: returns multiple positions with different away_x/away_o.

**[U] QueryByMatchScore — filtering**
Import several matches. Query awayX=3, awayO=5.
Success: all returned positions have away_x=3, away_o=5.

**[U] QueryByFeatures — composite filter**
Query with EquityDiffMin=500, AwayX=3.
Success: all returned moves have equity_diff >= 500 and away_x=3.

**[U] QueryByFeatures — empty filter**
Query with all filters nil, limit=10.
Success: returns 10 arbitrary positions.

**[U] SQL injection safety**
Query with adversarial string values in filters.
Success: no SQL error, parameterized queries used.

### Functional Tests

**[F] Target query 1 — position lookup**
Import test.xg. Pick a position. Query by zobrist_hash. Verify analysis
blocks match what xgparser produced.
Success: equity, win_rate values match.

**[F] Target query 2 — error analysis**
Import test.xg. Query moves with equity_diff > 0 (any error).
Success: results contain position details and move info.

**[F] Target query 3 — structural patterns**
Import test.xg. Query positions with bar_o > 0, group by away scores.
Success: results grouped correctly, counts are plausible.

**[F] Performance — zobrist lookup on BMAB region**
Run 100 random zobrist lookups on a region-sized DB (~3M positions).
Measure p50 and p99 latency.
Success: p99 < 100ms.

**[F] Python helper — round trip**
Use gbf_query.py to query test.xg database.
Success: DataFrame has correct columns, values match Go API output.

**[F] Python helper — error analysis**
Use `error_analysis(min_equity_diff=1000, away_x=3)`.
Success: DataFrame contains only rows matching the criteria.
