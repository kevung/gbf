"""GBF Query Helper — thin pandas wrapper over the GBF SQLite database.

Mirrors the Go QueryFilter / Store query API.  Auto-detects SQLite vs
PostgreSQL from the connection string (PostgreSQL support requires M7 and
the psycopg2 package; only SQLite is implemented here).

Usage::

    from gbf_query import GBFQuery
    q = GBFQuery("path/to/gbf.db")
    df = q.by_match_score(away_x=1, away_o=1)          # DMP positions
    df = q.by_features(pos_class=0, equity_diff_min=500)
    df = q.error_analysis(min_equity_diff=1000, away_x=3)
    df = q.score_distribution()
    df = q.class_distribution()
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import pandas as pd


# Column order returned by the positions SELECT (must match positionCols in sqlite.go).
_POSITION_COLS = [
    "id", "zobrist_hash", "board_hash",
    "pip_x", "pip_o", "away_x", "away_o", "cube_log2", "cube_owner",
    "bar_x", "bar_o", "borne_off_x", "borne_off_o", "side_to_move",
    "pos_class", "pip_diff", "prime_len_x", "prime_len_o",
]

_SUMMARY_COLS = [
    "id", "pos_class", "pip_x", "pip_o", "pip_diff",
    "away_x", "away_o", "cube_log2", "cube_owner",
    "bar_x", "bar_o", "prime_len_x", "prime_len_o",
]


def _pos_select(prefix: str = "") -> str:
    """Return the standard position SELECT column list."""
    p = prefix + "." if prefix else ""
    return f"""
        {p}id, {p}zobrist_hash, {p}board_hash,
        {p}pip_x, {p}pip_o, {p}away_x, {p}away_o,
        {p}cube_log2, {p}cube_owner,
        {p}bar_x, {p}bar_o, {p}borne_off_x, {p}borne_off_o, {p}side_to_move,
        COALESCE({p}pos_class,0), COALESCE({p}pip_diff,0),
        COALESCE({p}prime_len_x,0), COALESCE({p}prime_len_o,0)"""


class GBFQuery:
    """Query helper for a GBF SQLite database.

    Parameters
    ----------
    path:
        Path to the SQLite database file (or a PostgreSQL DSN starting
        with ``postgresql://`` — requires M7 and psycopg2).
    """

    def __init__(self, path: str) -> None:
        if path.startswith("postgresql://") or path.startswith("postgres://"):
            raise NotImplementedError(
                "PostgreSQL support requires M7. Use a SQLite path instead."
            )
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "GBFQuery":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Lookup queries ───────────────────────────────────────────────────────

    def by_zobrist(self, hash_value: int) -> pd.DataFrame:
        """Return positions matching a context-aware Zobrist hash."""
        # SQLite stores uint64 as int64 (bit-identical); pass as signed.
        signed = hash_value if hash_value < 2**63 else hash_value - 2**64
        sql = f"SELECT {_pos_select()} FROM positions WHERE zobrist_hash = ?"
        return self._query(sql, (signed,), _POSITION_COLS)

    def by_board_hash(self, hash_value: int) -> pd.DataFrame:
        """Return all context variations for a given board layout."""
        signed = hash_value if hash_value < 2**63 else hash_value - 2**64
        sql = f"SELECT {_pos_select()} FROM positions WHERE board_hash = ?"
        return self._query(sql, (signed,), _POSITION_COLS)

    # ── Filtered queries ─────────────────────────────────────────────────────

    def by_match_score(
        self,
        away_x: int = -1,
        away_o: int = -1,
    ) -> pd.DataFrame:
        """Return position summaries for a given match score.

        Use away_x=-1 or away_o=-1 to match any value (wildcard).
        """
        conds, args = [], []
        if away_x >= 0:
            conds.append("away_x = ?"); args.append(away_x)
        if away_o >= 0:
            conds.append("away_o = ?"); args.append(away_o)

        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"""
            SELECT id,
                   COALESCE(pos_class,0), pip_x, pip_o, COALESCE(pip_diff,0),
                   away_x, away_o, cube_log2, cube_owner, bar_x, bar_o,
                   COALESCE(prime_len_x,0), COALESCE(prime_len_o,0)
            FROM positions {where}"""
        return self._query(sql, args, _SUMMARY_COLS)

    def by_features(
        self,
        pos_class: Optional[int] = None,
        away_x: Optional[int] = None,
        away_o: Optional[int] = None,
        pip_diff_min: Optional[int] = None,
        pip_diff_max: Optional[int] = None,
        prime_len_x_min: Optional[int] = None,
        prime_len_o_min: Optional[int] = None,
        cube_log2: Optional[int] = None,
        cube_owner: Optional[int] = None,
        bar_x_min: Optional[int] = None,
        bar_o_min: Optional[int] = None,
        equity_diff_min: Optional[int] = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Return positions matching the given feature filters.

        When equity_diff_min is set the query joins with the moves table.
        equity_diff values are in ×10000 units (e.g. 1000 = 0.1 equity loss).
        """
        needs_join = equity_diff_min is not None
        conds, args = [], []

        pref = "p." if needs_join else ""

        def add(col: str, op: str, val):
            conds.append(f"{pref}{col} {op} ?")
            args.append(val)

        if pos_class is not None:    add("pos_class",   "=",  pos_class)
        if away_x is not None:       add("away_x",      "=",  away_x)
        if away_o is not None:       add("away_o",      "=",  away_o)
        if pip_diff_min is not None: add("pip_diff",    ">=", pip_diff_min)
        if pip_diff_max is not None: add("pip_diff",    "<=", pip_diff_max)
        if prime_len_x_min is not None: add("prime_len_x", ">=", prime_len_x_min)
        if prime_len_o_min is not None: add("prime_len_o", ">=", prime_len_o_min)
        if cube_log2 is not None:    add("cube_log2",   "=",  cube_log2)
        if cube_owner is not None:   add("cube_owner",  "=",  cube_owner)
        if bar_x_min is not None:    add("bar_x",       ">=", bar_x_min)
        if bar_o_min is not None:    add("bar_o",       ">=", bar_o_min)

        if needs_join:
            conds.append("m.equity_diff >= ?")
            args.append(equity_diff_min)

        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        if needs_join:
            sql = f"""
                SELECT DISTINCT {_pos_select("p")}
                FROM positions p
                JOIN moves m ON m.position_id = p.id
                {where}
                LIMIT ?"""
        else:
            sql = f"""
                SELECT {_pos_select()}
                FROM positions
                {where}
                LIMIT ?"""

        args.append(limit)
        return self._query(sql, args, _POSITION_COLS)

    def error_analysis(
        self,
        min_equity_diff: int = 500,
        **filters,
    ) -> pd.DataFrame:
        """Return moves with equity_diff ≥ min_equity_diff, joined to positions.

        Extra keyword args are passed to by_features (pos_class, away_x, …).

        Returns a DataFrame with both position and move columns.
        equity_diff is returned in ×10000 units and also as equity float.
        """
        pos_df = self.by_features(equity_diff_min=min_equity_diff, **filters)
        if pos_df.empty:
            return pd.DataFrame()

        pos_ids = pos_df["id"].tolist()
        placeholders = ",".join("?" * len(pos_ids))
        moves_sql = f"""
            SELECT position_id, move_number, player, move_type,
                   dice_1, dice_2, move_string,
                   equity_diff, best_equity, played_equity
            FROM moves
            WHERE position_id IN ({placeholders})
              AND equity_diff >= ?"""
        moves_df = self._query(
            moves_sql,
            pos_ids + [min_equity_diff],
            [
                "position_id", "move_number", "player", "move_type",
                "dice_1", "dice_2", "move_string",
                "equity_diff", "best_equity", "played_equity",
            ],
        )

        if moves_df.empty:
            return pd.DataFrame()

        # Convert equity_diff to float equity units.
        for col in ["equity_diff", "best_equity", "played_equity"]:
            moves_df[col + "_f"] = moves_df[col] / 10000.0

        merged = moves_df.merge(pos_df, left_on="position_id", right_on="id")
        return merged

    # ── Aggregations ─────────────────────────────────────────────────────────

    def score_distribution(self) -> pd.DataFrame:
        """Return position counts and avg equity loss per (away_x, away_o)."""
        sql = """
            SELECT p.away_x, p.away_o,
                   COUNT(DISTINCT p.id) AS count,
                   COALESCE(AVG(CAST(m.equity_diff AS REAL)), 0) AS avg_equity_diff
            FROM positions p
            LEFT JOIN moves m ON m.position_id = p.id
            GROUP BY p.away_x, p.away_o
            ORDER BY p.away_x, p.away_o"""
        df = self._query(sql, [], ["away_x", "away_o", "count", "avg_equity_diff"])
        df["avg_equity_diff_f"] = df["avg_equity_diff"] / 10000.0
        return df

    def class_distribution(self) -> pd.DataFrame:
        """Return position counts per class (0=contact, 1=race, 2=bearoff)."""
        sql = """
            SELECT COALESCE(pos_class,0) AS pos_class, COUNT(*) AS count
            FROM positions
            GROUP BY pos_class
            ORDER BY pos_class"""
        df = self._query(sql, [], ["pos_class", "count"])
        df["class_name"] = df["pos_class"].map(
            {0: "contact", 1: "race", 2: "bearoff"}
        )
        return df

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _query(self, sql: str, args, columns: list[str]) -> pd.DataFrame:
        cur = self._conn.execute(sql, args)
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=columns)
