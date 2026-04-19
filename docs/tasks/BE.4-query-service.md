# BE.4 — Backend Query Service

## Objective

Serve the interactive barycentric views with a small Python HTTP
service backed by DuckDB + polars over the local parquet files. The
existing Go `viz/api.go` is backed by a `gbf.Store` (SQLite) that does
not carry the barycentric data, and pushing barycentric rows into
SQLite for 16 M rows is premature; a thin read-only Python endpoint is
the right shape for now.

## Pre-requisites

- BE.1 (`barycentric_v2.parquet`), BE.2 (`bootstrap_cells.parquet`),
  BE.3 (`cell_keys.parquet`).
- `data/parquet/positions_enriched/*.parquet` — detail fallback.
- `data/parquet/matches.parquet`, `data/parquet/games.parquet` — for
  match / player metadata.

## Why Python (for now)

- Parquet-native data ingestion.
- DuckDB's `read_parquet(...)` glob handling is mature.
- Same stack as the rest of `scripts/`.
- Implementation in ≤ 400 lines, can be promoted to a Go service
  later if/when barycentric data lands in `gbf.Store` (M7 / M8 scope).

## Service

- File: `scripts/barycentric_service.py`.
- Framework: **FastAPI + uvicorn** (add to `scripts/requirements.txt`
  if not already present; FastAPI is a standard choice and
  lightweight).
- Port: `localhost:8100` (configurable via `--port`).
- Dev proxy: explorer Vite config proxies `/api/bary/*` to this port
  (BE.9).

### Startup

```python
@contextmanager
def lifespan(app):
    app.state.db = duckdb.connect(":memory:")
    app.state.db.execute("""
        CREATE VIEW bary  AS SELECT * FROM read_parquet(?);
        CREATE VIEW cells AS SELECT * FROM read_parquet(?);
        CREATE VIEW boot  AS SELECT * FROM read_parquet(?);
        CREATE VIEW pos_enriched AS SELECT * FROM read_parquet(?);
        CREATE VIEW games   AS SELECT * FROM read_parquet(?);
        CREATE VIEW matches AS SELECT * FROM read_parquet(?);
    """, [barycentric_v2, cell_keys, bootstrap_cells,
          positions_enriched_glob, games, matches])
    yield
    app.state.db.close()
```

In-memory LRU cache for per-match trajectory responses (key =
`match_id`, max 128 entries).

## Endpoints

Base path: `/api/bary`. All responses are JSON.

### 1. `GET /api/bary/cells`

Query params:
- `sampling ∈ {"raw", "bootstrap"}` (default `bootstrap`).
- `variant` (optional) — filter to one `crawford_variant`.

Response body:

```json
{
  "cells": [
    {
      "cell_id": "a7_b7_normal",
      "score_away_p1": 7,
      "score_away_p2": 7,
      "crawford_variant": "normal",
      "display_label": "7a-7a",
      "n_total": 5000,
      "mean_bary_p1_a": 5.63,
      "std_bary_p1_a": 0.03,
      "mean_bary_p1_b": 5.61,
      "std_bary_p1_b": 0.03,
      "cov_bary_p1_ab_mean": -0.002,
      "mean_disp_p1_a": -1.37,
      "mean_disp_p1_b": -1.39,
      "mean_mwc_p1": 0.503,
      "std_mwc_p1": 0.004,
      "mean_cube_gap_p1": -0.021,
      "std_cube_gap_p1": 0.008,
      "low_support": false
    },
    ...
  ]
}
```

### 2. `GET /api/bary/scatter`

Query params:
- `mode ∈ {"global", "cell"}` (default `global`).
- `cell_id` (required if `mode=cell`).
- `per_cell` (global mode only) — max points per cell (default 500).
- `limit` (cell mode only) — max points (default 10000).
- `seed` — deterministic sampling.
- `variant` (optional) — filter.

Response (cursor-free, sized by caller):

```json
{
  "mode": "global",
  "total": 112500,
  "points": [
    {
      "position_id": "abcdef…",
      "bary_p1_a": 5.73,
      "bary_p1_b": 5.42,
      "mwc_p1": 0.48,
      "cube_gap_p1": -0.03,
      "score_away_p1": 7,
      "score_away_p2": 7,
      "crawford_variant": "normal"
    },
    ...
  ]
}
```

Implementation: DuckDB `SAMPLE n` per-group query:

```sql
WITH stratified AS (
  SELECT *, row_number() OVER (
           PARTITION BY cell_id
           ORDER BY hash(position_id, :seed)
         ) AS rn
  FROM bary
  JOIN cell_keys USING (score_away_p1, score_away_p2)  -- BE.3 variant
)
SELECT … FROM stratified WHERE rn <= :per_cell;
```

### 3. `POST /api/bary/select`

Rectangular (or arbitrary-polygon future extension) selection.

Request:

```json
{
  "mode": "global",
  "cell_id": null,
  "rect": { "x0": 3.0, "y0": 4.0, "x1": 6.0, "y1": 7.0 },
  "filters": {
    "crawford_variant": "normal",
    "cube_min": 1,
    "cube_max": 8,
    "decision_type": ["checker"],
    "move_number_min": 1,
    "move_number_max": 200
  },
  "sort": { "field": "move_played_error", "order": "desc" },
  "limit": 200,
  "offset": 0
}
```

Response:

