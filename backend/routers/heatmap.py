"""Cube error heatmap endpoints."""
from functools import lru_cache
from fastapi import APIRouter, Query
from backend.db import q, q_one
from backend.config import MAX_ROWS

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("/cube-error")
def cube_error_heatmap(
    match_length: int | None = Query(None, ge=1, le=25),
    player:       str | None = Query(None, max_length=100),
):
    """
    Global or per-match-length cube error heatmap (away_p1 × away_p2).
    If `player` is provided, returns that player's personal heatmap.
    Falls back to pre-computed materialised table when possible.
    """
    if player:
        # Live query from raw positions
        params: list = [player]
        length_clause = ""
        if match_length:
            length_clause = "AND match_length = ?"
            params.append(match_length)
        rows = q(
            f"""
            SELECT away_p1, away_p2,
                   AVG(move_played_error)               AS avg_error,
                   COUNT(*)                             AS n_decisions,
                   AVG(CASE WHEN is_missed_double THEN 1.0 ELSE 0.0 END)
                                                        AS missed_double_rate,
                   AVG(CASE WHEN is_wrong_take    THEN 1.0 ELSE 0.0 END)
                                                        AS wrong_take_rate,
                   AVG(CASE WHEN is_wrong_pass    THEN 1.0 ELSE 0.0 END)
                                                        AS wrong_pass_rate
            FROM positions
            WHERE player_name = ?
              AND decision_type = 'cube'
              {length_clause}
            GROUP BY away_p1, away_p2
            HAVING COUNT(*) >= 20
            ORDER BY away_p1, away_p2
            """,
            params,
        )
    elif match_length:
        rows = q(
            """
            SELECT away_p1, away_p2, avg_error, n_decisions,
                   missed_double_rate, wrong_take_rate, wrong_pass_rate
            FROM heatmap_cells
            WHERE match_length = ?
            ORDER BY away_p1, away_p2
            """,
            [match_length],
        )
    else:
        rows = q(
            """
            SELECT away_p1, away_p2,
                   AVG(avg_error)       AS avg_error,
                   SUM(n_decisions)     AS n_decisions,
                   AVG(missed_double_rate) AS missed_double_rate,
                   AVG(wrong_take_rate)    AS wrong_take_rate,
                   AVG(wrong_pass_rate)    AS wrong_pass_rate
            FROM heatmap_cells
            GROUP BY away_p1, away_p2
            ORDER BY away_p1, away_p2
            """,
        )

    return {"cells": rows, "match_length": match_length, "player": player}


@router.get("/cube-error/cell")
def cube_error_cell(
    away_p1:      int = Query(..., ge=1, le=25),
    away_p2:      int = Query(..., ge=1, le=25),
    match_length: int | None = Query(None, ge=1, le=25),
):
    """Detail for a single (away_p1, away_p2) cell."""
    params: list = [away_p1, away_p2]
    length_clause = ""
    if match_length:
        length_clause = "AND match_length = ?"
        params.append(match_length)

    cell = q_one(
        f"""
        SELECT away_p1, away_p2,
               AVG(move_played_error)  AS avg_error,
               STDDEV(move_played_error) AS std_error,
               COUNT(*)                AS n_decisions,
               AVG(CASE WHEN is_missed_double THEN 1.0 ELSE 0.0 END) AS missed_double_rate,
               AVG(CASE WHEN is_wrong_take    THEN 1.0 ELSE 0.0 END) AS wrong_take_rate,
               AVG(CASE WHEN is_wrong_pass    THEN 1.0 ELSE 0.0 END) AS wrong_pass_rate
        FROM positions
        WHERE away_p1 = ? AND away_p2 = ?
          AND decision_type = 'cube'
          {length_clause}
        GROUP BY away_p1, away_p2
        """,
        params,
    )
    # Top positions at this score
    top = q(
        """
        SELECT match_id, move_number, player_name,
               move_played_error, eval_equity
        FROM positions
        WHERE away_p1 = ? AND away_p2 = ?
          AND decision_type = 'cube'
        ORDER BY move_played_error DESC
        LIMIT 5
        """,
        [away_p1, away_p2],
    )
    return {"cell": cell, "top_positions": top}
