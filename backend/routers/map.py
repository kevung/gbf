"""UMAP position map and trajectory endpoints (S4.7)."""
from fastapi import APIRouter, Query, HTTPException
from backend.db import q, q_one
from backend.config import MAX_ROWS

router = APIRouter(tags=["map"])


# ── Map / density endpoints ────────────────────────────────────────────────────

@router.get("/api/map/points")
def map_points(
    x_min:  float = Query(...),
    x_max:  float = Query(...),
    y_min:  float = Query(...),
    y_max:  float = Query(...),
    limit:  int   = Query(5000, le=5000),
    player: str | None = Query(None, max_length=100),
    phase:  str | None = Query(None),
    error_min: float   = Query(0.0, ge=0.0),
):
    """
    Points visible in the current viewport (for deck.gl ScatterplotLayer).
    Bounded by (x_min, x_max, y_min, y_max) in UMAP coordinate space.
    Returns at most 5 000 points (hard limit for WebGL performance).
    """
    params: list = [x_min, x_max, y_min, y_max, error_min]
    extra = ""
    if player:
        extra += " AND lower(player_name) LIKE lower(?)"
        params.append(f"%{player}%")
    if phase:
        pmap = {"contact": 0, "race": 1, "bearoff": 2}
        extra += " AND match_phase = ?"
        params.append(pmap.get(phase, phase))
    params.append(limit)

    rows = q(
        f"""
        SELECT position_hash, umap_x, umap_y,
               move_played_error, match_phase, cluster_id
        FROM umap_positions
        WHERE umap_x BETWEEN ? AND ?
          AND umap_y BETWEEN ? AND ?
          AND move_played_error >= ?
          {extra}
        ORDER BY RANDOM()
        LIMIT ?
        """,
        params,
    )
    return {"points": rows, "count": len(rows)}


@router.get("/api/map/hexbins")
def map_hexbins(
    x_min:      float = Query(...),
    x_max:      float = Query(...),
    y_min:      float = Query(...),
    y_max:      float = Query(...),
    resolution: int   = Query(40, ge=5, le=200),
    color_by:   str   = Query("density"),
):
    """
    Hexbin aggregation for intermediate zoom levels.
    Returns (hex_x, hex_y, count, avg_error, dominant_cluster) per bin.
    `color_by`: density | avg_error | cluster
    """
    rows = q(
        """
        SELECT
            ROUND(umap_x / ?, 0) * ? AS hex_x,
            ROUND(umap_y / ?, 0) * ? AS hex_y,
            COUNT(*)                 AS count,
            AVG(move_played_error)   AS avg_error,
            MODE(cluster_id)         AS dominant_cluster
        FROM umap_positions
        WHERE umap_x BETWEEN ? AND ?
          AND umap_y BETWEEN ? AND ?
        GROUP BY hex_x, hex_y
        ORDER BY count DESC
        """,
        [resolution, resolution, resolution, resolution,
         x_min, x_max, y_min, y_max],
    )
    return {"hexbins": rows, "color_by": color_by, "resolution": resolution}


# ── Trajectory endpoints ───────────────────────────────────────────────────────

