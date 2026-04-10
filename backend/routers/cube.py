"""Cube decision helper endpoints (thresholds, gammon values, recommendations)."""
import csv
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException
from backend.config import THRESHOLDS_FILE, GAMMON_GV_FILE, HEURISTICS_FILE

router = APIRouter(prefix="/api/cube", tags=["cube"])


# ── Cached CSV loaders ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_thresholds() -> list[dict]:
    path = Path(THRESHOLDS_FILE)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _load_gammon_values() -> list[dict]:
    path = Path(GAMMON_GV_FILE)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _load_heuristics() -> list[dict]:
    path = Path(HEURISTICS_FILE)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/thresholds")
def cube_thresholds(
    away_p1:    int | None = Query(None, ge=1, le=25),
    away_p2:    int | None = Query(None, ge=1, le=25),
    cube_value: int | None = Query(None),
):
    """
    Empirical cube thresholds (S3.3).
    Without filters: full table for the heatmap display.
    With filters: single-row lookup for the cube helper calculator.
    """
    rows = _load_thresholds()
    if away_p1 is not None:
        rows = [r for r in rows if _int(r.get("away_p1")) == away_p1]
    if away_p2 is not None:
        rows = [r for r in rows if _int(r.get("away_p2")) == away_p2]
    if cube_value is not None:
        rows = [r for r in rows if _int(r.get("cube_value")) == cube_value]
    return {"thresholds": rows}


@router.get("/recommendation")
def cube_recommendation(
    away_p1:      int   = Query(..., ge=1, le=25),
    away_p2:      int   = Query(..., ge=1, le=25),
    cube_value:   int   = Query(1),
    equity:       float = Query(..., ge=-1.0, le=1.0),
    gammon_threat: float = Query(0.0, ge=0.0, le=1.0),
):
    """
    Recommend a cube action for given score + equity + gammon threat.
    Returns: action, distance to nearest threshold, gammon-adjusted action.
    """
    thresholds = _load_thresholds()
    match = next(
        (r for r in thresholds
         if _int(r.get("away_p1")) == away_p1
         and _int(r.get("away_p2")) == away_p2
         and _int(r.get("cube_value", 1)) == cube_value),
        None,
    )
    if not match:
        raise HTTPException(404, "No threshold data for this score/cube combination")

    double_thr = _float(match.get("double_threshold"))
    pass_thr   = _float(match.get("pass_threshold"))

    # Standard recommendation
    if equity < double_thr:
        action = "no_double"
        distance = double_thr - equity
    elif equity < pass_thr:
        action = "double_take"
        distance = min(equity - double_thr, pass_thr - equity)
    else:
        action = "double_pass"
        distance = equity - pass_thr

    # Gammon-adjusted: widen pass threshold proportionally
    gammon_adj_action = action
    if gammon_threat >= 0.30 and pass_thr is not None:
        adj_pass_thr = pass_thr + gammon_threat * 0.05
        if equity < adj_pass_thr:
            gammon_adj_action = "double_take"

    # Top-3 applicable heuristics
    heuristics = [
        h for h in _load_heuristics()
        if h.get("away_p1") == str(away_p1) or h.get("score_zone") == _score_zone(away_p1, away_p2)
    ][:3]

    return {
        "action":             action,
        "distance":           round(distance, 4),
        "double_threshold":   double_thr,
        "pass_threshold":     pass_thr,
        "gammon_adj_action":  gammon_adj_action,
        "heuristics":         heuristics,
    }


@router.get("/gammon-values")
def gammon_values(
    away_p1:    int | None = Query(None, ge=1, le=25),
    away_p2:    int | None = Query(None, ge=1, le=25),
    cube_value: int | None = Query(None),
):
    """Gammon values by score and cube (S3.5 + Kazaross reference)."""
    rows = _load_gammon_values()
    if away_p1 is not None:
        rows = [r for r in rows if _int(r.get("away_p1")) == away_p1]
    if away_p2 is not None:
        rows = [r for r in rows if _int(r.get("away_p2")) == away_p2]
    if cube_value is not None:
        rows = [r for r in rows if _int(r.get("cube_value")) == cube_value]
    return {"gammon_values": rows}


@router.get("/heuristics")
def cube_heuristics(
    away_p1: int | None = Query(None, ge=1, le=25),
    away_p2: int | None = Query(None, ge=1, le=25),
    limit:   int        = Query(10, le=50),
):
    """Practical heuristic rules relevant to a score position (S3.4)."""
    zone = _score_zone(away_p1, away_p2) if away_p1 and away_p2 else None
    rows = _load_heuristics()
    if zone:
        rows = [r for r in rows if r.get("score_zone") == zone or not r.get("score_zone")]
    return {"heuristics": rows[:limit]}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _score_zone(p1: int | None, p2: int | None) -> str:
    if p1 is None or p2 is None:
        return "unknown"
    m = max(p1, p2)
    if m <= 2:   return "dmp"
    if m <= 3:   return "gs"
    if m <= 6:   return "4-6away"
    if m <= 10:  return "7-10away"
    return "money"
