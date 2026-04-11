#!/usr/bin/env python3
"""S1.1 — Global descriptive statistics for the backgammon mining study.

Produces a structured text report covering the full dataset:
  - Error distributions (checker vs cube, by magnitude)
  - Equity distribution
  - Game phase distribution (contact / race / bearoff)
  - Away score frequency matrix
  - Match and game length distributions
  - Top tournaments and players by volume
  - Temporal evolution (by year if dates available)
  - Cube value distribution at cube decisions

Also writes CSV summaries to --output for use in notebooks / S3 / S4.

Usage::

    python scripts/descriptive_stats.py \\
        --parquet-dir data/parquet \\
        [--enriched data/parquet/positions_enriched] \\
        [--output data/stats]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import polars as pl


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def section(title: str):
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")


def row_fmt(label: str, value, width: int = 38) -> str:
    return f"  {label:<{width}} {value}"


def pct(n: int, total: int) -> str:
    if total == 0:
        return "  0.0%"
    return f"{100.0 * n / total:5.1f}%"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def dataset_overview(conn: duckdb.DuckDBPyConnection):
    section("Dataset Overview")
    r = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM matches)   AS n_matches,
            (SELECT COUNT(*) FROM games)     AS n_games,
            (SELECT COUNT(*) FROM positions) AS n_positions,
            (SELECT COUNT(*) FROM positions WHERE decision_type = 'checker') AS n_checker,
            (SELECT COUNT(*) FROM positions WHERE decision_type = 'cube')    AS n_cube,
            (SELECT COUNT(DISTINCT player1) + COUNT(DISTINCT player2) FROM matches) AS approx_players
    """).fetchone()
    n_matches, n_games, n_pos, n_checker, n_cube, n_players = r
    print(row_fmt("Matches:", f"{n_matches:,}"))
    print(row_fmt("Games:", f"{n_games:,}"))
    print(row_fmt("Positions:", f"{n_pos:,}"))
    print(row_fmt("  checker decisions:", f"{n_checker:,}  ({pct(n_checker, n_pos)})"))
    print(row_fmt("  cube decisions:", f"{n_cube:,}  ({pct(n_cube, n_pos)})"))
    print(row_fmt("Approx. distinct players:", f"{n_players:,}"))
    return {"n_matches": n_matches, "n_games": n_games, "n_positions": n_pos,
            "n_checker": n_checker, "n_cube": n_cube}


def error_distribution(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Error Distribution (checker decisions)")

    stats = conn.execute("""
        SELECT
            COUNT(*)                 AS n,
            AVG(move_played_error)   AS mean,
            STDDEV(move_played_error) AS std,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY move_played_error) AS p25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY move_played_error) AS p50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY move_played_error) AS p75,
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY move_played_error) AS p90,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY move_played_error) AS p95,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY move_played_error) AS p99,
            MAX(move_played_error)   AS max_err
        FROM positions
        WHERE decision_type = 'checker' AND move_played_error IS NOT NULL
    """).fetchone()
    n, mean, std, p25, p50, p75, p90, p95, p99, mx = stats
    print(row_fmt("N (checker with error):", f"{n:,}"))
    print(row_fmt("Mean error:", f"{mean:.4f}"))
    print(row_fmt("Std dev:", f"{std:.4f}"))
    print(row_fmt("Median (p50):", f"{p50:.4f}"))
    print(row_fmt("p75:", f"{p75:.4f}"))
    print(row_fmt("p90:", f"{p90:.4f}"))
    print(row_fmt("p95:", f"{p95:.4f}"))
    print(row_fmt("p99:", f"{p99:.4f}"))
    print(row_fmt("Max:", f"{mx:.4f}"))

    # Magnitude buckets.
    buckets = [
        ("Perfect (0.000)",       "move_played_error = 0"),
        ("Tiny   (0.001–0.010)",  "move_played_error BETWEEN 0.001 AND 0.010"),
        ("Small  (0.011–0.030)",  "move_played_error BETWEEN 0.011 AND 0.030"),
        ("Medium (0.031–0.100)",  "move_played_error BETWEEN 0.031 AND 0.100"),
        ("Blunder (>0.100)",      "move_played_error > 0.100"),
    ]
    print()
    for label, cond in buckets:
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM positions WHERE decision_type='checker' AND {cond}"
        ).fetchone()[0]
        print(row_fmt(f"  {label}:", f"{cnt:>10,}  {pct(cnt, n)}"))

    # Save for notebook.
    df = conn.execute("""
        SELECT ROUND(move_played_error, 3) AS error_bin, COUNT(*) AS n
        FROM positions
        WHERE decision_type = 'checker' AND move_played_error IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).pl()
    df.write_csv(str(out_dir / "error_distribution_checker.csv"))


def equity_distribution(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Equity Distribution (checker decisions)")

    stats = conn.execute("""
        SELECT
            AVG(eval_equity) AS mean,
            STDDEV(eval_equity) AS std,
            MIN(eval_equity) AS mn,
            MAX(eval_equity) AS mx,
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY eval_equity) AS p10,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY eval_equity) AS p50,
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY eval_equity) AS p90
        FROM positions
        WHERE decision_type = 'checker' AND eval_equity IS NOT NULL
    """).fetchone()
    mean, std, mn, mx, p10, p50, p90 = stats
    print(row_fmt("Mean equity:", f"{mean:+.4f}"))
    print(row_fmt("Std dev:", f"{std:.4f}"))
    print(row_fmt("Range:", f"[{mn:+.3f}, {mx:+.3f}]"))
    print(row_fmt("p10 / p50 / p90:", f"{p10:+.3f} / {p50:+.3f} / {p90:+.3f}"))

    # Histogram buckets.
    print()
    for lo, hi in [(-3, -1), (-1, -0.3), (-0.3, -0.1), (-0.1, 0.1), (0.1, 0.3), (0.3, 1), (1, 3)]:
        cnt = conn.execute(f"""
            SELECT COUNT(*) FROM positions
            WHERE decision_type='checker'
              AND eval_equity >= {lo} AND eval_equity < {hi}
        """).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE decision_type='checker' AND eval_equity IS NOT NULL"
        ).fetchone()[0]
        print(row_fmt(f"  [{lo:+.1f}, {hi:+.1f}):", f"{cnt:>10,}  {pct(cnt, total)}"))

    df = conn.execute("""
        SELECT ROUND(eval_equity * 10) / 10 AS equity_bin, COUNT(*) AS n
        FROM positions WHERE decision_type='checker' AND eval_equity IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).pl()
    df.write_csv(str(out_dir / "equity_distribution.csv"))


