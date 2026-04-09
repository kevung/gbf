# S4.2 — Dashboard Application Architecture

Web application architecture for the GBF mining study dashboard.
Serves the 7 views defined in S4.1 on top of 160M-position Parquet data.

---

## Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| **Backend** | Python / FastAPI | Same ecosystem as analysis pipeline; DuckDB Python driver mature |
| **Database** | DuckDB (embedded) | Queries Parquet files directly; no ETL; columnar; fast aggregations |
| **Frontend** | Svelte 5 + SvelteKit + TypeScript | Compiled, minimal runtime; reactive stores replace Context |
| **Charts** | LayerCake (Svelte) + D3.js (heatmap) | LayerCake for radar/line/bar; D3 for fine-grained heatmap SVG |
| **Board rendering** | SVG (Svelte component) | Resolution-independent; CSS-animatable; no canvas boilerplate |
| **Trajectory map** | deck.gl (WebGL) | Handles millions of points; ScatterplotLayer + PathLayer built-in |
| **Styling** | Tailwind CSS | Utility-first; no runtime overhead; purge unused classes |
| **Deployment** | Docker (single image) | Portable; static frontend served by FastAPI `StaticFiles` |

---

## Architecture Layers

```
┌──────────────────────────────────────────────────────────┐
│  Layer 5 — Browser (SvelteKit SPA)                       │
│  8 pages · board component · deck.gl map                 │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP/JSON  REST
┌────────────────────────▼─────────────────────────────────┐
│  Layer 4 — FastAPI application                           │
│  /api/* routers · Pydantic schemas · response caching    │
└────────────────────────┬─────────────────────────────────┘
                         │ Python DuckDB driver
┌────────────────────────▼─────────────────────────────────┐
│  Layer 3 — DuckDB (embedded)                             │
│  Views over Parquet · materialised tables (DuckDB file)  │
└──────────┬─────────────────────────────┬─────────────────┘
           │ SELECT on .parquet          │ SELECT on .duckdb
┌──────────▼──────────┐      ┌───────────▼─────────────────┐
│  Layer 2 — Parquet  │      │  Layer 2 — Materialisations  │
│  (S0–S3 outputs)    │      │  (pre-computed aggregations) │
│  read-only          │      │  heatmap_cells.parquet       │
│  ~160M rows         │      │  player_profiles_agg.parquet │
│                     │      │  cluster_summaries.parquet   │
│                     │      │  cube_thresholds_agg.parquet │
└──────────┬──────────┘      │  rankings.parquet            │
           │                 │  temporal_series.parquet     │
┌──────────▼──────────┐      │  tile_pyramid/ (PNG)         │
│  Layer 1 — Batch    │      └─────────────────────────────┘
│  materialise.py     │
│  (offline, run once)│
└─────────────────────┘
```

---

## Directory Structure

```
gbf-dashboard/
  backend/
    main.py               # FastAPI app entry point
    config.py             # DATA_DIR, DB_PATH, CACHE_TTL env vars
    db.py                 # DuckDB connection pool (thread-local)
    routers/
      players.py          # /api/players/*
      heatmap.py          # /api/heatmap/*
      positions.py        # /api/positions/*
      cube.py             # /api/cube/*
      stats.py            # /api/stats/*
      clusters.py         # /api/clusters/*
      map.py              # /api/map/* + /api/trajectories/*
    schemas/              # Pydantic response models
    materialise.py        # Offline batch pre-computation script
  frontend/
    src/
      pages/              # 8 page components
      components/
        Board.svelte        # S4.3 board component
        CubeHeatmap.svelte  # D3 heatmap grid
        RadarChart.svelte   # LayerCake radar
        TrajectoryMap.svelte # deck.gl map
      api/                # typed fetch wrappers
      store/              # Svelte stores (filters, selected player)
    public/
      tiles/              # pre-rendered tile pyramid (zoom 0–7)
  docker/
    Dockerfile
    docker-compose.yml
  data/                   # symlink or mount to actual Parquet outputs
```

---

## Data Flow

### Read-only path (live queries, positions / players)

```
Browser filter form
  → GET /api/positions?player=X&away_p1=3&error_min=0.08
  → FastAPI router: build WHERE clause with bind params
  → DuckDB: SELECT ... FROM positions_enriched/*.parquet WHERE ...
  → Pydantic model → JSON response
  → Svelte table component
```

### Pre-computed path (heatmaps, rankings, thresholds)

```
materialise.py (run once after S0–S3)
  → DuckDB: GROUP BY / aggregate Parquet files
  → write heatmap_cells.parquet, player_profiles_agg.parquet, ...

Browser heatmap page load
  → GET /api/heatmap/cube-error
  → DuckDB: SELECT * FROM heatmap_cells.parquet   (< 5 ms)
  → D3 renders 15×15 grid
```

### Tile path (trajectory map, zoom 0–7)

