"""Global statistics and ranking endpoints."""
import json
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter, Query
from backend.db import q, q_one
from backend.config import STATS_FILE, TEMPORAL_FILE, OVERUNDER_FILE, MAX_ROWS

router = APIRouter(prefix="/api/stats", tags=["stats"])

_VALID_METRICS = {
    "pr", "checker", "cube", "contact", "race", "bearoff",
    "gammon", "consistency",
}


@lru_cache(maxsize=1)
def _load_overview() -> dict:
    path = Path(STATS_FILE)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_temporal() -> list[dict]:
    import csv
    path = Path(TEMPORAL_FILE)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _load_overunder() -> list[dict]:
    import csv
    path = Path(OVERUNDER_FILE)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@router.get("/overview")
def overview():
    """High-level dataset statistics (S1.1 descriptive_stats.json)."""
    base = _load_overview()
    live = q_one(
        """
        SELECT COUNT(*) AS total_positions,
               AVG(move_played_error) AS avg_error,
               AVG(CASE WHEN move_played_error >= 0.080 THEN 1.0 ELSE 0.0 END)
                   AS blunder_rate
        FROM positions
        """
    )
    return {**base, **(live or {})}


@router.get("/error-distribution")
def error_distribution(
    decision_type: str | None = Query(None),
    bins:          int        = Query(40, ge=5, le=200),
):
    """
    Histogram of move_played_error.
    Returns bin edges + counts; frontend renders with D3.
    """
    dt_clause = ""
    params: list = []
    if decision_type:
        dt_clause = "WHERE lower(decision_type) = lower(?)"
        params.append(decision_type)

    rows = q(
        f"""
        SELECT width_bucket(move_played_error, 0.0, 2.0, ?) AS bucket,
               COUNT(*) AS count,
               MIN(move_played_error) AS bin_min,
               MAX(move_played_error) AS bin_max
        FROM positions
        {dt_clause}
        GROUP BY bucket
        ORDER BY bucket
        """,
        [bins, *params],
    )
    return {"bins": rows, "decision_type": decision_type}


@router.get("/rankings")
def rankings(
    metric: str = Query("pr", pattern=r"^[a-z_]+$"),
    limit:  int = Query(50, le=MAX_ROWS),
    offset: int = Query(0,  ge=0),
    search: str = Query("", max_length=100),
):
    """Pre-ranked player list (S2.3 player_ranking.parquet)."""
    if metric not in _VALID_METRICS:
        metric = "pr"

    col_map = {
        "pr":          "pr_rating",
        "checker":     "checker_rating",
        "cube":        "cube_rating",
        "contact":     "contact_rating",
        "race":        "race_rating",
        "bearoff":     "bearoff_rating",
        "gammon":      "gammon_rating",
        "consistency": "consistency_rating",
    }
    col = col_map.get(metric, "pr_rating")

    search_clause = ""
    params: list = [limit, offset]
    if search:
        search_clause = "WHERE lower(player_name) LIKE lower(?)"
        params = [f"%{search}%"] + params

    rows = q(
        f"""
        SELECT player_name, {col} AS rating, pr_rating, pr_rank,
               total_games, blunder_rate
        FROM player_rankings
        {search_clause}
        ORDER BY {col} ASC NULLS LAST
        LIMIT ? OFFSET ?
        """,
        params,
    )
    return {"rankings": rows, "metric": metric, "limit": limit, "offset": offset}


@router.get("/temporal")
def temporal(
    metric: str = Query("avg_error", pattern=r"^[a-z_]+$"),
):
    """Year-by-year trend (S1.7 temporal_series.csv)."""
    rows = _load_temporal()
    if metric != "avg_error":
        rows = [r for r in rows if r.get("metric") == metric]
    return {"series": rows, "metric": metric}


@router.get("/over-under-performers")
def over_under_performers(limit: int = Query(20, le=MAX_ROWS)):
    """Players performing better/worse than expected for their PR (S2.3)."""
    rows = _load_overunder()
    return {"performers": rows[:limit]}
