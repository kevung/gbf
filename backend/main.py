"""GBF Dashboard — FastAPI application entry point."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.routers import players, heatmap, positions, cube, stats, clusters, map
from backend.config import STATIC_DIR

app = FastAPI(
    title="GBF Dashboard API",
    description="REST API for the GBF backgammon mining study dashboard.",
    version="0.1.0",
)

# ── CORS (allow SvelteKit dev server on :5173) ─────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(players.router)
app.include_router(heatmap.router)
app.include_router(positions.router)
app.include_router(cube.router)
app.include_router(stats.router)
app.include_router(clusters.router)
app.include_router(map.router)

# ── Tournament search (lightweight, no dedicated router) ───────────────────────
from fastapi import Query as Q
from backend.db import q
from backend.config import MAX_ROWS

@app.get("/api/tournaments", tags=["tournaments"])
def list_tournaments(search: str = Q("", max_length=200), limit: int = Q(20, le=MAX_ROWS)):
    clause = "WHERE lower(tournament) LIKE lower(?)" if search else ""
    params = [f"%{search}%", limit] if search else [limit]
    rows = q(
        f"""
        SELECT tournament,
               COUNT(DISTINCT match_id) AS match_count,
               COUNT(*)                 AS position_count,
               AVG(move_played_error)   AS avg_error
        FROM positions
        {clause}
        GROUP BY tournament
        ORDER BY match_count DESC
        LIMIT ?
        """,
        params,
    )
    return {"tournaments": rows}


@app.get("/api/tournaments/{name}/stats", tags=["tournaments"])
def tournament_stats(name: str):
    row = q(
        """
        SELECT tournament,
               COUNT(DISTINCT match_id) AS match_count,
               COUNT(*)                 AS position_count,
               AVG(move_played_error)   AS avg_error,
               AVG(CASE WHEN move_played_error >= 0.080 THEN 1.0 ELSE 0.0 END)
                   AS blunder_rate,
               COUNT(DISTINCT player_name) AS player_count
        FROM positions
        WHERE lower(tournament) = lower(?)
        GROUP BY tournament
        """,
        [name],
    )
    return {"stats": row[0] if row else None}


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}


# ── Serve SvelteKit static build (production) ──────────────────────────────────
_static = Path(STATIC_DIR)
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
