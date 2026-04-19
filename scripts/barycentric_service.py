#!/usr/bin/env python3
"""
BE.4 — Barycentric Query Service

FastAPI + DuckDB read-only HTTP service that serves the interactive barycentric
explorer views from local parquet files.

Usage
-----
  python scripts/barycentric_service.py \\
      --bary    data/barycentric/barycentric_v2.parquet \\
      --cells   data/barycentric/cell_keys.parquet \\
      --boot    data/barycentric/bootstrap_cells.parquet \\
      --enriched data/parquet/positions_enriched \\
      --games   data/parquet/games.parquet \\
      --matches data/parquet/matches.parquet \\
      --port    8100
"""

from __future__ import annotations

import argparse
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import duckdb
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Module-level path config — populated by CLI before app starts
# ---------------------------------------------------------------------------

_paths: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Startup / teardown
# ---------------------------------------------------------------------------

def _create_views(db: duckdb.DuckDBPyConnection, paths: dict[str, str]) -> None:
    db.execute(f"CREATE VIEW bary      AS SELECT * FROM read_parquet('{paths['bary']}')")
    db.execute(f"CREATE VIEW cell_keys AS SELECT * FROM read_parquet('{paths['cells']}')")
    db.execute(f"CREATE VIEW boot      AS SELECT * FROM read_parquet('{paths['boot']}')")
    db.execute(f"CREATE VIEW pos_enriched AS SELECT * FROM read_parquet('{paths['enriched']}')")
    db.execute(f"CREATE VIEW games     AS SELECT * FROM read_parquet('{paths['games']}')")
    db.execute(f"CREATE VIEW matches   AS SELECT * FROM read_parquet('{paths['matches']}')")
    # Derived view: add crawford_variant so all queries have it available
    db.execute("""
        CREATE VIEW bary_v AS
        SELECT *,
            CASE
                WHEN score_away_p1 != 1 AND score_away_p2 != 1 THEN 'normal'
                WHEN crawford = true THEN 'crawford'
                WHEN is_post_crawford = true THEN 'post_crawford'
                ELSE 'normal'
            END AS crawford_variant
        FROM bary
    """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = duckdb.connect(":memory:")
    _create_views(db, _paths)
    app.state.db = db
    app.state.lock = threading.Lock()
    app.state.match_cache: dict[str, dict] = {}
    yield
    db.close()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="Barycentric Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _query(request: Request, sql: str, params: list | None = None) -> list[dict]:
    db: duckdb.DuckDBPyConnection = request.app.state.db
    lock: threading.Lock = request.app.state.lock
    with lock:
        rel = db.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]


