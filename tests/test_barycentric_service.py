"""Tests for BE.4 — barycentric_service.py

Schema conformance and numeric invariant checks against a tiny synthetic
dataset: 20 positions across 2 matches, 2 games each, 3 score cells.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Patch _paths before importing the app so the lifespan can pick them up.
import barycentric_service as svc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture data builders
# ---------------------------------------------------------------------------

CELLS = [
    (3, 3, "normal"),
    (5, 5, "normal"),
    (7, 7, "normal"),
]
MATCH_IDS = ["match_A", "match_B", "match_C"]
N_GAMES = 2
N_MOVES = 5  # moves per game


def _cell_id(a: int, b: int, variant: str) -> str:
    return f"a{a}_b{b}_{variant}"


def _make_bary() -> pl.DataFrame:
    rows = []
    pos_idx = 0
    for match_idx, match_id in enumerate(MATCH_IDS):
        # Spread matches across all cells so each cell has data
        cell = CELLS[match_idx % len(CELLS)]
        a, b, variant = cell
        for game_num in range(1, N_GAMES + 1):
            game_id = f"{match_id}_game_{game_num:02d}"
            for move in range(1, N_MOVES + 1):
                pid = f"pos_{pos_idx:03d}"
                rows.append({
                    "position_id": pid,
                    "game_id": game_id,
                    "game_number": game_num,
                    "move_number": move,
                    "player_on_roll": 1 + (move % 2),
                    "score_away_p1": a,
                    "score_away_p2": b,
                    "cube_value": 1,
                    "crawford": False,
                    "is_post_crawford": False,
                    "bary_p1_a": float(a) + 0.1 * move,
                    "bary_p1_b": float(b) + 0.05 * move,
                    "disp_p1_a": -1.0 - 0.1 * move,
                    "disp_p1_b": -0.9 - 0.05 * move,
                    "disp_magnitude_p1": 1.3,
                    "cubeless_mwc_p1": 0.45 + 0.01 * move,
                    "cubeless_equity_p1": -0.1 + 0.02 * move,
                    "cubeful_equity_p1": -0.08 + 0.02 * move,
                    "cube_gap_p1": 0.02,
                    "match_id": match_id,
                    "decision_type": "checker",
                    "move_played_error": 0.005 * move,
                })
                pos_idx += 1
    return pl.DataFrame(rows)


def _make_cell_keys() -> pl.DataFrame:
    rows = []
    for a, b, v in CELLS:
        label = f"{a}a-{b}a"
        rows.append({
            "cell_id": _cell_id(a, b, v),
            "score_away_p1": a,
            "score_away_p2": b,
            "crawford_variant": v,
            "display_label": label,
            "is_one_away": False,
        })
    return pl.DataFrame(rows)


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _make_bootstrap_cells(cell_keys: pl.DataFrame, bary: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for row in cell_keys.iter_rows(named=True):
        cid = row["cell_id"]
        a, b = row["score_away_p1"], row["score_away_p2"]
        subset = bary.filter(
            (pl.col("score_away_p1") == a) & (pl.col("score_away_p2") == b)
        )
        n = len(subset)
        rows.append({
            "cell_id": cid,
            "score_away_p1": a,
            "score_away_p2": b,
            "crawford_variant": row["crawford_variant"],
            "sampling_mode": "stratified",
            "n_total": n,
            "n_draws": 50,
            "draw_size": 500000,
            "mean_n_in_draw": float(n),
            "low_support": n < 50,
            "mean_bary_p1_a_mean": _f(subset["bary_p1_a"].mean()),
            "mean_bary_p1_a_std": _f(subset["bary_p1_a"].std()),
            "mean_bary_p1_a_p05": _f(subset["bary_p1_a"].quantile(0.05)),
            "mean_bary_p1_a_p95": _f(subset["bary_p1_a"].quantile(0.95)),
            "mean_bary_p1_b_mean": _f(subset["bary_p1_b"].mean()),
            "mean_bary_p1_b_std": _f(subset["bary_p1_b"].std()),
            "mean_bary_p1_b_p05": _f(subset["bary_p1_b"].quantile(0.05)),
            "mean_bary_p1_b_p95": _f(subset["bary_p1_b"].quantile(0.95)),
            "mean_disp_p1_a_mean": _f(subset["disp_p1_a"].mean()),
            "mean_disp_p1_a_std": 0.0,
            "mean_disp_p1_a_p05": 0.0,
            "mean_disp_p1_a_p95": 0.0,
            "mean_disp_p1_b_mean": _f(subset["disp_p1_b"].mean()),
            "mean_disp_p1_b_std": 0.0,
            "mean_disp_p1_b_p05": 0.0,
            "mean_disp_p1_b_p95": 0.0,
            "mean_disp_magnitude_p1_mean": 1.3,
            "mean_disp_magnitude_p1_std": 0.0,
            "mean_disp_magnitude_p1_p05": 0.0,
            "mean_disp_magnitude_p1_p95": 0.0,
            "mean_cubeless_mwc_p1_mean": _f(subset["cubeless_mwc_p1"].mean()),
            "mean_cubeless_mwc_p1_std": _f(subset["cubeless_mwc_p1"].std()),
            "mean_cubeless_mwc_p1_p05": _f(subset["cubeless_mwc_p1"].quantile(0.05)),
            "mean_cubeless_mwc_p1_p95": _f(subset["cubeless_mwc_p1"].quantile(0.95)),
            "mean_cubeless_equity_p1_mean": 0.0,
            "mean_cubeless_equity_p1_std": 0.0,
            "mean_cubeless_equity_p1_p05": 0.0,
            "mean_cubeless_equity_p1_p95": 0.0,
            "mean_cubeful_equity_p1_mean": 0.0,
            "mean_cubeful_equity_p1_std": 0.0,
            "mean_cubeful_equity_p1_p05": 0.0,
            "mean_cubeful_equity_p1_p95": 0.0,
            "mean_cube_gap_p1_mean": _f(subset["cube_gap_p1"].mean()),
            "mean_cube_gap_p1_std": _f(subset["cube_gap_p1"].std()),
            "mean_cube_gap_p1_p05": _f(subset["cube_gap_p1"].quantile(0.05)),
            "mean_cube_gap_p1_p95": _f(subset["cube_gap_p1"].quantile(0.95)),
            "cov_bary_p1_ab_mean": 0.001,
            "cov_bary_p1_ab_std": 0.0,
        })
    return pl.DataFrame(rows)


def _make_pos_enriched(bary: pl.DataFrame) -> pl.DataFrame:
    return bary.select("position_id", "decision_type", "move_played_error").with_columns([
        pl.lit(None).cast(pl.List(pl.Int32)).alias("board_p1"),
        pl.lit(None).cast(pl.List(pl.Int32)).alias("board_p2"),
        pl.lit(None).cast(pl.List(pl.Int32)).alias("dice"),
        pl.lit(0.5).alias("eval_win"),
        pl.lit(0.1).alias("eval_win_g"),
        pl.lit(0.01).alias("eval_win_bg"),
        pl.lit(0.08).alias("eval_lose_g"),
        pl.lit(0.005).alias("eval_lose_bg"),
        pl.lit(0.0).alias("eval_equity"),
        pl.lit("13/9 13/10").alias("move_played"),
        pl.lit("13/9 13/10").alias("best_move"),
        pl.lit(None).cast(pl.Utf8).alias("cube_action_played"),
        pl.lit(None).cast(pl.Utf8).alias("cube_action_optimal"),
        pl.lit(167).alias("pip_count_p1"),
        pl.lit(167).alias("pip_count_p2"),
    ])


def _make_games(bary: pl.DataFrame) -> pl.DataFrame:
    return (
        bary.select("game_id", "match_id", "game_number")
        .unique()
        .sort(["match_id", "game_number"])
    )


def _make_matches() -> pl.DataFrame:
    return pl.DataFrame({
        "match_id": MATCH_IDS,
        "match_length": [11, 9, 7],
        "player1": ["Alice", "Carol", "Eve"],
        "player2": ["Bob", "Dave", "Frank"],
    })


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("parquet")

    bary = _make_bary()
    cell_keys = _make_cell_keys()
    boot = _make_bootstrap_cells(cell_keys, bary)
    pos_enriched = _make_pos_enriched(bary)
    games = _make_games(bary)
    matches = _make_matches()

    bary.write_parquet(d / "barycentric_v2.parquet")
    cell_keys.write_parquet(d / "cell_keys.parquet")
    boot.write_parquet(d / "bootstrap_cells.parquet")
    enriched_dir = d / "enriched"
    enriched_dir.mkdir()
    pos_enriched.write_parquet(enriched_dir / "part-0.parquet")
    games.write_parquet(d / "games.parquet")
    matches.write_parquet(d / "matches.parquet")

    return d


@pytest.fixture(scope="session")
def client(fixture_dir):
    from fastapi.testclient import TestClient

    svc._paths.update({
        "bary":     str(fixture_dir / "barycentric_v2.parquet"),
        "cells":    str(fixture_dir / "cell_keys.parquet"),
        "boot":     str(fixture_dir / "bootstrap_cells.parquet"),
        "enriched": str(fixture_dir / "enriched" / "*.parquet"),
        "games":    str(fixture_dir / "games.parquet"),
        "matches":  str(fixture_dir / "matches.parquet"),
    })
    with TestClient(svc.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests — /cells
# ---------------------------------------------------------------------------

class TestCells:
    def test_bootstrap_returns_cells(self, client):
        r = client.get("/api/bary/cells?sampling=bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert "cells" in body
        assert len(body["cells"]) > 0

    def test_bootstrap_cell_schema(self, client):
        r = client.get("/api/bary/cells?sampling=bootstrap")
        cell = r.json()["cells"][0]
        required = {
            "cell_id", "score_away_p1", "score_away_p2", "crawford_variant",
            "display_label", "n_total",
            "mean_bary_p1_a", "std_bary_p1_a",
            "mean_bary_p1_b", "std_bary_p1_b",
            "cov_bary_p1_ab_mean",
            "mean_disp_p1_a", "mean_disp_p1_b",
            "mean_mwc_p1", "std_mwc_p1",
            "mean_cube_gap_p1", "std_cube_gap_p1",
            "low_support",
        }
        assert required <= set(cell.keys()), f"missing keys: {required - set(cell.keys())}"

    def test_raw_matches_polars_groupby(self, client, fixture_dir):
        r = client.get("/api/bary/cells?sampling=raw")
        assert r.status_code == 200
        api_cells = {c["cell_id"]: c for c in r.json()["cells"]}

        bary = pl.read_parquet(fixture_dir / "barycentric_v2.parquet")
        bary = bary.with_columns(pl.lit("normal").alias("crawford_variant"))
        grouped = (
            bary.group_by(["score_away_p1", "score_away_p2"])
            .agg(
                pl.col("bary_p1_a").mean().alias("mean_bary_p1_a"),
                pl.col("cubeless_mwc_p1").mean().alias("mean_mwc_p1"),
                pl.len().alias("n_total"),
            )
        )
        for row in grouped.iter_rows(named=True):
            cid = _cell_id(row["score_away_p1"], row["score_away_p2"], "normal")
            if cid not in api_cells:
                continue
            api = api_cells[cid]
            assert abs(api["mean_bary_p1_a"] - row["mean_bary_p1_a"]) < 1e-4
            assert api["n_total"] == row["n_total"]

    def test_variant_filter(self, client):
        r = client.get("/api/bary/cells?sampling=bootstrap&variant=normal")
        assert r.status_code == 200
        for cell in r.json()["cells"]:
            assert cell["crawford_variant"] == "normal"

    def test_invalid_sampling(self, client):
        r = client.get("/api/bary/cells?sampling=bogus")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests — /scatter
# ---------------------------------------------------------------------------

class TestScatter:
    def test_global_scatter_schema(self, client):
        r = client.get("/api/bary/scatter?mode=global&per_cell=5")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "global"
        assert "points" in body
        assert len(body["points"]) > 0
        pt = body["points"][0]
        for k in ("position_id", "bary_p1_a", "bary_p1_b", "mwc_p1",
                  "cube_gap_p1", "score_away_p1", "score_away_p2", "crawford_variant"):
            assert k in pt

    def test_global_scatter_per_cell_limit(self, client):
        per_cell = 3
        r = client.get(f"/api/bary/scatter?mode=global&per_cell={per_cell}")
        body = r.json()
        n_cells = len(CELLS)
        assert len(body["points"]) <= n_cells * per_cell

    def test_cell_mode_requires_cell_id(self, client):
        r = client.get("/api/bary/scatter?mode=cell")
        assert r.status_code == 400

    def test_cell_mode_filters_to_cell(self, client):
        cid = _cell_id(*CELLS[0])
        r = client.get(f"/api/bary/scatter?mode=cell&cell_id={cid}&limit=100")
        assert r.status_code == 200
        for pt in r.json()["points"]:
            assert pt["score_away_p1"] == CELLS[0][0]
            assert pt["score_away_p2"] == CELLS[0][1]

    def test_invalid_mode(self, client):
        r = client.get("/api/bary/scatter?mode=xyz")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests — /select
# ---------------------------------------------------------------------------

class TestSelect:
    def test_rectangle_returns_inside_points(self, client):
        # All bary_p1_a values start at a + 0.1 (= 3.1 .. 3.5 for cell (3,3))
        body = {
            "rect": {"x0": 2.0, "y0": 2.0, "x1": 10.0, "y1": 10.0},
        }
        r = client.post("/api/bary/select", json=body)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data and "returned" in data and "positions" in data
        rect = body["rect"]
        for pos in data["positions"]:
            assert rect["x0"] <= pos["bary_p1_b"] <= rect["x1"]
            assert rect["y0"] <= pos["bary_p1_a"] <= rect["y1"]

    def test_tight_rectangle_excludes_outside(self, client):
        # bary_p1_a for cell(3,3) moves 1 is 3.1 — use tight rect to exclude nothing
        body = {"rect": {"x0": 99.0, "y0": 99.0, "x1": 100.0, "y1": 100.0}}
        r = client.post("/api/bary/select", json=body)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_sorted_by_move_played_error_desc(self, client):
        body = {
            "rect": {"x0": 0.0, "y0": 0.0, "x1": 20.0, "y1": 20.0},
            "sort": {"field": "move_played_error", "order": "desc"},
        }
        r = client.post("/api/bary/select", json=body)
        errors = [p["move_played_error"] for p in r.json()["positions"] if p["move_played_error"] is not None]
        assert errors == sorted(errors, reverse=True)

    def test_position_schema(self, client):
        body = {"rect": {"x0": 0.0, "y0": 0.0, "x1": 20.0, "y1": 20.0}, "limit": 1}
        r = client.post("/api/bary/select", json=body)
        pos = r.json()["positions"][0]
        for k in ("position_id", "game_id", "match_id", "move_number",
                  "score_away_p1", "score_away_p2", "bary_p1_a", "bary_p1_b"):
            assert k in pos, f"missing key: {k}"

    def test_invalid_sort_field(self, client):
        body = {
            "rect": {"x0": 0.0, "y0": 0.0, "x1": 20.0, "y1": 20.0},
            "sort": {"field": "injected_field; DROP TABLE bary", "order": "asc"},
        }
        r = client.post("/api/bary/select", json=body)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests — /match/{position_id}
# ---------------------------------------------------------------------------

class TestMatch:
    def test_returns_full_trajectory(self, client):
        r = client.get("/api/bary/match/pos_000")
        assert r.status_code == 200
        body = r.json()
        assert body["match_id"] == "match_A"
        assert "positions" in body
        assert len(body["positions"]) == N_GAMES * N_MOVES

    def test_ordered_by_game_then_move(self, client):
        r = client.get("/api/bary/match/pos_000")
        positions = r.json()["positions"]
        pairs = [(p["game_number"], p["move_number"]) for p in positions]
        assert pairs == sorted(pairs)

    def test_match_metadata_present(self, client):
        r = client.get("/api/bary/match/pos_000")
        body = r.json()
        assert "players" in body
        assert "match_length" in body

    def test_unknown_position_404(self, client):
        r = client.get("/api/bary/match/does_not_exist")
        assert r.status_code == 404

    def test_match_cache_warm(self, client):
        r1 = client.get("/api/bary/match/pos_000")
        r2 = client.get("/api/bary/match/pos_000")
        assert r1.json() == r2.json()


# ---------------------------------------------------------------------------
# Tests — /position/{position_id}
# ---------------------------------------------------------------------------

class TestPosition:
    def test_returns_detail(self, client):
        r = client.get("/api/bary/position/pos_000")
        assert r.status_code == 200
        body = r.json()
        assert body["position_id"] == "pos_000"
        assert "context" in body
        ctx = body["context"]
        for k in ("bary_p1_a", "bary_p1_b", "mwc_p1", "cube_gap_p1",
                  "crawford_variant", "match_id", "game_id"):
            assert k in ctx

    def test_unknown_position_404(self, client):
        r = client.get("/api/bary/position/does_not_exist")
        assert r.status_code == 404
