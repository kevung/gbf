"""Player endpoints."""
from fastapi import APIRouter, Query, HTTPException
from backend.db import q, q_one
from backend.config import MAX_ROWS

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("")
def list_players(
    search: str = Query("", max_length=100),
    limit:  int = Query(20, le=MAX_ROWS),
    offset: int = Query(0,  ge=0),
):
    """Search players by name, ordered by game count descending."""
    if search:
        rows = q(
            """
            SELECT player_name, total_games, total_positions,
                   avg_error_checker, avg_error_cube, blunder_rate
            FROM player_profiles
            WHERE lower(player_name) LIKE lower(?)
            ORDER BY total_games DESC
            LIMIT ? OFFSET ?
            """,
            [f"%{search}%", limit, offset],
        )
    else:
        rows = q(
            """
            SELECT player_name, total_games, total_positions,
                   avg_error_checker, avg_error_cube, blunder_rate
            FROM player_profiles
            ORDER BY total_games DESC
            LIMIT ? OFFSET ?
            """,
            [limit, offset],
        )
    return {"players": rows, "limit": limit, "offset": offset}


@router.get("/compare")
def compare_players(
    p1: str = Query(..., max_length=100),
    p2: str = Query(..., max_length=100),
):
    """Return profile metrics for two players side-by-side."""
    rows = q(
        """
        SELECT *
        FROM player_profiles
        WHERE player_name IN (?, ?)
        """,
        [p1, p2],
    )
    if len(values := {r["player_name"]: r for r in rows}) < 2:
        missing = [p for p in [p1, p2] if p not in values]
        raise HTTPException(404, detail=f"Players not found: {missing}")
    return {"p1": values[p1], "p2": values[p2]}


@router.get("/{name}/profile")
def player_profile(name: str):
    """Full profile for a single player (metrics + cluster + ranking)."""
    row = q_one(
        """
        SELECT p.*, r.pr_rating, r.pr_rank, r.pr_ci_low, r.pr_ci_high,
               c.cluster_id, c.archetype_label
        FROM player_profiles p
        LEFT JOIN player_rankings r USING (player_name)
        LEFT JOIN (
            SELECT player_name, cluster_id, archetype_label
            FROM (
                SELECT player_name, cluster_id::VARCHAR AS cluster_id,
                       '' AS archetype_label
                FROM player_profiles
            )
        ) c USING (player_name)
        WHERE p.player_name = ?
        """,
        [name],
    )
    if not row:
        raise HTTPException(404, detail=f"Player '{name}' not found")
    return row


@router.get("/{name}/positions")
def player_positions(
    name:       str,
    phase:      str | None = Query(None),
    error_min:  float = Query(0.0,  ge=0.0),
    error_max:  float = Query(2.0,  le=2.0),
    decision_type: str | None = Query(None),
    limit:      int   = Query(50,  le=MAX_ROWS),
    offset:     int   = Query(0,   ge=0),
):
    """Positions played by a player, with optional filters."""
    filters = ["player_name = ?"]
    params: list = [name, error_min, error_max]

    base_where = "move_played_error BETWEEN ? AND ?"
    if phase:
        filters.append("match_phase = ?")
        params.append({"contact": 0, "race": 1, "bearoff": 2}.get(phase, phase))
    if decision_type:
        filters.append("lower(decision_type) = lower(?)")
        params.append(decision_type)

    where = " AND ".join(filters)
    params += [limit, offset]

    rows = q(
        f"""
        SELECT match_id, move_number, player_name,
               away_p1, away_p2, match_phase, decision_type,
               move_played_error, eval_equity
        FROM positions
        WHERE {where} AND {base_where}
        ORDER BY move_played_error DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )
    return {"positions": rows, "limit": limit, "offset": offset}
