# M8 — Visualization SaaS

## Objective

Build production-ready visualization components for the SaaS platform:
interactive scatter plots, cluster views, and player comparison tools.
Projections are pre-computed and served via API endpoints.

## Pre-requisites

- M5 (exploration findings: validated UMAP parameters, cluster analysis)
- M7 (PostgreSQL backend for concurrent access)

## Sub-steps

### M8.1 — Projection Storage

Store pre-computed UMAP/PCA coordinates in the database:

```sql
CREATE TABLE projections (
    id          BIGSERIAL PRIMARY KEY,
    position_id BIGINT REFERENCES positions(id),
    method      TEXT NOT NULL,       -- 'umap_2d', 'pca_2d', 'umap_3d'
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    z           REAL,                -- NULL for 2D projections
    cluster_id  INTEGER,             -- from HDBSCAN/k-means
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_proj_method ON projections(method);
CREATE INDEX idx_proj_cluster ON projections(method, cluster_id);
```

Projection computation is a batch job (Go or Python script) that runs
after import + feature extraction. Not computed on every request.

### M8.2 — API Endpoints

**GET /api/viz/projection**
Query params: method (umap_2d|pca_2d), limit, offset,
filters (away_x, away_o, cluster_id, player, position_class)

Response:
```json
{
  "points": [
    {"id": 123, "x": 0.45, "y": -1.2, "cluster_id": 3,
     "away_x": 3, "away_o": 5, "position_class": "contact"},
    ...
  ],
  "total": 150000,
  "clusters": [
    {"id": 3, "centroid_x": 0.5, "centroid_y": -1.0, "count": 8500, "label": "back game"},
    ...
  ]
}
```

**GET /api/viz/position/:id**
Returns full position detail for drill-down:
- BaseRecord decoded fields (board, bar, cube, etc.)
- All analysis blocks
- Game context (match, game number, move number)
- XGID (computed on the fly)

**GET /api/viz/player-comparison**
Query params: player1, player2, method
Returns projection coordinates for positions played by each player,
plus density statistics.

### M8.3 — Interactive Scatter Plot

Frontend component (framework TBD in SaaS project):
- Render up to 50K points using WebGL (deck.gl or similar)
- Color by: cluster_id, position_class, equity_diff, away_score
- Hover: show position summary (pip counts, cube, away scores)
- Click: drill-down to full position detail (calls /api/viz/position/:id)
- Zoom and pan

### M8.4 — Dynamic Filtering

User applies filters (away score, cube, position class) in the UI.
Two strategies depending on filter selectivity:

**Pre-filtered view** (< 50K matching points):
Query filtered projection points, render directly.

**Re-projected subset** (large filters like "all contact positions"):
Pre-compute a filtered UMAP projection and cache it. Show loading
state while computing. Cache key: sorted filter parameters hash.

### M8.5 — Player Comparison View

Overlay mode:
- Player A's positions in blue, Player B's in red
- Background: all positions in gray (10% opacity)
- Density contours per player (kernel density estimation)
- Side panel: per-cluster counts for each player

### M8.6 — Projection Cache

Pre-computed projections are expensive. Caching strategy:
- **Full dataset projection**: computed once per UMAP run, stored in projections table
- **Filtered subsets**: cached in a separate table or Redis, TTL = 1 hour
- **Re-computation trigger**: new import that adds > 10% new positions

## Files to Create/Modify

| File | Action |
|------|--------|
| `pg/schema.sql` | Add projections table |
| `viz/projection.go` | Create (batch projection computation) |
| `viz/api.go` | Create (HTTP handlers) |
| `viz/cache.go` | Create (projection cache) |

## Acceptance Criteria

- [ ] /api/viz/projection returns correct JSON for umap_2d method
- [ ] /api/viz/position/:id returns full position detail with XGID
- [ ] Scatter plot renders 10K points in < 2s client-side
- [ ] Filtering by away_score re-renders with correct subset
- [ ] Player comparison shows distinguishable distributions
- [ ] Pre-computed projections stored and retrieved correctly

## Tests

### Unit Tests

**[U] Projection storage round-trip**
Insert 100 projection points, query back by method.
Success: all points returned with correct coordinates.

**[U] API /projection — default response**
Call endpoint with method=umap_2d, limit=100.
Success: JSON response with 100 points and cluster info.

**[U] API /projection — filtered**
Call with method=umap_2d, away_x=3, away_o=5.
Success: all returned points have matching away scores.

**[U] API /position/:id — drill-down**
Query a known position_id.
Success: response includes decoded board, analysis, XGID.

**[U] API /player-comparison**
Call with two known players.
Success: response contains points for both players.

### Functional Tests

**[F] Scatter plot performance**
Serve 10K projection points to a frontend. Measure render time.
Success: < 2s from API response to rendered canvas.

**[F] Filter then drill-down**
Filter by away_x=3, click on a point, view position detail.
Success: drill-down shows correct position matching the filter.

**[F] Player comparison — visual**
Serve comparison for 2 players with > 1K positions each.
Success: density contours are visibly different.

**[F] Cache invalidation**
Compute a projection, import new files, verify cache is flagged stale.
Success: stale flag set, re-computation produces updated projection.

**[F] Full workflow**
Import 1000 files → extract features → compute UMAP → store projections
→ serve via API → render scatter plot → filter → drill-down.
Success: entire chain works end-to-end.
