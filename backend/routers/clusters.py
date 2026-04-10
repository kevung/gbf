"""Position cluster endpoints (S1.3 / S2.2)."""
from fastapi import APIRouter, Query, HTTPException
from backend.db import q, q_one
from backend.config import MAX_ROWS

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("")
def list_clusters():
    """All clusters with summary statistics."""
    rows = q(
        """
        SELECT cluster_id,
               ANY_VALUE(archetype_label) AS archetype_label,
               COUNT(*)                   AS position_count,
               AVG(move_played_error)     AS avg_error,
               STDDEV(move_played_error)  AS std_error,
               MODE(match_phase)          AS dominant_phase
        FROM position_clusters
        GROUP BY cluster_id
        ORDER BY avg_error DESC
        """
    )
    return {"clusters": rows}


@router.get("/{cluster_id}/profile")
def cluster_profile(cluster_id: int):
    """Detailed profile for one cluster."""
    summary = q_one(
        """
        SELECT cluster_id,
               ANY_VALUE(archetype_label) AS archetype_label,
               COUNT(*)                   AS position_count,
               AVG(move_played_error)     AS avg_error,
               STDDEV(move_played_error)  AS std_error,
               AVG(CASE WHEN match_phase = 0 THEN 1.0 ELSE 0.0 END) AS contact_pct,
               AVG(CASE WHEN match_phase = 1 THEN 1.0 ELSE 0.0 END) AS race_pct,
               AVG(CASE WHEN match_phase = 2 THEN 1.0 ELSE 0.0 END) AS bearoff_pct
        FROM position_clusters
        WHERE cluster_id = ?
        GROUP BY cluster_id
        """,
        [cluster_id],
    )
    if not summary:
        raise HTTPException(404, f"Cluster {cluster_id} not found")

    # Error distribution within cluster (5 buckets)
    distribution = q(
        """
        SELECT width_bucket(move_played_error, 0.0, 0.5, 5) AS bucket,
               COUNT(*) AS count,
               MIN(move_played_error) AS bin_min,
               MAX(move_played_error) AS bin_max
        FROM position_clusters
        WHERE cluster_id = ?
        GROUP BY bucket
        ORDER BY bucket
        """,
        [cluster_id],
    )

    return {"profile": summary, "error_distribution": distribution}


@router.get("/{cluster_id}/positions")
def cluster_positions(
    cluster_id:  int,
    traps_only:  bool = Query(False),
    limit:       int  = Query(20, le=MAX_ROWS),
    offset:      int  = Query(0,  ge=0),
):
    """Positions in a cluster, optionally filtered to trap positions (high error)."""
    trap_clause = "AND move_played_error >= 0.080" if traps_only else ""
    rows = q(
        f"""
        SELECT match_id, move_number, player_name,
               away_p1, away_p2, match_phase, decision_type,
               move_played_error, eval_equity
        FROM position_clusters
        WHERE cluster_id = ?
          {trap_clause}
        ORDER BY move_played_error DESC
        LIMIT ? OFFSET ?
        """,
        [cluster_id, limit, offset],
    )
    return {"positions": rows, "cluster_id": cluster_id,
            "traps_only": traps_only, "limit": limit, "offset": offset}


@router.get("/{cluster_id}/heuristics")
def cluster_heuristics(cluster_id: int, limit: int = Query(10, le=50)):
    """
    Heuristic rules applicable to this cluster (S3.4 heuristics.csv).
    Falls back to phase-based heuristics if no cluster-specific rules exist.
    """
    import csv
    from pathlib import Path
    from backend.config import HEURISTICS_FILE

    path = Path(HEURISTICS_FILE)
    if not path.exists():
        return {"heuristics": []}

    with open(path, newline="") as f:
        all_rules = list(csv.DictReader(f))

    # Filter by cluster_id, fall back to all rules if none found
    rules = [r for r in all_rules if str(r.get("cluster_id")) == str(cluster_id)]
    if not rules:
        # Get dominant phase for this cluster and filter by phase
        phase_row = q_one(
            "SELECT MODE(match_phase) AS phase FROM position_clusters WHERE cluster_id = ?",
            [cluster_id],
        )
        if phase_row:
            phase = str(phase_row.get("phase", ""))
            rules = [r for r in all_rules if str(r.get("match_phase")) == phase]
    return {"heuristics": rules[:limit], "cluster_id": cluster_id}