```json
{
  "total": 537,
  "returned": 200,
  "positions": [
    {
      "position_id": "…",
      "game_id": "…",
      "match_id": "…",
      "move_number": 17,
      "player_on_roll": 1,
      "score_away_p1": 5, "score_away_p2": 6,
      "cube_value": 2,
      "crawford_variant": "normal",
      "bary_p1_a": 3.1, "bary_p1_b": 4.8,
      "disp_p1_a": -1.9, "disp_p1_b": -1.2,
      "mwc_p1": 0.62, "cube_gap_p1": 0.04,
      "cubeful_equity_p1": 0.20,
      "decision_type": "checker",
      "move_played_error": 0.012,
      "board_p1": [...], "board_p2": [...],
      "dice": [4, 3],
      "move_played": "13/9 13/10",
      "best_move":   "13/9 13/10"
    },
    ...
  ]
}
```

Axis convention: `x = bary_p1_b` (opponent away), `y = bary_p1_a` (P1
away), matching the existing RG plots (y-axis inverted in the UI, see
BE.5). The rectangle test is therefore `x0 ≤ bary_p1_b ≤ x1` and
`y0 ≤ bary_p1_a ≤ y1`.

Implementation: JOIN `bary` with `pos_enriched` on `position_id` to
pick up `board_p1/p2`, `dice`, `move_played`, `best_move`,
`move_played_error`. Keep the projection narrow — full boards are
expensive.

### 4. `GET /api/bary/match/{position_id}`

Returns the full trajectory of the match the position belongs to.

Response:

```json
{
  "match_id": "…",
  "match_length": 11,
  "players": { "p1": "Michel Lamote", "p2": "Gaz Owen" },
  "games": [
    { "game_id": "…_game_01", "game_number": 1, "score_away_p1_start": 11,
      "score_away_p2_start": 11, "winner": 2, "points_won": 8,
      "gammon": true, "backgammon": false, "crawford": false }
  ],
  "positions": [
    {
      "position_id": "…",
      "game_id": "…_game_01",
      "game_number": 1,
      "move_number": 1,
      "player_on_roll": 2,
      "score_away_p1": 11, "score_away_p2": 11,
      "crawford": false, "is_post_crawford": false,
      "cube_value": 1,
      "bary_p1_a": 10.4, "bary_p1_b": 10.5,
      "mwc_p1": 0.502, "cube_gap_p1": 0.003,
      "cubeful_equity_p1": 0.0,
      "decision_type": "checker",
      "move_played_error": 0.0
    },
    ... ordered by (game_number, move_number) ...
  ]
}
```

Implementation:

```sql
WITH target AS (SELECT match_id FROM bary WHERE position_id = ?)
SELECT b.*, g.game_number
FROM bary b
JOIN games g USING (game_id)
WHERE b.match_id = (SELECT match_id FROM target)
ORDER BY g.game_number, b.move_number;
```

Cache: `@lru_cache(maxsize=128)` keyed by `match_id`. Invalidation
isn't needed (the parquet is static between runs).

### 5. `GET /api/bary/position/{position_id}`

Rich detail for the selection panel's drawer. Payload shape matches
what `PositionDetail.svelte` already consumes (reuse directly):

```json
{
  "position_id": "...",
  "board_p1": [...], "board_p2": [...],
  "dice": [...], "cube_value": ..., "cube_owner": ...,
  "player_on_roll": ..., "score_away_p1": ..., "score_away_p2": ...,
  "eval_win": ..., "eval_win_g": ..., "eval_win_bg": ...,
  "eval_lose_g": ..., "eval_lose_bg": ..., "eval_equity": ...,
  "move_played": ..., "best_move": ..., "move_played_error": ...,
  "cube_action_played": ..., "cube_action_optimal": ...,
  "pip_count_p1": ..., "pip_count_p2": ...,
  "context": {
    "bary_p1_a": ..., "bary_p1_b": ...,
    "mwc_p1": ..., "cube_gap_p1": ...,
    "crawford_variant": "normal",
    "match_id": "...",
    "game_id": "..."
  }
}
```

Prefer delegating to the existing Go viz API (`GET
/api/viz/position/{id}`) if it serves the same payload shape; if so,
the Python service can skip this endpoint and the frontend queries
both APIs directly.

### Error responses

- `400` with `{ "error": "..." }` for invalid params.
- `404` for unknown `position_id` / `cell_id`.
- `500` with a short message; server logs the stack trace.

## CLI / run

```bash
python scripts/barycentric_service.py \
  --bary   data/barycentric/barycentric_v2.parquet \
  --cells  data/barycentric/cell_keys.parquet \
  --boot   data/barycentric/bootstrap_cells.parquet \
  --enriched data/parquet/positions_enriched \
  --games  data/parquet/games.parquet \
  --matches data/parquet/matches.parquet \
  --port   8100

# Dev helper
make bary-service    # wraps the above
```

## Complexity

Medium. ~350 lines Python. No database migrations, no state beyond
the LRU cache.

## Verification

1. **Schema conformance** — `pytest tests/test_barycentric_service.py`
   calls each endpoint with fixture parquet files (tiny synthetic
   dataset; 20 positions across 2 matches) and validates response
   shapes with pydantic models.

2. **Numeric invariants**:
   - `/scatter?mode=global` returns `≤ 225 * per_cell` points.
   - `/select` rectangle returns positions whose
     `(bary_p1_b, bary_p1_a)` actually lie inside the rectangle.
   - `/match` returns positions sorted by `(game_number, move_number)`.
   - `/cells?sampling=raw` cells numerically match a polars group-by
     on `barycentric_v2.parquet` (unit test).

3. **Performance smoke** — on the real 16 M dataset, record latency
   for:
   - cold `/scatter?mode=global` (< 1 s).
   - `/select` returning 200 positions (< 300 ms).
   - `/match` cold (< 400 ms), warm (< 5 ms).

4. **CORS / dev proxy** — manual test via the Vite dev server.

## Migration path to Go

If/when the barycentric data moves into `gbf.Store`, these endpoints
are mechanically portable: each is a single SQL query plus projection.
Keep the HTTP contract stable so the frontend can swap base URLs
without code changes.
