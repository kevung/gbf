"""Functional tests for all API routers using in-memory DuckDB."""
import pytest
from fastapi.testclient import TestClient
import duckdb

import backend.db as db_module
from backend.main import app


# ── Fixture: patch db.get_conn with in-memory data ───────────────────────────

@pytest.fixture(scope="module")
def conn():
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE positions AS SELECT
            'm' || i::VARCHAR AS match_id, i AS move_number,
            CASE WHEN i%2=0 THEN 'Alice' ELSE 'Bob' END AS player_name,
            'Aachen 2024' AS tournament,
            (i%13)+1 AS away_p1, (i%11)+1 AS away_p2, i%3 AS match_phase,
            CASE WHEN i%2=0 THEN 'checker' ELSE 'cube' END AS decision_type,
            (i%100)*0.002 AS move_played_error,
            ((i%200)-100)*0.01 AS eval_equity, i%7 AS cluster_id,
            (i%5)+5 AS match_length,
            i%5=0 AS is_missed_double, i%7=0 AS is_wrong_take, i%11=0 AS is_wrong_pass
        FROM range(1,101) t(i)
    """)
    c.execute("""
        CREATE TABLE player_profiles AS SELECT
            n AS player_name, 50 AS total_games, 1000 AS total_positions,
            0.05 AS avg_error_checker, 0.06 AS avg_error_cube, 0.05 AS blunder_rate,
            0.03 AS missed_double_rate, 0.02 AS wrong_take_rate,
            0.04 AS contact_error, 0.05 AS race_error, 0.03 AS bearoff_error
        FROM (VALUES ('Alice'), ('Bob')) t(n)
    """)
    c.execute("""
        CREATE TABLE player_rankings_raw AS SELECT
            n AS player_name, rk*2.0 AS pr_rating, rk AS pr_rank,
            rk*1.9 AS pr_ci_low, rk*2.1 AS pr_ci_high,
            rk*1.8 AS checker_rating, rk*2.2 AS cube_rating,
            rk*1.9 AS contact_rating, rk*2.0 AS race_rating, rk*1.7 AS bearoff_rating
        FROM (VALUES ('Alice',1),('Bob',2)) t(n,rk)
    """)
    c.execute("CREATE TABLE pos_clusters AS SELECT *, 'Archetype '||cluster_id AS archetype_label FROM positions")
    c.execute("CREATE TABLE matches AS SELECT DISTINCT match_id, tournament FROM positions")
    c.execute("""
        CREATE TABLE heatmap_cells AS
        SELECT away_p1, away_p2, match_length,
               COUNT(*) AS n_decisions, AVG(move_played_error) AS avg_error,
               0.0 AS std_error,
               AVG(CASE WHEN is_missed_double THEN 1.0 ELSE 0.0 END) AS missed_double_rate,
               AVG(CASE WHEN is_wrong_take THEN 1.0 ELSE 0.0 END) AS wrong_take_rate,
               AVG(CASE WHEN is_wrong_pass THEN 1.0 ELSE 0.0 END) AS wrong_pass_rate
        FROM positions WHERE decision_type='cube'
        GROUP BY away_p1, away_p2, match_length HAVING COUNT(*)>=1
    """)
    c.execute("""
        CREATE TABLE trajectory_graph AS SELECT
            'h'||i::VARCHAR AS position_hash, 'm'||i::VARCHAR AS match_id,
            i AS move_number, 'Alice' AS player_name, 0.04 AS move_played_error,
            'h'||(i+1)::VARCHAR AS next_position_hash
        FROM range(1,11) t(i)
    """)
    c.execute("""
        CREATE TABLE umap_positions AS SELECT
            'h'||i::VARCHAR AS position_hash,
            (i%20)-10.0 AS umap_x, (i%15)-7.5 AS umap_y,
            (i%100)*0.002 AS move_played_error, i%3 AS match_phase, i%7 AS cluster_id
        FROM range(1,51) t(i)
    """)
    return c


@pytest.fixture(scope="module")
def client(conn, monkeypatch_module):
    monkeypatch_module.setattr(db_module, "get_conn", lambda: conn)
    return TestClient(app)


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ── Health ─────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Players ────────────────────────────────────────────────────────────────────

def test_players_list(client):
    r = client.get("/api/players")
    assert r.status_code == 200
    data = r.json()
    assert "players" in data
    assert len(data["players"]) >= 1

def test_players_search(client):
    r = client.get("/api/players?search=Alice")
    assert r.status_code == 200
    names = [p["player_name"] for p in r.json()["players"]]
    assert all("alice" in n.lower() for n in names)

def test_player_profile(client):
    r = client.get("/api/players/Alice/profile")
    assert r.status_code == 200
    assert r.json()["player_name"] == "Alice"

def test_player_profile_not_found(client):
    r = client.get("/api/players/NoSuchPlayer/profile")
    assert r.status_code == 404

def test_players_compare(client):
    r = client.get("/api/players/compare?p1=Alice&p2=Bob")
    assert r.status_code == 200
    data = r.json()
    assert "p1" in data and "p2" in data

def test_player_positions(client):
    r = client.get("/api/players/Alice/positions?limit=10")
    assert r.status_code == 200
    assert "positions" in r.json()


# ── Heatmap ────────────────────────────────────────────────────────────────────

def test_heatmap_global(client):
    r = client.get("/api/heatmap/cube-error")
    assert r.status_code == 200
    assert "cells" in r.json()

def test_heatmap_by_length(client):
    r = client.get("/api/heatmap/cube-error?match_length=7")
    assert r.status_code == 200

def test_heatmap_cell(client):
    r = client.get("/api/heatmap/cube-error/cell?away_p1=3&away_p2=3")
    assert r.status_code == 200
    assert "top_positions" in r.json()


# ── Positions ──────────────────────────────────────────────────────────────────

def test_positions_search(client):
    r = client.get("/api/positions?limit=20")
    assert r.status_code == 200
    data = r.json()
    assert len(data["positions"]) <= 20

def test_positions_blunders_only(client):
    r = client.get("/api/positions?blunders_only=true&limit=50")
    assert r.status_code == 200
    for pos in r.json()["positions"]:
        assert pos["move_played_error"] >= 0.080

def test_positions_filter_phase(client):
    r = client.get("/api/positions?phase=contact&limit=20")
    assert r.status_code == 200
    for pos in r.json()["positions"]:
        assert pos["match_phase"] == 0


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_overview(client):
    r = client.get("/api/stats/overview")
    assert r.status_code == 200
    data = r.json()
    assert "total_positions" in data or "avg_error" in data

def test_stats_rankings(client):
    r = client.get("/api/stats/rankings?metric=pr&limit=10")
    assert r.status_code == 200
    assert "rankings" in r.json()

def test_stats_error_distribution(client):
    r = client.get("/api/stats/error-distribution")
    assert r.status_code == 200
    assert "bins" in r.json()

def test_tournaments_list(client):
    r = client.get("/api/tournaments")
    assert r.status_code == 200
    assert "tournaments" in r.json()


# ── Clusters ───────────────────────────────────────────────────────────────────

def test_clusters_list(client):
    r = client.get("/api/clusters")
    assert r.status_code == 200
    clusters = r.json()["clusters"]
    assert len(clusters) >= 1

def test_cluster_profile(client):
    cid = client.get("/api/clusters").json()["clusters"][0]["cluster_id"]
    r = client.get(f"/api/clusters/{cid}/profile")
    assert r.status_code == 200
    assert "profile" in r.json()

def test_cluster_positions(client):
    cid = client.get("/api/clusters").json()["clusters"][0]["cluster_id"]
    r = client.get(f"/api/clusters/{cid}/positions?limit=5")
    assert r.status_code == 200
    assert len(r.json()["positions"]) <= 5


# ── Map / trajectories ─────────────────────────────────────────────────────────

def test_map_points(client):
    r = client.get("/api/map/points?x_min=-10&x_max=10&y_min=-10&y_max=10")
    assert r.status_code == 200
    assert "points" in r.json()

def test_map_hexbins(client):
    r = client.get("/api/map/hexbins?x_min=-10&x_max=10&y_min=-10&y_max=10&resolution=5")
    assert r.status_code == 200
    assert "hexbins" in r.json()

def test_trajectories(client):
    r = client.get("/api/trajectories/h1")
    assert r.status_code == 200
    assert "trajectories" in r.json()

def test_trajectory_detail(client):
    r = client.get("/api/trajectories/h1/detail")
    assert r.status_code == 200
    assert "stats" in r.json()
