# M8 — Visualization SaaS

## Objective

Build production-ready visualization backend for the SaaS platform:
projection storage, HTTP API, and batch computation pipeline.
Frontend (WebGL scatter plot) is deferred to the SaaS project.

## Pre-requisites

- M5 (exploration findings: validated UMAP parameters, cluster analysis)
- M7 (PostgreSQL backend for concurrent access)

## Architecture: Projection Runs

The API is **decoupled from the feature format** via versioned projection runs.
When features change (e.g., removing pip_diff), a new run is created and
activated — the API only serves (x, y, cluster_id) per run.

```
Features (Python, exploratory)       API (Go, stable)
────────────────────────────────     ────────────────────
features.npy → UMAP/HDBSCAN    →   projection_runs table → /api/viz/projection
                                    projections table
```

## Sub-steps

### M8.1 — Projection Storage ✅

Two new tables in both SQLite and PostgreSQL schemas:

```sql
CREATE TABLE projection_runs (
    id              BIGSERIAL PRIMARY KEY,
    method          TEXT NOT NULL,          -- 'umap_2d', 'pca_2d', 'umap_3d'
    feature_version TEXT NOT NULL,          -- 'v1.0', 'v2-no-pip'
    params          JSONB/TEXT,             -- hyperparameters
    n_points        INTEGER,
    created_at      TIMESTAMP,
    is_active       BOOLEAN DEFAULT FALSE   -- one active per method
);

CREATE TABLE projections (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT REFERENCES projection_runs(id),
    position_id BIGINT REFERENCES positions(id),
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    z           REAL,                       -- NULL for 2D
    cluster_id  INTEGER                     -- from HDBSCAN
);
```

Store interface extended with 6 methods:
- `CreateProjectionRun`, `ActivateProjectionRun`, `InsertProjectionBatch`
- `ActiveProjectionRun`, `QueryProjections`, `QueryClusterSummary`
- Optional: `PositionByID` (for drill-down, not in Store interface)

### M8.2 — API Endpoints ✅

`viz/api.go` — 4 HTTP handlers using Go 1.22+ path patterns:

**GET /api/viz/projection**
- Query params: `method`, `cluster_id`, `away_x`, `away_o`, `pos_class`, `limit`, `offset`
- Returns: `{points, clusters, run, total}`

**GET /api/viz/clusters**
- Query params: `method`
- Returns: `[{cluster_id, count, centroid_x, centroid_y}]`

**GET /api/viz/position/{id}**
- Returns: decoded board, analyses, position attributes
- Uses optional `PositionByID` interface on the store

**GET /api/viz/runs**
- Lists active projection runs for known methods

### M8.3 — Import Pipeline ✅

**Go CLI**: `cmd/import-projections/main.go`
- Reads CSV (position_id, x, y [, z] [, cluster_id])
- Creates projection_run, batch-inserts points, activates run

**Python pipeline**: `python/compute_projections.py`
- Reads features.npy + position_ids.npy
- Runs UMAP or PCA + HDBSCAN clustering
- Outputs CSV for import-projections

### M8.4–M8.6 — Deferred

- **M8.4 Interactive Scatter Plot**: deferred to SaaS frontend project (deck.gl/WebGL)
- **M8.5 Player Comparison**: needs query-by-player in Store (future)
- **M8.6 Projection Cache**: not needed — pre-filtered views via SQL are fast enough

## Files Created/Modified

| File | Action |
|------|--------|
| `store.go` | Extended: 6 projection methods + 5 new types |
| `sqlite/schema.sql` | Added projection_runs + projections tables |
| `pg/schema.sql` | Added projection_runs + projections tables (JSONB, BIGSERIAL) |
| `sqlite/sqlite.go` | Added: PositionByID, projection methods |
| `pg/pg.go` | Added: PositionByID, projection methods, TruncateAll updated |
| `viz/api.go` | Created: Server, RegisterRoutes, 4 handlers |
| `cmd/import-projections/main.go` | Created: CSV import CLI |
| `python/compute_projections.py` | Created: UMAP/PCA → CSV pipeline |
| `m8_test.go` | Created: 11 tests (5 storage + 6 HTTP API) |

## Acceptance Criteria

- [x] /api/viz/projection returns correct JSON for umap_2d method
- [x] /api/viz/position/{id} returns full position detail with analyses
- [x] /api/viz/clusters returns per-cluster counts and centroids
- [x] Filtering by cluster_id returns correct subset
- [x] Pre-computed projections stored and retrieved correctly
- [x] Run activation deactivates previous run of same method
- [x] Empty state (no active run) returns empty JSON, not error
- [ ] Frontend scatter plot renders 10K points in < 2s (deferred to SaaS)
- [ ] Player comparison endpoint (deferred)

## Tests (11/11 pass)

### Storage Tests (5)

| Test | Description |
|------|-------------|
| `TestProjectionStorageRoundTrip` | Create run → insert point → query back |
| `TestActiveProjectionRun_NoRun` | Returns nil when no active run |
| `TestActivateProjectionRun_Deactivation` | New run deactivates old one |
| `TestQueryClusterSummary` | Counts and centroids correct for 2 clusters |
| `TestQueryProjections_FilteredByCluster` | Filter returns matching points only |

### HTTP API Tests (6)

| Test | Description |
|------|-------------|
| `TestAPIProjection_Default` | 5 points, 2 clusters, correct JSON structure |
| `TestAPIProjection_FilteredByCluster` | cluster_id=0 returns 3 points |
| `TestAPIProjection_NoActiveRun` | Empty response, no error |
| `TestAPIClusters` | 2 cluster summaries |
| `TestAPIPositionDetail` | Position detail with analysis |
| `TestAPIRuns` | Lists 1 active run |
