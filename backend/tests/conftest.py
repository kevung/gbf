"""Pytest fixtures — in-memory DuckDB with synthetic test data."""
import pytest
import duckdb
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def mem_conn():
    """In-memory DuckDB loaded with minimal synthetic data."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE positions AS
        SELECT
            'match_' || i::VARCHAR     AS match_id,
            i                          AS move_number,
            CASE WHEN i % 3 = 0 THEN 'Alice' ELSE 'Bob' END AS player_name,
            'Open 2024'                AS tournament,
            (i % 13) + 1               AS away_p1,
            (i % 11) + 1               AS away_p2,
            i % 3                      AS match_phase,
            CASE WHEN i % 2 = 0 THEN 'checker' ELSE 'cube' END AS decision_type,
            (i % 100) * 0.002          AS move_played_error,
            ((i % 200) - 100) * 0.01  AS eval_equity,
            i % 7                      AS cluster_id,
            (i % 5) + 5                AS match_length,
            CASE WHEN i % 5 = 0 THEN TRUE ELSE FALSE END AS is_missed_double,
            CASE WHEN i % 7 = 0 THEN TRUE ELSE FALSE END AS is_wrong_take,
            CASE WHEN i % 11 = 0 THEN TRUE ELSE FALSE END AS is_wrong_pass
        FROM range(1, 201) t(i)
    """)
    conn.execute("""
        CREATE TABLE player_profiles AS SELECT
            name AS player_name,
            50 AS total_games, 2000 AS total_positions,
            0.050 AS avg_error_checker, 0.060 AS avg_error_cube,
            0.05 AS blunder_rate,
            0.03 AS missed_double_rate, 0.02 AS wrong_take_rate,
            0.04 AS contact_error, 0.05 AS race_error, 0.03 AS bearoff_error
        FROM (VALUES ('Alice'), ('Bob')) t(name)
    """)
    conn.execute("""
        CREATE TABLE player_rankings_raw AS SELECT
            name AS player_name, n * 2.0 AS pr_rating, n AS pr_rank,
            n * 1.9 AS pr_ci_low, n * 2.1 AS pr_ci_high,
            n * 1.8 AS checker_rating, n * 2.2 AS cube_rating,
            n * 1.9 AS contact_rating, n * 2.0 AS race_rating, n * 1.7 AS bearoff_rating
        FROM (VALUES ('Alice', 1), ('Bob', 2)) t(name, n)
    """)
    conn.execute("""
        CREATE TABLE pos_clusters AS
        SELECT *, 'Archetype ' || cluster_id AS archetype_label FROM positions
    """)
    conn.execute("""
        CREATE TABLE matches AS SELECT DISTINCT match_id, tournament FROM positions
    """)
    conn.execute("""
        CREATE TABLE heatmap_cells AS
        SELECT away_p1, away_p2, match_length,
               COUNT(*) AS n_decisions,
               AVG(move_played_error) AS avg_error,
               0.0 AS std_error,
               AVG(CASE WHEN is_missed_double THEN 1.0 ELSE 0.0 END) AS missed_double_rate,
               AVG(CASE WHEN is_wrong_take    THEN 1.0 ELSE 0.0 END) AS wrong_take_rate,
               AVG(CASE WHEN is_wrong_pass    THEN 1.0 ELSE 0.0 END) AS wrong_pass_rate
        FROM positions WHERE decision_type = 'cube'
        GROUP BY away_p1, away_p2, match_length HAVING COUNT(*) >= 1
    """)
    conn.execute("""
        CREATE TABLE trajectory_graph AS SELECT
            'hash_' || i::VARCHAR AS position_hash,
            'match_' || i::VARCHAR AS match_id,
            i AS move_number,
            'Alice' AS player_name,
            0.04 AS move_played_error,
            'hash_' || (i+1)::VARCHAR AS next_position_hash
        FROM range(1, 21) t(i)
    """)
    conn.execute("""
        CREATE TABLE umap_positions AS SELECT
            'hash_' || i::VARCHAR AS position_hash,
            (i % 20) - 10.0       AS umap_x,
            (i % 15) - 7.5        AS umap_y,
            (i % 100) * 0.002     AS move_played_error,
            i % 3                 AS match_phase,
            i % 7                 AS cluster_id
        FROM range(1, 101) t(i)
    """)
    return conn


@pytest.fixture(scope="session")
def client(mem_conn, tmp_path_factory, monkeypatch_session):
    """FastAPI TestClient wired to the in-memory DuckDB."""
    import backend.db as db_module
    monkeypatch_session.setattr(db_module, "get_conn", lambda: mem_conn)

    from backend.main import app
    return TestClient(app)


@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session-scoped monkeypatch."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()
