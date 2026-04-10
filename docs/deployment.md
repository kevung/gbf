# S4.6 — Deployment Guide

## Prerequisites

| Component | Version |
|---|---|
| Python | ≥ 3.11 |
| Node.js | ≥ 20 |
| DuckDB | ≥ 1.0 |
| Docker + Compose | optional, for containerised deploy |

Analysis scripts (S0–S3) must have run and produced their outputs in
`data/` before starting the dashboard.

---

## 1. Pre-computation (run once)

Builds materialised aggregation tables and tile pyramid from the raw
Parquet files produced by S0–S3.

```bash
# From repo root
python -m backend.materialise --data-dir ./data

# Skip tile pyramid if UMAP coordinates not yet available (S4.7)
python -m backend.materialise --data-dir ./data --no-tiles
```

Expected runtime: 5–15 min on 160M positions.
Outputs written to `data/materialized/`.

---

## 2. Development (local, hot-reload)

```bash
# Terminal 1 — Backend
pip install fastapi uvicorn duckdb polars
DATA_DIR=./data uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev          # Vite dev server on :5173, proxies /api → :8000
```

Open: http://localhost:5173

---

## 3. Production (single process)

```bash
# Build frontend
cd frontend && npm run build && cd ..

# Copy static build
cp -r frontend/build backend/static

# Start server
DATA_DIR=./data uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2
```

FastAPI serves the SvelteKit SPA from `/` and the API from `/api/*`.

---

## 4. Docker deployment

```bash
# First run: pre-compute materialised tables on the host
python -m backend.materialise --data-dir ./data --no-tiles

# Build and start
cd docker
docker compose up --build -d

# Check logs
docker compose logs -f

# Health check
curl http://localhost:8000/api/health
```

The data directory is mounted read-only into the container.
To update data (after re-running S0–S3 scripts), stop the container,
re-run materialise.py, then restart.

---

## 5. Running tests

```bash
pip install pytest httpx
pytest backend/tests/ -v
```

All tests use an in-memory DuckDB fixture — no Parquet data required.

### Performance test (requires running server)

```bash
# Start backend first, then:
python scripts/perf_test.py --base-url http://localhost:8000 --reps 10
```

Performance budgets (P95):

| Endpoint category | Budget |
|---|---|
| Pre-computed aggregates (heatmap, thresholds, rankings) | < 50 ms |
| Player profile | < 100 ms |
| Filtered position search | < 500 ms |
| Cube recommendation | < 20 ms |
| Map viewport points | < 400 ms |

---

## 6. Optimisation checklist

If query times exceed budget on 160M positions:

- **Position search > 500 ms**: ensure Parquet files are partitioned by
  `away_p1`/`match_phase`; add `LIMIT` + `OFFSET` on all queries.
- **Player profile > 100 ms**: verify `player_profiles_agg.parquet` was
  built by `materialise.py` and the view is pointing to it.
- **Heatmap > 50 ms**: heatmap must load from `heatmap_cells.parquet`
  (225 rows max), not the raw positions table.
- **DuckDB memory**: set `SET memory_limit = '8GB'` in `db.py` if running
  on a machine with ≥ 16 GB RAM.
- **Parquet row groups**: ensure row group size ≤ 100K rows so DuckDB
  predicate pushdown is effective.

---

## 7. Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `data` | Path to Parquet outputs from S0–S3 |
| `DB_PATH` | `$DATA_DIR/gbf.duckdb` | DuckDB persistent file |
| `CACHE_TTL` | `3600` | Seconds for `Cache-Control` headers |
| `MAX_ROWS` | `200` | Hard limit on list endpoint results |
| `STATIC_DIR` | `static` | Path to SvelteKit build output |