def phase_distribution(conn: duckdb.DuckDBPyConnection, enriched: bool, out_dir: Path):
    section("Game Phase Distribution")

    if not enriched:
        print("  (requires positions_enriched — run S0.4 first)")
        return

    total = conn.execute("SELECT COUNT(*) FROM enriched").fetchone()[0]
    phases = conn.execute("""
        SELECT match_phase, COUNT(*) AS n
        FROM enriched
        GROUP BY match_phase ORDER BY match_phase
    """).pl()
    labels = {0: "Contact ", 1: "Race    ", 2: "Bearoff "}
    for row in phases.iter_rows(named=True):
        p = row["match_phase"]
        n = row["n"]
        bar = "█" * int(30 * n / max(total, 1))
        print(f"  {labels.get(p,'?')}  {bar:<30}  {n:>10,}  {pct(n, total)}")

    phases.with_columns(
        pl.col("match_phase").map_elements(
            lambda x: labels.get(x, "?").strip(), return_dtype=pl.String
        ).alias("phase_name")
    ).write_csv(str(out_dir / "phase_distribution.csv"))


def away_score_distribution(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Away Score Distribution (top 20 score pairs)")

    df = conn.execute("""
        SELECT score_away_p1, score_away_p2, COUNT(*) AS n
        FROM games
        WHERE score_away_p1 > 0 AND score_away_p2 > 0
        GROUP BY 1, 2
        ORDER BY n DESC
        LIMIT 20
    """).pl()

    total = conn.execute(
        "SELECT COUNT(*) FROM games WHERE score_away_p1 > 0"
    ).fetchone()[0]

    print(f"  {'away_p1':>7}  {'away_p2':>7}  {'games':>10}  {'%':>6}")
    for row in df.iter_rows(named=True):
        print(
            f"  {row['score_away_p1']:>7}  {row['score_away_p2']:>7}"
            f"  {row['n']:>10,}  {pct(row['n'], total)}"
        )
    df.write_csv(str(out_dir / "score_distribution.csv"))


def match_game_lengths(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Match & Game Length Distributions")

    # Games per match.
    match_stats = conn.execute("""
        SELECT
            MIN(num_games) AS mn, MAX(num_games) AS mx,
            AVG(num_games) AS avg,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY num_games) AS median
        FROM matches
    """).fetchone()
    print(row_fmt("Games per match (min/max/avg/median):",
                  f"{match_stats[0]} / {match_stats[1]} / {match_stats[2]:.1f} / {match_stats[3]:.1f}"))

    # Moves per game (positions per game).
    game_stats = conn.execute("""
        SELECT
            MIN(n) AS mn, MAX(n) AS mx, AVG(n) AS avg,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY n) AS median
        FROM (
            SELECT game_id, COUNT(*) AS n FROM positions GROUP BY game_id
        )
    """).fetchone()
    print(row_fmt("Moves per game (min/max/avg/median):",
                  f"{game_stats[0]} / {game_stats[1]} / {game_stats[2]:.1f} / {game_stats[3]:.1f}"))

    # Match length (points to win) distribution.
    ml_dist = conn.execute("""
        SELECT match_length, COUNT(*) AS n
        FROM matches
        GROUP BY match_length ORDER BY match_length
    """).pl()
    print("\n  Match length distribution:")
    total_m = ml_dist["n"].sum()
    for row in ml_dist.iter_rows(named=True):
        label = "money" if row["match_length"] == 0 else f"{row['match_length']}pt"
        print(f"    {label:>8}: {row['n']:>8,}  {pct(row['n'], total_m)}")

    ml_dist.write_csv(str(out_dir / "match_length_distribution.csv"))


def top_tournaments(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Top 20 Tournaments by Position Volume")

    df = conn.execute("""
        SELECT
            COALESCE(m.tournament, '(unknown)') AS tournament,
            COUNT(DISTINCT m.match_id) AS matches,
            COUNT(*) AS positions
        FROM positions p
        JOIN games g ON g.game_id = p.game_id
        JOIN matches m ON m.match_id = g.match_id
        GROUP BY 1
        ORDER BY positions DESC
        LIMIT 20
    """).pl()

    print(f"  {'Tournament':<42}  {'matches':>8}  {'positions':>10}")
    for row in df.iter_rows(named=True):
        print(f"  {str(row['tournament'])[:42]:<42}  {row['matches']:>8,}  {row['positions']:>10,}")

    df.write_csv(str(out_dir / "tournament_volumes.csv"))


def top_players(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Top 20 Players by Match Count")

    df = conn.execute("""
        SELECT player, COUNT(*) AS matches FROM (
            SELECT player1 AS player FROM matches
            UNION ALL
            SELECT player2 AS player FROM matches
        ) GROUP BY player ORDER BY matches DESC LIMIT 20
    """).pl()

    print(f"  {'Player':<40}  {'matches':>8}")
    for row in df.iter_rows(named=True):
        print(f"  {str(row['player'])[:40]:<40}  {row['matches']:>8,}")

    df.write_csv(str(out_dir / "player_volumes.csv"))


def temporal_evolution(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Temporal Evolution (by year)")

    # Extract year from date string (format: "YYYY-MM-DD..." or similar).
    df = conn.execute("""
        SELECT
            TRY_CAST(SUBSTRING(date, 1, 4) AS INTEGER) AS year,
            COUNT(*) AS matches,
            AVG(num_games) AS avg_games
        FROM matches
        WHERE date IS NOT NULL AND date != ''
        GROUP BY year
        HAVING year >= 1990 AND year <= 2030
        ORDER BY year
    """).pl()

    if df.is_empty():
        print("  (no date information available)")
        return

    print(f"  {'Year':>6}  {'matches':>10}  {'avg_games':>10}")
    for row in df.iter_rows(named=True):
        print(f"  {row['year']:>6}  {row['matches']:>10,}  {row['avg_games']:>10.1f}")

    df.write_csv(str(out_dir / "temporal_evolution.csv"))


def cube_value_distribution(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Cube Value Distribution (cube decisions)")

    df = conn.execute("""
        SELECT cube_value, COUNT(*) AS n
        FROM positions
        WHERE decision_type = 'cube'
        GROUP BY cube_value ORDER BY cube_value
    """).pl()

    total = df["n"].sum()
    print(f"  {'Cube value':>12}  {'count':>10}  {'%':>6}")
    for row in df.iter_rows(named=True):
        print(f"  {row['cube_value']:>12}  {row['n']:>10,}  {pct(row['n'], total)}")

    # Cube action distribution.
    actions = conn.execute("""
        SELECT cube_action_played, COUNT(*) AS n
        FROM positions
        WHERE decision_type = 'cube' AND cube_action_played IS NOT NULL
        GROUP BY 1 ORDER BY n DESC
    """).pl()
    if not actions.is_empty():
        print("\n  Cube action played:")
        total_a = actions["n"].sum()
        for row in actions.iter_rows(named=True):
            print(f"    {str(row['cube_action_played']):<20}  {row['n']:>8,}  {pct(row['n'], total_a)}")

    df.write_csv(str(out_dir / "cube_value_distribution.csv"))


def gammon_stats(conn: duckdb.DuckDBPyConnection, out_dir: Path):
    section("Gammon & Backgammon Rates")

    r = conn.execute("""
        SELECT
            COUNT(*) AS total_finished,
            SUM(CASE WHEN gammon THEN 1 ELSE 0 END) AS gammons,
            SUM(CASE WHEN backgammon THEN 1 ELSE 0 END) AS backgammons
        FROM games WHERE winner != 0
    """).fetchone()
    total, gammons, bgs = r
    print(row_fmt("Finished games:", f"{total:,}"))
    print(row_fmt("Gammon wins:", f"{gammons:,}  ({pct(gammons, total)})"))
    print(row_fmt("Backgammon wins:", f"{bgs:,}  ({pct(bgs, total)})"))
    print(row_fmt("Normal wins:", f"{total-gammons-bgs:,}  ({pct(total-gammons-bgs, total)})"))

    df = conn.execute("""
        SELECT
            AVG(CASE WHEN decision_type='checker' THEN eval_win_g ELSE NULL END) AS avg_win_g_checker,
            AVG(CASE WHEN decision_type='checker' THEN eval_lose_g ELSE NULL END) AS avg_lose_g_checker
        FROM positions
    """).pl()
    if not df.is_empty():
        row0 = df.row(0)
        if row0[0] is not None:
            print(row_fmt("Avg gammon threat (checker):", f"{row0[0]:.4f}"))
        if row0[1] is not None:
            print(row_fmt("Avg gammon risk (checker):", f"{row0[1]:.4f}"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S1.1: Global descriptive statistics for the mining study"
    )
    parser.add_argument("--parquet-dir", default="data/parquet",
                        help="Parquet directory (S0.2 output)")
    parser.add_argument("--enriched",
                        help="Enriched positions directory (S0.4 output)")
    parser.add_argument("--output", default="data/stats",
                        help="Output directory for CSV summaries (default: data/stats)")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prefer deduplicated positions if available.
    pos_dir = parquet_dir / "positions_dedup"
    if not pos_dir.exists() or not list(pos_dir.glob("part-*.parquet")):
        pos_dir = parquet_dir / "positions"
    pos_glob   = str(pos_dir / "part-*.parquet")
    games_path = parquet_dir / "games.parquet"
    match_path = parquet_dir / "matches.parquet"

    for label, p in [("games.parquet", games_path), ("matches.parquet", match_path)]:
        if not p.exists():
            print(f"ERROR: {label} not found", file=sys.stderr)
            sys.exit(1)
    if not list(pos_dir.glob("part-*.parquet")):
        print("ERROR: no position files found", file=sys.stderr)
        sys.exit(1)

    print(f"Using {pos_dir.name}/ for positions")
    t0 = time.time()
    conn = duckdb.connect()
    conn.execute("SET memory_limit='8GB'")
    conn.execute(f"CREATE VIEW positions AS SELECT * FROM read_parquet('{pos_glob}')")
    conn.execute(f"CREATE VIEW games    AS SELECT * FROM read_parquet('{games_path}')")
    conn.execute(f"CREATE VIEW matches  AS SELECT * FROM read_parquet('{match_path}')")

    has_enriched = False
    if args.enriched:
        enriched_files = sorted(Path(args.enriched).glob("part-*.parquet"))
        if enriched_files:
            enriched_glob = str(Path(args.enriched) / "part-*.parquet")
            conn.execute(f"CREATE VIEW enriched AS SELECT * FROM read_parquet('{enriched_glob}')")
            has_enriched = True

    print("=" * 64)
    print("  S1.1 — Global Descriptive Statistics Report")
    print("=" * 64)

    overview = dataset_overview(conn)
    error_distribution(conn, out_dir)
    equity_distribution(conn, out_dir)
    phase_distribution(conn, has_enriched, out_dir)
    away_score_distribution(conn, out_dir)
    match_game_lengths(conn, out_dir)
    top_tournaments(conn, out_dir)
    top_players(conn, out_dir)
    temporal_evolution(conn, out_dir)
    cube_value_distribution(conn, out_dir)
    gammon_stats(conn, out_dir)

    conn.close()
    elapsed = time.time() - t0
    print(f"\n{'═' * 64}")
    print(f"  Report complete in {elapsed:.1f}s — CSVs written to {out_dir}/")
    print(f"{'═' * 64}\n")


if __name__ == "__main__":
    main()
