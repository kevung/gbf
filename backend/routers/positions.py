"""Position search and detail endpoints."""
from fastapi import APIRouter, Query, HTTPException
from backend.db import q, q_one
from backend.config import MAX_ROWS

router = APIRouter(prefix="/api/positions", tags=["positions"])

_PHASE_MAP = {"contact": 0, "race": 1, "bearoff": 2}


@router.get("")
def search_positions(
    player:        str | None   = Query(None, max_length=100),
    tournament:    str | None   = Query(None, max_length=200),
    away_p1:       int | None   = Query(None, ge=1, le=25),
    away_p2:       int | None   = Query(None, ge=1, le=25),
    phase:         str | None   = Query(None),
    decision_type: str | None   = Query(None),
    error_min:     float        = Query(0.0, ge=0.0),
    error_max:     float        = Query(2.0, le=2.0),
    cluster:       int | None   = Query(None),
    blunders_only: bool         = Query(False),
    limit:         int          = Query(50, le=MAX_ROWS),
    offset:        int          = Query(0, ge=0),
):
    """
    Search positions with any combination of filters.
    All user inputs are bind-param safe (no SQL injection).
    """
    clauses = ["move_played_error BETWEEN ? AND ?"]
    params: list = [error_min, error_max]

    if blunders_only:
        clauses.append("move_played_error >= 0.080")
    if player:
        clauses.append("lower(player_name) LIKE lower(?)")
        params.append(f"%{player}%")
    if tournament:
        clauses.append("lower(tournament) LIKE lower(?)")
        params.append(f"%{tournament}%")
    if away_p1 is not None:
        clauses.append("away_p1 = ?")
        params.append(away_p1)
    if away_p2 is not None:
        clauses.append("away_p2 = ?")
        params.append(away_p2)
    if phase:
        clauses.append("match_phase = ?")
        params.append(_PHASE_MAP.get(phase, phase))
    if decision_type:
        clauses.append("lower(decision_type) = lower(?)")
        params.append(decision_type)
    if cluster is not None:
        clauses.append("cluster_id = ?")
        params.append(cluster)

    where = " AND ".join(clauses)
    params += [limit, offset]

    rows = q(
        f"""
        SELECT match_id, move_number, player_name, tournament,
               away_p1, away_p2, match_phase, decision_type,
               move_played_error, eval_equity, cluster_id
        FROM positions
        WHERE {where}
        ORDER BY move_played_error DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )
    return {"positions": rows, "limit": limit, "offset": offset}


@router.get("/{position_id}/detail")
def position_detail(position_id: str):
    """
    Full detail for a single position by composite ID
    (format: {match_id}_{move_number}).
    """
    parts = position_id.split("_", 1)
    if len(parts) != 2:
        raise HTTPException(400, "position_id must be {match_id}_{move_number}")
    match_id, move_number = parts[0], parts[1]

    row = q_one(
        """
        SELECT *
        FROM positions
        WHERE match_id = ? AND move_number::VARCHAR = ?
        LIMIT 1
        """,
        [match_id, move_number],
    )
    if not row:
        raise HTTPException(404, "Position not found")

    # Cluster context
    cluster = None
    if row.get("cluster_id") is not None:
        cluster = q_one(
            """
            SELECT cluster_id, archetype_label,
                   AVG(move_played_error) AS cluster_avg_error,
                   COUNT(*) AS cluster_size
            FROM position_clusters
            WHERE cluster_id = ?
            GROUP BY cluster_id, archetype_label
            """,
            [row["cluster_id"]],
        )

    return {"position": row, "cluster": cluster}
