"""S0.3 — DuckDB access layer for the backgammon mining study pipeline.

BGDatabase wraps DuckDB queries on Parquet files produced by S0.2.
DuckDB reads Parquet directly — no data loaded into RAM.

Usage::

    from bgdata import BGDatabase

    db = BGDatabase("data/parquet")
    print(db.summary())

    df = db.query("SELECT player1, COUNT(*) FROM matches GROUP BY 1 ORDER BY 2 DESC")
    df = db.get_positions({"decision_type": "checker", "eval_win": (0.45, 0.55)})
    stats = db.get_player_stats("Kévin Unger")
    print(db.get_match("27140e69adf32826"))

Dependencies:
    pip install duckdb polars
"""

from __future__ import annotations

import functools
import textwrap
from pathlib import Path
from typing import Any

import duckdb
import polars as pl


class BGDatabase:
    """DuckDB-backed query interface over S0.2 Parquet files.

    Parameters
    ----------
    data_dir:
        Directory containing matches.parquet, games.parquet, and
        positions/ as produced by scripts/convert_jsonl_to_parquet.py.
    cache_size:
        Number of query results to keep in the LRU cache (0 = disabled).
    """

    def __init__(self, data_dir: str | Path, cache_size: int = 64):
        self._dir = Path(data_dir)
        self._conn = duckdb.connect()
        self._cache_size = cache_size
        self._cache: dict[str, pl.DataFrame] = {}
        self._cache_order: list[str] = []
        self._register_views()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register_views(self):
        """Register Parquet files as DuckDB views."""
        matches_path = self._dir / "matches.parquet"
        games_path = self._dir / "games.parquet"
        positions_glob = str(self._dir / "positions" / "part-*.parquet")

        if matches_path.exists():
            self._conn.execute(
                f"CREATE OR REPLACE VIEW matches AS SELECT * FROM read_parquet('{matches_path}')"
            )
        if games_path.exists():
            self._conn.execute(
                f"CREATE OR REPLACE VIEW games AS SELECT * FROM read_parquet('{games_path}')"
            )
        pos_files = list((self._dir / "positions").glob("part-*.parquet"))
        if pos_files:
            self._conn.execute(
                f"CREATE OR REPLACE VIEW positions AS SELECT * FROM read_parquet('{positions_glob}')"
            )

    def _lru_get(self, key: str) -> pl.DataFrame | None:
        return self._cache.get(key)

    def _lru_put(self, key: str, df: pl.DataFrame):
        if self._cache_size <= 0:
            return
        if key in self._cache:
            self._cache_order.remove(key)
        elif len(self._cache) >= self._cache_size:
            oldest = self._cache_order.pop(0)
            del self._cache[oldest]
        self._cache[key] = df
        self._cache_order.append(key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, sql: str, cache: bool = False) -> pl.DataFrame:
        """Execute arbitrary SQL and return a Polars DataFrame.

        Parameters
        ----------
        sql:
            DuckDB SQL query. Views available: ``matches``, ``games``,
            ``positions``.
        cache:
            Cache this result by SQL text (LRU, evicts when full).
        """
        if cache:
            cached = self._lru_get(sql)
            if cached is not None:
                return cached
        result = self._conn.execute(sql).pl()
        if cache:
            self._lru_put(sql, result)
        return result

    def get_match(self, match_id: str) -> dict[str, Any]:
        """Return match metadata + games as a dict.

        Returns an empty dict if the match_id is not found.
        """
        sql = f"SELECT * FROM matches WHERE match_id = '{match_id}'"
        df = self.query(sql)
        if df.is_empty():
            return {}
        record = df.to_dicts()[0]

        games_sql = f"SELECT * FROM games WHERE match_id = '{match_id}' ORDER BY game_number"
        record["games"] = self.query(games_sql).to_dicts()
        return record

    def get_positions(self, filters: dict[str, Any] | None = None) -> pl.DataFrame:
        """Return positions matching the given filters.

        Filter values can be:
        - scalar: exact match (``{"decision_type": "checker"}``)
        - 2-tuple: inclusive range (``{"eval_win": (0.45, 0.55)}``)
        - list: IN clause (``{"cube_owner": [1, 2]}``)

        Parameters
        ----------
        filters:
            Column → value mapping. All conditions are ANDed.
        """
        where_clauses = []
        if filters:
            for col, val in filters.items():
                if isinstance(val, tuple) and len(val) == 2:
                    lo, hi = val
                    where_clauses.append(f"{col} BETWEEN {lo} AND {hi}")
                elif isinstance(val, list):
                    items = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in val)
                    where_clauses.append(f"{col} IN ({items})")
                elif isinstance(val, str):
                    where_clauses.append(f"{col} = '{val}'")
                else:
                    where_clauses.append(f"{col} = {val}")

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT * FROM positions {where} LIMIT 100000"
        return self.query(sql)

    def get_player_stats(self, player_name: str) -> dict[str, Any]:
        """Return per-player aggregated statistics.

        Covers both player1 and player2 columns in matches.
        """
        sql = textwrap.dedent(f"""
            WITH player_matches AS (
                SELECT match_id, match_length, winner,
                       1 AS side, score_final_p1 AS score, score_final_p2 AS opp_score
                FROM matches WHERE player1 = '{player_name}'
                UNION ALL
                SELECT match_id, match_length, winner,
                       2 AS side, score_final_p2 AS score, score_final_p1 AS opp_score
                FROM matches WHERE player2 = '{player_name}'
            ),
            player_games AS (
                SELECT g.match_id, g.winner AS game_winner, g.points_won,
                       g.gammon, g.backgammon, pm.side
                FROM games g
                JOIN player_matches pm ON pm.match_id = g.match_id
            )
            SELECT
                COUNT(DISTINCT pm.match_id) AS num_matches,
                SUM(CASE WHEN pm.winner = pm.side THEN 1 ELSE 0 END) AS matches_won,
                COUNT(pg.match_id) AS num_games,
                SUM(CASE WHEN pg.game_winner = pg.side THEN 1 ELSE 0 END) AS games_won,
                SUM(CASE WHEN pg.gammon AND pg.game_winner = pg.side THEN 1 ELSE 0 END) AS gammons_won,
                SUM(CASE WHEN pg.backgammon AND pg.game_winner = pg.side THEN 1 ELSE 0 END) AS backgammons_won
            FROM player_matches pm
            LEFT JOIN player_games pg ON pg.match_id = pm.match_id
        """)
        df = self.query(sql)
        stats = df.to_dicts()[0] if not df.is_empty() else {}
        stats["player"] = player_name

        # Average error from positions.
        error_sql = textwrap.dedent(f"""
            SELECT
                COUNT(*) AS num_positions,
                AVG(move_played_error) AS avg_error,
                AVG(CASE WHEN move_played_error > 0.1 THEN 1.0 ELSE 0.0 END) AS blunder_rate
            FROM positions p
            JOIN games g ON g.game_id = p.game_id
            JOIN matches m ON m.match_id = g.match_id
            WHERE (m.player1 = '{player_name}' AND p.player_on_roll = 1)
               OR (m.player2 = '{player_name}' AND p.player_on_roll = 2)
        """)
        err_df = self.query(error_sql)
        if not err_df.is_empty():
            stats.update(err_df.to_dicts()[0])

        return stats

    def get_tournament_stats(self, tournament: str) -> dict[str, Any]:
        """Return per-tournament aggregated statistics."""
        sql = textwrap.dedent(f"""
            SELECT
                COUNT(*) AS num_matches,
                SUM(num_games) AS total_games,
                AVG(match_length) AS avg_match_length,
                COUNT(DISTINCT player1) + COUNT(DISTINCT player2) AS approx_players
            FROM matches
            WHERE tournament = '{tournament}'
        """)
        df = self.query(sql)
        stats = df.to_dicts()[0] if not df.is_empty() else {}
        stats["tournament"] = tournament

        top_players_sql = textwrap.dedent(f"""
            SELECT player, COUNT(*) AS appearances FROM (
                SELECT player1 AS player FROM matches WHERE tournament = '{tournament}'
                UNION ALL
                SELECT player2 AS player FROM matches WHERE tournament = '{tournament}'
            ) GROUP BY player ORDER BY appearances DESC LIMIT 10
        """)
        stats["top_players"] = self.query(top_players_sql).to_dicts()
        return stats

    def summary(self) -> dict[str, Any]:
        """Return high-level dataset statistics (counts and distributions).

        Result is cached after the first call.
        """
        cached = self._lru_get("__summary__")
        if cached is not None:
            return cached.to_dicts()[0]  # type: ignore[attr-defined]

        counts_sql = """
            SELECT
                (SELECT COUNT(*) FROM matches) AS num_matches,
                (SELECT COUNT(*) FROM games) AS num_games,
                (SELECT COUNT(*) FROM positions) AS num_positions,
                (SELECT COUNT(*) FROM positions WHERE decision_type = 'checker') AS num_checker,
                (SELECT COUNT(*) FROM positions WHERE decision_type = 'cube') AS num_cube,
                (SELECT COUNT(DISTINCT player1) + COUNT(DISTINCT player2) FROM matches) AS approx_players
        """
        counts = self.query(counts_sql).to_dicts()[0]

        score_dist_sql = """
            SELECT score_away_p1, score_away_p2, COUNT(*) AS n
            FROM games
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT 20
        """
        counts["score_distribution_top20"] = self.query(score_dist_sql, cache=True).to_dicts()

        error_dist_sql = """
            SELECT
                AVG(move_played_error) AS avg_error,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY move_played_error) AS median_error,
                MAX(move_played_error) AS max_error,
                AVG(CASE WHEN move_played_error > 0.1 THEN 1.0 ELSE 0.0 END) AS blunder_rate
            FROM positions
            WHERE move_played_error IS NOT NULL
        """
        counts["error_stats"] = self.query(error_dist_sql, cache=True).to_dicts()[0]

        return counts

    def close(self):
        """Close the DuckDB connection."""
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self):
        return f"BGDatabase({self._dir})"