def _query_one(request: Request, sql: str, params: list | None = None) -> dict | None:
    rows = _query(request, sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# GET /api/bary/cells
# ---------------------------------------------------------------------------

@app.get("/api/bary/cells")
def get_cells(
    request: Request,
    sampling: str = "bootstrap",
    variant: Optional[str] = None,
) -> dict:
    if sampling not in ("bootstrap", "raw"):
        raise HTTPException(400, detail={"error": f"sampling must be 'raw' or 'bootstrap'"})

    if sampling == "bootstrap":
        # Prefer stratified draws; fall back to uniform
        cond = "AND b.crawford_variant = ?" if variant else ""
        params = [variant] if variant else []
        sql = f"""
            SELECT
                b.cell_id,
                b.score_away_p1, b.score_away_p2, b.crawford_variant,
                k.display_label,
                b.n_total,
                b.mean_bary_p1_a_mean        AS mean_bary_p1_a,
                b.mean_bary_p1_a_std         AS std_bary_p1_a,
                b.mean_bary_p1_b_mean        AS mean_bary_p1_b,
                b.mean_bary_p1_b_std         AS std_bary_p1_b,
                b.cov_bary_p1_ab_mean,
                b.mean_disp_p1_a_mean        AS mean_disp_p1_a,
                b.mean_disp_p1_b_mean        AS mean_disp_p1_b,
                b.mean_cubeless_mwc_p1_mean  AS mean_mwc_p1,
                b.mean_cubeless_mwc_p1_std   AS std_mwc_p1,
                b.mean_cube_gap_p1_mean      AS mean_cube_gap_p1,
                b.mean_cube_gap_p1_std       AS std_cube_gap_p1,
                b.low_support
            FROM boot b
            JOIN cell_keys k USING (cell_id)
            WHERE b.sampling_mode = 'stratified' {cond}
        """
        cells = _query(request, sql, params)
        if not cells:
            sql = sql.replace("sampling_mode = 'stratified'", "sampling_mode = 'uniform'")
            cells = _query(request, sql, params)
    else:
        # Raw: compute live from bary_v + cell_keys
        cond = "WHERE v.crawford_variant = ?" if variant else ""
        params = [variant] if variant else []
        sql = f"""
            SELECT
                k.cell_id,
                k.score_away_p1, k.score_away_p2, k.crawford_variant,
                k.display_label,
                COUNT(*)                       AS n_total,
                AVG(v.bary_p1_a)               AS mean_bary_p1_a,
                STDDEV(v.bary_p1_a)            AS std_bary_p1_a,
                AVG(v.bary_p1_b)               AS mean_bary_p1_b,
                STDDEV(v.bary_p1_b)            AS std_bary_p1_b,
                COVAR_POP(v.bary_p1_a, v.bary_p1_b) AS cov_bary_p1_ab_mean,
                AVG(v.disp_p1_a)               AS mean_disp_p1_a,
                AVG(v.disp_p1_b)               AS mean_disp_p1_b,
                AVG(v.cubeless_mwc_p1)         AS mean_mwc_p1,
                STDDEV(v.cubeless_mwc_p1)      AS std_mwc_p1,
                AVG(v.cube_gap_p1)             AS mean_cube_gap_p1,
                STDDEV(v.cube_gap_p1)          AS std_cube_gap_p1,
                false                          AS low_support
            FROM bary_v v
            JOIN cell_keys k USING (score_away_p1, score_away_p2, crawford_variant)
            {cond}
            GROUP BY k.cell_id, k.score_away_p1, k.score_away_p2,
                     k.crawford_variant, k.display_label
        """
        cells = _query(request, sql, params)

    return {"cells": cells}


# ---------------------------------------------------------------------------
# GET /api/bary/scatter
# ---------------------------------------------------------------------------

@app.get("/api/bary/scatter")
def get_scatter(
    request: Request,
    mode: str = "global",
    cell_id: Optional[str] = None,
    per_cell: int = 500,
    limit: int = 10000,
    seed: int = 42,
    variant: Optional[str] = None,
) -> dict:
    if mode not in ("global", "cell"):
        raise HTTPException(400, detail={"error": "mode must be 'global' or 'cell'"})
    if mode == "cell" and not cell_id:
        raise HTTPException(400, detail={"error": "cell_id required when mode=cell"})

    SELECT = """
        v.position_id,
        v.bary_p1_a, v.bary_p1_b,
        v.cubeless_mwc_p1 AS mwc_p1,
        v.cube_gap_p1,
        v.score_away_p1, v.score_away_p2,
        v.crawford_variant
    """

    if mode == "global":
        cond = "AND v.crawford_variant = ?" if variant else ""
        params: list = [variant] if variant else []
        sql = f"""
            WITH stratified AS (
                SELECT {SELECT},
                    k.cell_id,
                    row_number() OVER (
                        PARTITION BY k.cell_id
                        ORDER BY hash(v.position_id || CAST({seed} AS VARCHAR))
                    ) AS rn
                FROM bary_v v
                JOIN cell_keys k USING (score_away_p1, score_away_p2, crawford_variant)
                WHERE 1=1 {cond}
            )
            SELECT position_id, bary_p1_a, bary_p1_b, mwc_p1, cube_gap_p1,
                   score_away_p1, score_away_p2, crawford_variant
            FROM stratified
            WHERE rn <= {per_cell}
        """
    else:
        # mode=cell
        cond = "AND v.crawford_variant = ?" if variant else ""
        params = [variant] if variant else []
        sql = f"""
            SELECT {SELECT}
            FROM bary_v v
            JOIN cell_keys k USING (score_away_p1, score_away_p2, crawford_variant)
            WHERE k.cell_id = ? {cond}
            ORDER BY hash(v.position_id || CAST({seed} AS VARCHAR))
            LIMIT {limit}
        """
        params = [cell_id] + params

    points = _query(request, sql, params or None)
    return {"mode": mode, "total": len(points), "points": points}


# ---------------------------------------------------------------------------
# POST /api/bary/select
# ---------------------------------------------------------------------------

class Rect(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class Filters(BaseModel):
    crawford_variant: Optional[str] = None
    cube_min: Optional[int] = None
    cube_max: Optional[int] = None
    decision_type: Optional[list[str]] = None
    move_number_min: Optional[int] = None
    move_number_max: Optional[int] = None


class SortSpec(BaseModel):
    field: str = "move_played_error"
    order: str = "desc"


class SelectBody(BaseModel):
    mode: str = "global"
    cell_id: Optional[str] = None
    rect: Rect
    filters: Optional[Filters] = None
    sort: Optional[SortSpec] = None
    limit: int = 200
    offset: int = 0


_SORTABLE_FIELDS = {
    "move_played_error", "mwc_p1", "cube_gap_p1",
    "bary_p1_a", "bary_p1_b", "move_number",
}


@app.post("/api/bary/select")
def post_select(request: Request, body: SelectBody) -> dict:
    f = body.filters or Filters()
    sort = body.sort or SortSpec()

    if sort.field not in _SORTABLE_FIELDS:
        raise HTTPException(400, detail={"error": f"Cannot sort by '{sort.field}'"})
    if sort.order not in ("asc", "desc"):
        raise HTTPException(400, detail={"error": "sort.order must be 'asc' or 'desc'"})

    conds: list[str] = [
        "v.bary_p1_b BETWEEN ? AND ?",  # x axis = bary_p1_b
        "v.bary_p1_a BETWEEN ? AND ?",  # y axis = bary_p1_a
    ]
    params: list[Any] = [body.rect.x0, body.rect.x1, body.rect.y0, body.rect.y1]

    if body.cell_id:
        conds.append("k.cell_id = ?")
        params.append(body.cell_id)
    if f.crawford_variant:
        conds.append("v.crawford_variant = ?")
        params.append(f.crawford_variant)
    if f.cube_min is not None:
        conds.append("v.cube_value >= ?")
        params.append(f.cube_min)
    if f.cube_max is not None:
        conds.append("v.cube_value <= ?")
        params.append(f.cube_max)
    if f.decision_type:
        placeholders = ",".join("?" * len(f.decision_type))
        conds.append(f"p.decision_type IN ({placeholders})")
        params.extend(f.decision_type)
    if f.move_number_min is not None:
        conds.append("v.move_number >= ?")
        params.append(f.move_number_min)
    if f.move_number_max is not None:
        conds.append("v.move_number <= ?")
        params.append(f.move_number_max)

    where = "WHERE " + " AND ".join(conds) if conds else ""

    # Map sort field aliases
    sort_col = {
        "mwc_p1": "v.cubeless_mwc_p1",
        "move_played_error": "p.move_played_error",
        "bary_p1_a": "v.bary_p1_a",
        "bary_p1_b": "v.bary_p1_b",
        "cube_gap_p1": "v.cube_gap_p1",
        "move_number": "v.move_number",
    }.get(sort.field, f"v.{sort.field}")

    # Count query
    count_sql = f"""
        SELECT COUNT(*) AS n
        FROM bary_v v
        JOIN cell_keys k USING (score_away_p1, score_away_p2, crawford_variant)
        LEFT JOIN pos_enriched p USING (position_id)
        {where}
    """
    total_row = _query_one(request, count_sql, list(params))
    total = total_row["n"] if total_row else 0

    data_sql = f"""
        SELECT
            v.position_id, v.game_id, v.match_id, v.move_number, v.player_on_roll,
            v.score_away_p1, v.score_away_p2, v.cube_value,
            v.crawford_variant,
            v.bary_p1_a, v.bary_p1_b, v.disp_p1_a, v.disp_p1_b,
            v.cubeless_mwc_p1 AS mwc_p1,
            v.cubeful_equity_p1,
            v.cube_gap_p1,
            p.decision_type,
            p.move_played_error,
            p.board_p1, p.board_p2,
            p.dice,
            p.move_played,
            p.best_move
        FROM bary_v v
        JOIN cell_keys k USING (score_away_p1, score_away_p2, crawford_variant)
        LEFT JOIN pos_enriched p USING (position_id)
        {where}
        ORDER BY {sort_col} {sort.order}
        LIMIT {body.limit} OFFSET {body.offset}
    """
    positions = _query(request, data_sql, list(params))
    return {"total": total, "returned": len(positions), "positions": positions}


# ---------------------------------------------------------------------------
# GET /api/bary/match/{position_id}
# ---------------------------------------------------------------------------

@app.get("/api/bary/match/{position_id}")
def get_match(request: Request, position_id: str) -> dict:
    cache: dict = request.app.state.match_cache

    # Resolve match_id
    mid_row = _query_one(
        request,
        "SELECT match_id FROM bary WHERE position_id = ?",
        [position_id],
    )
    if not mid_row:
        raise HTTPException(404, detail={"error": f"position '{position_id}' not found"})
    match_id = mid_row["match_id"]

    if match_id in cache:
        return cache[match_id]

    # Match metadata
    meta = _query_one(
        request,
        "SELECT * FROM matches WHERE match_id = ?",
        [match_id],
    )
    # Games metadata
    games_rows = _query(
        request,
        """
        SELECT g.game_id, g.game_number,
               MIN(v.score_away_p1) AS score_away_p1_start,
               MIN(v.score_away_p2) AS score_away_p2_start
        FROM bary_v v
        JOIN games g USING (game_id)
        WHERE v.match_id = ?
        GROUP BY g.game_id, g.game_number
        ORDER BY g.game_number
        """,
        [match_id],
    )
    # All positions in match
    positions = _query(
        request,
        """
        SELECT
            v.position_id, v.game_id, v.game_number, v.move_number,
            v.player_on_roll,
            v.score_away_p1, v.score_away_p2,
            v.crawford, v.is_post_crawford,
            v.cube_value,
            v.bary_p1_a, v.bary_p1_b,
            v.cubeless_mwc_p1 AS mwc_p1,
            v.cubeful_equity_p1,
            v.cube_gap_p1,
            v.decision_type,
            v.move_played_error
        FROM bary_v v
        WHERE v.match_id = ?
        ORDER BY v.game_number, v.move_number
        """,
        [match_id],
    )

    result: dict[str, Any] = {
        "match_id": match_id,
        "match_length": meta.get("match_length") if meta else None,
        "players": {
            "p1": meta.get("player1") if meta else None,
            "p2": meta.get("player2") if meta else None,
        },
        "games": games_rows,
        "positions": positions,
    }

    # LRU: evict oldest when full
    if len(cache) >= 128:
        cache.pop(next(iter(cache)))
    cache[match_id] = result
    return result


# ---------------------------------------------------------------------------
# GET /api/bary/position/{position_id}
# ---------------------------------------------------------------------------

@app.get("/api/bary/position/{position_id}")
def get_position(request: Request, position_id: str) -> dict:
    row = _query_one(
        request,
        """
        SELECT
            v.position_id,
            v.player_on_roll, v.score_away_p1, v.score_away_p2,
            v.cube_value, v.crawford_variant,
            v.bary_p1_a, v.bary_p1_b,
            v.cubeless_mwc_p1 AS mwc_p1,
            v.cubeful_equity_p1, v.cube_gap_p1,
            v.match_id, v.game_id,
            p.board_p1, p.board_p2, p.dice,
            p.eval_win, p.eval_win_g, p.eval_win_bg,
            p.eval_lose_g, p.eval_lose_bg, p.eval_equity,
            p.move_played, p.best_move, p.move_played_error,
            p.cube_action_played, p.cube_action_optimal,
            p.pip_count_p1, p.pip_count_p2
        FROM bary_v v
        LEFT JOIN pos_enriched p USING (position_id)
        WHERE v.position_id = ?
        """,
        [position_id],
    )
    if not row:
        raise HTTPException(404, detail={"error": f"position '{position_id}' not found"})

    # Reshape: hoist bary fields into a context sub-object
    context = {
        k: row.pop(k)
        for k in ("bary_p1_a", "bary_p1_b", "mwc_p1", "cube_gap_p1",
                  "crawford_variant", "match_id", "game_id")
        if k in row
    }
    row["context"] = context
    return row


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="BE.4 Barycentric Query Service")
    ap.add_argument("--bary",     required=True, help="barycentric_v2.parquet")
    ap.add_argument("--cells",    required=True, help="cell_keys.parquet")
    ap.add_argument("--boot",     required=True, help="bootstrap_cells.parquet")
    ap.add_argument("--enriched", required=True, help="positions_enriched dir (glob)")
    ap.add_argument("--games",    required=True, help="games.parquet")
    ap.add_argument("--matches",  required=True, help="matches.parquet")
    ap.add_argument("--port",     type=int, default=8100)
    return ap


if __name__ == "__main__":
    import uvicorn

    args = _build_parser().parse_args()

    enriched_path = Path(args.enriched)
    if enriched_path.is_dir():
        enriched_glob = str(enriched_path / "*.parquet")
    else:
        enriched_glob = args.enriched

    _paths.update({
        "bary":     args.bary,
        "cells":    args.cells,
        "boot":     args.boot,
        "enriched": enriched_glob,
        "games":    args.games,
        "matches":  args.matches,
    })

    uvicorn.run(app, host="127.0.0.1", port=args.port)