```
materialise.py
  → read positions_with_hash.parquet (UMAP x/y coordinates)
  → generate PNG tiles at zoom 0–7 (density heatmap, pillow)
  → save to frontend/public/tiles/{z}/{x}/{y}.png

Browser map, low zoom
  → deck.gl BitmapLayer loads tiles from /tiles/{z}/{x}/{y}.png
  → no API call; fully static
```

---

## DuckDB Schema

DuckDB reads Parquet files directly via `read_parquet()` views.
One persistent `.duckdb` file holds only pre-aggregated tables.

```sql
-- Registered views (no copy, query-time read)
CREATE OR REPLACE VIEW positions AS
  SELECT * FROM read_parquet('data/positions_enriched/*.parquet');

CREATE OR REPLACE VIEW clusters AS
  SELECT * FROM read_parquet('data/position_clusters.parquet');

CREATE OR REPLACE VIEW player_profiles AS
  SELECT * FROM read_parquet('data/player_profiles.parquet');

CREATE OR REPLACE VIEW matches AS
  SELECT * FROM read_parquet('data/matches.parquet');

-- Materialised tables (written by materialise.py)
CREATE TABLE heatmap_cells AS ...;         -- 225 rows max
CREATE TABLE player_profiles_agg AS ...;   -- one row per player
CREATE TABLE cluster_summaries AS ...;     -- one row per cluster
CREATE TABLE cube_thresholds_agg AS ...;   -- (away_p1, away_p2, cube)
CREATE TABLE rankings AS ...;              -- sorted, pre-ranked
CREATE TABLE temporal_series AS ...;       -- per year
```

---

## API Design Principles

- **Stateless**: no server-side session; all state in URL params or client
- **Pagination**: all list endpoints accept `limit` (max 200) + `offset`
- **Bind params**: all user input via DuckDB `?` placeholders (no injection)
- **Response caching**: FastAPI `@lru_cache` on pre-aggregated endpoints;
  `Cache-Control: max-age=3600` header on static aggregates
- **Content-type**: `application/json` everywhere except tile PNGs
- **Error format**: `{"error": "message", "code": 400}` on all failures

---

## Performance Budget

| Query type | Target | Strategy |
|---|---|---|
| Heatmap load | < 50 ms | Pre-computed table (225 rows) |
| Player profile | < 100 ms | Pre-computed table |
| Rankings list | < 50 ms | Pre-computed, sorted |
| Position search (filtered) | < 500 ms | DuckDB column pruning + Parquet predicate pushdown |
| Position search (unfiltered) | < 2 s | Warn user; suggest filters |
| Cube thresholds | < 20 ms | Pre-computed, single row lookup |
| Trajectory fetch | < 300 ms | Spatial index on UMAP coords |
| Map tiles | < 20 ms | Static PNG, served by browser cache |
| Map points (viewport) | < 400 ms | DuckDB bounding-box filter on x, y columns |

---

## Materialise Script (`materialise.py`)

Run once offline after all S0–S3 scripts complete.

```
Steps:
  1. Connect DuckDB, register Parquet views
  2. Build heatmap_cells    (GROUP BY away_p1, away_p2, match_length)
  3. Build player_profiles_agg  (JOIN profiles + clusters + rankings)
  4. Build cluster_summaries    (GROUP BY cluster_id)
  5. Build cube_thresholds_agg  (JOIN S3.3 thresholds + Kazaross TP)
  6. Build rankings             (pre-sorted, pre-ranked)
  7. Build temporal_series      (GROUP BY year, decision_type)
  8. Export all as Parquet to data/materialized/
  9. Generate tile pyramid      (UMAP x/y → density raster → PNG tiles)
 10. Write manifest.json        (timestamps, row counts, data checksums)
```

Estimated runtime on 160M positions: 5–15 min (one-time).

---

## Docker Deployment

```dockerfile
FROM python:3.11-slim
WORKDIR /app

# Backend dependencies
COPY backend/requirements.txt .
RUN pip install fastapi uvicorn duckdb polars lightgbm

# Frontend build (pre-built via SvelteKit static adapter)
COPY frontend/build/ static/

# App + data
COPY backend/ backend/
COPY data/ data/          # Parquet files + materialized/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
services:
  dashboard:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data:ro     # mount Parquet data read-only
    environment:
      - DATA_DIR=/app/data
      - DB_PATH=/app/data/gbf.duckdb
```

Frontend static files served by FastAPI `StaticFiles("/", directory="static")`.
Single-container deployment; no separate web server required.

---

## Development Workflow

```
# 1. Run materialise script once
python backend/materialise.py --data-dir ./data

# 2. Start backend (hot-reload)
uvicorn backend.main:app --reload --port 8000

# 3. Start frontend dev server (SvelteKit + Vite)
cd frontend && npm run dev      # port 5173, proxies /api → 8000

# 4. Build for production
cd frontend && npm run build    # SvelteKit static adapter → build/
cp -r frontend/build backend/static/

# 5. Docker build
docker compose up --build
```