@router.get("/api/trajectories/{position_hash}")
def trajectories(
    position_hash: str,
    limit:         int          = Query(100, le=500),
    player:        str | None   = Query(None, max_length=100),
    result:        str | None   = Query(None),
):
    """
    Trajectories passing through a crossroad position.
    Returns sequences of (umap_x, umap_y, move_number) per match.
    """
    params: list = [position_hash]
    extra = ""
    if player:
        extra += " AND lower(t.player_name) LIKE lower(?)"
        params.append(f"%{player}%")
    if result in ("win", "loss"):
        extra += " AND t.game_result = ?"
        params.append(result)
    params.append(limit)

    # Get match IDs passing through this position
    match_ids = q(
        f"""
        SELECT DISTINCT match_id
        FROM trajectory_graph
        WHERE position_hash = ?
          {extra}
        LIMIT ?
        """,
        params,
    )
    ids = [r["match_id"] for r in match_ids]
    if not ids:
        return {"trajectories": [], "position_hash": position_hash}

    # Fetch ordered waypoints for those matches
    placeholders = ",".join("?" * len(ids))
    waypoints = q(
        f"""
        SELECT t.match_id, t.move_number, u.umap_x, u.umap_y,
               t.move_played_error, t.position_hash
        FROM trajectory_graph t
        JOIN umap_positions u USING (position_hash)
        WHERE t.match_id IN ({placeholders})
        ORDER BY t.match_id, t.move_number
        """,
        ids,
    )

    # Group by match_id
    by_match: dict[str, list] = {}
    for wp in waypoints:
        by_match.setdefault(wp["match_id"], []).append(wp)

    return {
        "trajectories": [
            {"match_id": mid, "waypoints": pts}
            for mid, pts in by_match.items()
        ],
        "position_hash": position_hash,
    }


@router.get("/api/trajectories/{position_hash}/detail")
def trajectory_detail(position_hash: str):
    """
    Crossroad detail panel: stats + continuation branches.
    """
    stats = q_one(
        """
        SELECT position_hash,
               COUNT(DISTINCT match_id)        AS match_count,
               COUNT(DISTINCT player_name)     AS player_count,
               AVG(move_played_error)          AS avg_error,
               STDDEV(move_played_error)        AS std_error
        FROM trajectory_graph
        WHERE position_hash = ?
        GROUP BY position_hash
        """,
        [position_hash],
    )
    if not stats:
        raise HTTPException(404, "Position hash not found in trajectory graph")

    # Top continuation positions (next_position_hash)
    continuations = q(
        """
        SELECT next_position_hash,
               COUNT(*) AS frequency,
               AVG(move_played_error) AS avg_error
        FROM trajectory_graph
        WHERE position_hash = ?
          AND next_position_hash IS NOT NULL
        GROUP BY next_position_hash
        ORDER BY frequency DESC
        LIMIT 10
        """,
        [position_hash],
    )

    # Players who crossed this position
    players = q(
        """
        SELECT DISTINCT player_name
        FROM trajectory_graph
        WHERE position_hash = ?
        LIMIT 20
        """,
        [position_hash],
    )

    return {
        "stats": stats,
        "continuations": continuations,
        "players": [r["player_name"] for r in players],
    }


@router.get("/api/trajectories/compare")
def trajectories_compare(
    hash:    str = Query(..., alias="hash"),
    player1: str = Query(..., max_length=100),
    player2: str = Query(..., max_length=100),
    limit:   int = Query(50, le=200),
):
    """
    Compare trajectories of two players through the same crossroad.
    Returns separate trajectory lists for player1 and player2.
    """
    def fetch(player: str) -> list:
        ids = q(
            """
            SELECT DISTINCT match_id
            FROM trajectory_graph
            WHERE position_hash = ?
              AND lower(player_name) LIKE lower(?)
            LIMIT ?
            """,
            [hash, f"%{player}%", limit],
        )
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        mid_list = [r["match_id"] for r in ids]
        wps = q(
            f"""
            SELECT t.match_id, t.move_number, u.umap_x, u.umap_y,
                   t.move_played_error
            FROM trajectory_graph t
            JOIN umap_positions u USING (position_hash)
            WHERE t.match_id IN ({placeholders})
            ORDER BY t.match_id, t.move_number
            """,
            mid_list,
        )
        by_match: dict[str, list] = {}
        for wp in wps:
            by_match.setdefault(wp["match_id"], []).append(wp)
        return [{"match_id": mid, "waypoints": pts} for mid, pts in by_match.items()]

    return {
        "position_hash": hash,
        "player1": {"name": player1, "trajectories": fetch(player1)},
        "player2": {"name": player2, "trajectories": fetch(player2)},
    }
