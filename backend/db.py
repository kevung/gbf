"""DuckDB connection management.

One connection per thread (thread-local).  Views over Parquet files are
registered once on first use.  Pre-aggregated materialised tables live in
the persistent .duckdb file (written by materialise.py).
"""
import threading
import duckdb
from backend.config import (
    DB_PATH, POSITIONS_GLOB, CLUSTERS_FILE, PLAYERS_FILE,
    MATCHES_FILE, RANKINGS_FILE, HEATMAP_FILE,
    TRAJECTORIES_FILE, UMAP_FILE,
)

_local = threading.local()


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return the per-thread DuckDB connection, creating it if needed."""
    if not hasattr(_local, "conn"):
        _local.conn = _open()
    return _local.conn


def _open() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(DB_PATH), read_only=False)
    _register_views(conn)
    return conn


def _register_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Register read-only Parquet views (idempotent on reconnect)."""
    views = {
        "positions":      f"read_parquet('{POSITIONS_GLOB}')",
        "position_clusters": f"read_parquet('{CLUSTERS_FILE}')",
        "player_profiles": f"read_parquet('{PLAYERS_FILE}')",
        "matches":         f"read_parquet('{MATCHES_FILE}')",
        "player_rankings": f"read_parquet('{RANKINGS_FILE}')",
        "heatmap_cells":   f"read_parquet('{HEATMAP_FILE}')",
        "trajectory_graph": f"read_parquet('{TRAJECTORIES_FILE}')",
        "umap_positions":  f"read_parquet('{UMAP_FILE}')",
    }
    for name, source in views.items():
        conn.execute(
            f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {source}"
        )


def q(sql: str, params: list | None = None) -> list[dict]:
    """Execute a query and return rows as list of dicts."""
    conn  = get_conn()
    cur   = conn.execute(sql, params or [])
    cols  = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def q_one(sql: str, params: list | None = None) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None