# ---------------------------------------------------------------------------
# Pre-defined aggregation queries (convenience functions)
# ---------------------------------------------------------------------------

def error_by_score(db: BGDatabase) -> pl.DataFrame:
    """Average checker error grouped by (away_p1, away_p2)."""
    return db.query("""
        SELECT
            g.score_away_p1, g.score_away_p2,
            AVG(p.move_played_error) AS avg_error,
            COUNT(*) AS n
        FROM positions p
        JOIN games g ON g.game_id = p.game_id
        WHERE p.decision_type = 'checker' AND p.move_played_error IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, cache=True)


def top_players_by_volume(db: BGDatabase, min_matches: int = 5) -> pl.DataFrame:
    """Players ranked by number of positions (proxy for dataset representation)."""
    return db.query(f"""
        SELECT player, SUM(n) AS total_positions FROM (
            SELECT m.player1 AS player, COUNT(*) AS n
            FROM positions p
            JOIN games g ON g.game_id = p.game_id
            JOIN matches m ON m.match_id = g.match_id
            WHERE p.player_on_roll = 1
            GROUP BY m.player1
            UNION ALL
            SELECT m.player2 AS player, COUNT(*) AS n
            FROM positions p
            JOIN games g ON g.game_id = p.game_id
            JOIN matches m ON m.match_id = g.match_id
            WHERE p.player_on_roll = 2
            GROUP BY m.player2
        ) GROUP BY player HAVING SUM(n) >= {min_matches}
        ORDER BY total_positions DESC
    """, cache=True)


def cube_errors_by_score(db: BGDatabase) -> pl.DataFrame:
    """Average cube decision error grouped by (away_p1, away_p2)."""
    return db.query("""
        SELECT
            g.score_away_p1, g.score_away_p2,
            AVG(ABS(p.eval_equity)) AS avg_abs_equity,
            COUNT(*) AS n
        FROM positions p
        JOIN games g ON g.game_id = p.game_id
        WHERE p.decision_type = 'cube'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, cache=True)


def equity_distribution(db: BGDatabase, bins: int = 20) -> pl.DataFrame:
    """Distribution of best-move equity across checker positions."""
    return db.query(f"""
        SELECT
            ROUND(eval_equity * {bins}) / {bins} AS equity_bin,
            COUNT(*) AS n,
            AVG(move_played_error) AS avg_error
        FROM positions
        WHERE decision_type = 'checker' AND eval_equity IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """, cache=True)
