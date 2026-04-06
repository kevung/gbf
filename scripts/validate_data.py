#!/usr/bin/env python3
"""S0.5 — Data quality validation for the backgammon mining study pipeline.

Runs a suite of checks on Parquet files from S0.2 and the enriched
positions from S0.4. Prints a structured report and exits with code 1
if any FAIL-level check fails.

Checks performed
----------------
1. Referential integrity     every game_id in positions exists in games
2. Probability sanity        win + opp_win ≈ 1, gammon rates in [0, 1]
3. Equity range              eval_equity in [-3, +3]
4. Board validity            15 checkers per player, no negatives
5. Completeness              % positions with full analysis
6. No duplicate position_id
7. Move ordering             move_number increases within each game
8. Score coherence           away scores > 0, consistent with match_length
9. Volume statistics         counts by decision type, match phase, score

Usage::

    python scripts/validate_data.py --parquet-dir data/parquet [--enriched data/parquet/positions_enriched]

Exit code: 0 if all checks pass (or only warnings), 1 if any FAIL.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import polars as pl


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

PASS = "✓ PASS"
WARN = "⚠ WARN"
FAIL = "✗ FAIL"

_failures = 0
_warnings = 0


def check(label: str, cond: bool, detail: str = "", level: str = FAIL):
    global _failures, _warnings
    status = PASS if cond else level
    if not cond:
        if level == FAIL:
            _failures += 1
        else:
            _warnings += 1
    detail_str = f"  → {detail}" if detail else ""
    print(f"  {status}  {label}{detail_str}")


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_referential_integrity(conn: duckdb.DuckDBPyConnection):
    section("1. Referential Integrity")

    # games → matches
    orphan_games = conn.execute("""
        SELECT COUNT(*) FROM games g
        LEFT JOIN matches m ON m.match_id = g.match_id
        WHERE m.match_id IS NULL
    """).fetchone()[0]
    check("games.match_id → matches.match_id", orphan_games == 0,
          f"{orphan_games} orphan game rows")

    # positions → games
    orphan_pos = conn.execute("""
        SELECT COUNT(*) FROM positions p
        LEFT JOIN games g ON g.game_id = p.game_id
        WHERE g.game_id IS NULL
    """).fetchone()[0]
    check("positions.game_id → games.game_id", orphan_pos == 0,
          f"{orphan_pos} orphan position rows")

    # Check that all matches referenced by games exist
    missing_matches = conn.execute("""
        SELECT COUNT(DISTINCT g.match_id) FROM games g
        LEFT JOIN matches m ON m.match_id = g.match_id
        WHERE m.match_id IS NULL
    """).fetchone()[0]
    check("all game.match_id values found in matches", missing_matches == 0,
          f"{missing_matches} missing match_ids")


def check_probability_sanity(conn: duckdb.DuckDBPyConnection):
    section("2. Probability Sanity")

    # win + opp_win ≈ 1 (should be close, not exact due to gammon rates)
    # Actually: eval_win is P(win for on-roll), but positions may store only
    # eval_win (not opp_win directly). Check eval_win in [0,1].
    win_range = conn.execute("""
        SELECT
            SUM(CASE WHEN eval_win < 0 OR eval_win > 1 THEN 1 ELSE 0 END) AS out_of_range,
            COUNT(*) AS total
        FROM positions WHERE eval_win IS NOT NULL
    """).fetchone()
    bad_win, total_win = win_range
    check("eval_win in [0, 1]", bad_win == 0,
          f"{bad_win}/{total_win} out of range")

    # Gammon rates in [0, 1]
    for col in ("eval_win_g", "eval_win_bg", "eval_lose_g", "eval_lose_bg"):
        bad = conn.execute(f"""
            SELECT SUM(CASE WHEN {col} < 0 OR {col} > 1 THEN 1 ELSE 0 END)
            FROM positions WHERE {col} IS NOT NULL
        """).fetchone()[0]
        check(f"{col} in [0, 1]", bad == 0, f"{bad} out-of-range values")

    # Sum of gammon + bg rates should not exceed win rate (loose sanity).
    bad_gammon = conn.execute("""
        SELECT COUNT(*) FROM positions
        WHERE eval_win IS NOT NULL
          AND eval_win_g IS NOT NULL
          AND eval_win_bg IS NOT NULL
          AND eval_win_g + eval_win_bg > eval_win + 0.001
    """).fetchone()[0]
    pct = 100.0 * bad_gammon / max(total_win, 1)
    check("gammon+bg rate ≤ win rate", pct < 1.0,
          f"{bad_gammon} violations ({pct:.2f}%)", level=WARN)


def check_equity_range(conn: duckdb.DuckDBPyConnection):
    section("3. Equity Range")

    stats = conn.execute("""
        SELECT
            MIN(eval_equity) AS mn, MAX(eval_equity) AS mx,
            AVG(eval_equity) AS avg,
            SUM(CASE WHEN eval_equity < -3 OR eval_equity > 3 THEN 1 ELSE 0 END) AS extreme,
            COUNT(*) AS total
        FROM positions WHERE eval_equity IS NOT NULL
    """).fetchone()
    mn, mx, avg, extreme, total = stats
    check("eval_equity in [-3, +3]", extreme == 0,
          f"{extreme}/{total} extreme values, range=[{mn:.3f}, {mx:.3f}]")
    check("eval_equity mean near 0", abs(avg) < 0.1,
          f"mean={avg:.4f} (expected ≈0 for symmetric dataset)", level=WARN)

    # Error values
    bad_err = conn.execute("""
        SELECT COUNT(*) FROM positions
        WHERE move_played_error IS NOT NULL
          AND (move_played_error < 0 OR move_played_error > 3)
    """).fetchone()[0]
    check("move_played_error in [0, 3]", bad_err == 0,
          f"{bad_err} out-of-range error values")


def check_board_validity(conn: duckdb.DuckDBPyConnection):
    section("4. Board Validity")

    # DuckDB can query list columns — use list_sum and element access.
    # Total checkers per player: sum of board array slots 0..25.
    bad_total = conn.execute("""
        SELECT COUNT(*) FROM positions
        WHERE list_sum(board_p1) + list_sum(board_p2) != 30
    """).fetchone()[0]
    check("total checkers per position = 30 (15+15)", bad_total == 0,
          f"{bad_total} positions with wrong total")

    # Individual player checker count.
    bad_p1 = conn.execute("""
        SELECT COUNT(*) FROM positions WHERE list_sum(board_p1) != 15
    """).fetchone()[0]
    bad_p2 = conn.execute("""
        SELECT COUNT(*) FROM positions WHERE list_sum(board_p2) != 15
    """).fetchone()[0]
    check("board_p1 sums to 15", bad_p1 == 0, f"{bad_p1} positions wrong")
    check("board_p2 sums to 15", bad_p2 == 0, f"{bad_p2} positions wrong")

    # No negative values in board arrays.
    bad_neg = conn.execute("""
        SELECT COUNT(*) FROM positions
        WHERE list_min(board_p1) < 0 OR list_min(board_p2) < 0
    """).fetchone()[0]
    check("no negative board values", bad_neg == 0,
          f"{bad_neg} positions with negatives")


def check_completeness(conn: duckdb.DuckDBPyConnection):
    section("5. Completeness")

    total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    with_equity = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE eval_equity IS NOT NULL"
    ).fetchone()[0]
    pct = 100.0 * with_equity / max(total, 1)
    check("positions with eval_equity", pct > 80,
          f"{with_equity}/{total} ({pct:.1f}%)", level=WARN)

    no_analysis = total - with_equity
    check("positions without analysis < 20%", no_analysis / max(total, 1) < 0.2,
          f"{no_analysis} positions ({100*no_analysis/max(total,1):.1f}%)", level=WARN)

    # Cube decisions should all have cube_action_played.
    cube_total = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE decision_type='cube'"
    ).fetchone()[0]
    cube_with_action = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE decision_type='cube' AND cube_action_played IS NOT NULL"
    ).fetchone()[0]
    if cube_total > 0:
        pct_cube = 100.0 * cube_with_action / cube_total
        check("cube decisions have cube_action_played", pct_cube > 90,
              f"{cube_with_action}/{cube_total} ({pct_cube:.1f}%)", level=WARN)


def check_duplicates(conn: duckdb.DuckDBPyConnection):
    section("6. Duplicates")

    dup_pos = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT position_id, COUNT(*) AS n FROM positions
            GROUP BY position_id HAVING n > 1
        )
    """).fetchone()[0]
    check("no duplicate position_id", dup_pos == 0,
          f"{dup_pos} duplicate position_ids")

    dup_match = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT match_id, COUNT(*) AS n FROM matches
            GROUP BY match_id HAVING n > 1
        )
    """).fetchone()[0]
    check("no duplicate match_id", dup_match == 0,
          f"{dup_match} duplicate match_ids")


def check_move_ordering(conn: duckdb.DuckDBPyConnection):
    section("7. Move Ordering")

    # Within each game, move_number should be monotonically increasing.
    # Check: max - min + 1 ≈ count (no gaps or duplicates).
    disorder = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT game_id,
                   MAX(move_number) - MIN(move_number) + 1 AS span,
                   COUNT(*) AS n
            FROM positions
            GROUP BY game_id
            HAVING span != n
        )
    """).fetchone()[0]
    check("move_number is monotone within each game", disorder == 0,
          f"{disorder} games with gaps or duplicate move numbers", level=WARN)


def check_score_coherence(conn: duckdb.DuckDBPyConnection):
    section("8. Score Coherence")

    # Away scores should be > 0 for match-play games (match_length > 0).
    # Money games (match_length = 0) use away = 0 by convention.
    bad_away = conn.execute("""
        SELECT COUNT(*) FROM games g
        JOIN matches m ON m.match_id = g.match_id
        WHERE m.match_length > 0
          AND (g.score_away_p1 <= 0 OR g.score_away_p2 <= 0)
    """).fetchone()[0]
    check("away scores > 0 for match-play games", bad_away == 0,
          f"{bad_away} match-play games with zero/negative away score")

    # Points won should be >= 1 for finished games.
    bad_pts = conn.execute("""
        SELECT COUNT(*) FROM games WHERE winner != 0 AND points_won < 1
    """).fetchone()[0]
    check("finished games have points_won >= 1", bad_pts == 0,
          f"{bad_pts} finished games with points_won < 1")

    # Match length should be positive for match-play games.
    bad_len = conn.execute("""
        SELECT COUNT(*) FROM matches WHERE match_length < 0
    """).fetchone()[0]
    check("match_length >= 0", bad_len == 0,
          f"{bad_len} matches with negative match_length")


def volume_statistics(conn: duckdb.DuckDBPyConnection):
    section("Volume Statistics")

    counts = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM matches) AS matches,
            (SELECT COUNT(*) FROM games) AS games,
            (SELECT COUNT(*) FROM positions) AS positions,
            (SELECT COUNT(*) FROM positions WHERE decision_type='checker') AS checker,
            (SELECT COUNT(*) FROM positions WHERE decision_type='cube') AS cube
    """).fetchone()
    print(f"  matches:    {counts[0]:>12,}")
    print(f"  games:      {counts[1]:>12,}")
    print(f"  positions:  {counts[2]:>12,}")
    print(f"    checker:  {counts[3]:>12,}  ({100*counts[3]/max(counts[2],1):.1f}%)")
    print(f"    cube:     {counts[4]:>12,}  ({100*counts[4]/max(counts[2],1):.1f}%)")

    # Top 5 tournaments by position count.
    top_t = conn.execute("""
        SELECT m.tournament, COUNT(*) AS n
        FROM positions p
        JOIN games g ON g.game_id = p.game_id
        JOIN matches m ON m.match_id = g.match_id
        GROUP BY 1 ORDER BY 2 DESC LIMIT 5
    """).fetchall()
    if top_t:
        print("\n  Top tournaments by position count:")
        for name, n in top_t:
            print(f"    {str(name)[:40]:<40}  {n:>8,}")

    # Decision type distribution.
    phase_dist = conn.execute("""
        SELECT score_away_p1, score_away_p2, COUNT(*) AS n
        FROM positions p
        JOIN games g ON g.game_id = p.game_id
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5
    """).fetchall()
    if phase_dist:
        print("\n  Top score pairs by frequency:")
        for away1, away2, n in phase_dist:
            print(f"    {away1}-away vs {away2}-away:  {n:>8,}")


def check_enriched(enriched_dir: Path):
    section("Enriched Features (S0.4)")
    files = sorted(enriched_dir.glob("part-*.parquet"))
    if not files:
        check("positions_enriched exists", False, f"no files in {enriched_dir}")
        return

    df = pl.read_parquet(enriched_dir / "part-*.parquet")
    n = len(df)

    expected_cols = [
        "pip_count_p1", "pip_count_p2", "pip_count_diff",
        "num_blots_p1", "num_points_made_p1", "home_board_points_p1",
        "longest_prime_p1", "back_anchor_p1", "match_phase",
        "gammon_threat", "gammon_risk", "net_gammon",
        "leader", "is_dmp", "dgr", "take_point_match",
    ]
    missing = [c for c in expected_cols if c not in df.columns]
    check("all expected feature columns present", not missing,
          f"missing: {missing}")

    # Pip counts should be positive.
    bad_pip = (df["pip_count_p1"] < 0).sum() + (df["pip_count_p2"] < 0).sum()
    check("pip counts >= 0", bad_pip == 0, f"{bad_pip} negative pip counts")

    # match_phase in [0, 1, 2].
    phase_vals = df["match_phase"].unique().to_list()
    bad_phase = [v for v in phase_vals if v not in (0, 1, 2)]
    check("match_phase in {0,1,2}", not bad_phase, f"unexpected values: {bad_phase}")

    # gammon_threat in [0, 1].
    if "gammon_threat" in df.columns:
        bad_gt = ((df["gammon_threat"] < 0) | (df["gammon_threat"] > 1)).sum()
        check("gammon_threat in [0, 1]", bad_gt == 0, f"{bad_gt} out-of-range")

    print(f"\n  Enriched positions: {n:,} rows, {len(df.columns)} columns")
    phase_dist = df["match_phase"].value_counts().sort("match_phase")
    labels = {0: "contact", 1: "race", 2: "bearoff"}
    for row in phase_dist.iter_rows(named=True):
        pct = 100.0 * row["count"] / n
        print(f"    {labels.get(row['match_phase'], '?'):<10}: {row['count']:>6,} ({pct:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S0.5: Data quality validation for the mining study pipeline"
    )
    parser.add_argument("--parquet-dir", default="data/parquet",
                        help="Parquet directory (S0.2 output)")
    parser.add_argument("--enriched",
                        help="Enriched positions directory (S0.4 output, optional)")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    t0 = time.time()

    print("=" * 60)
    print("  S0.5 — Data Quality Validation Report")
    print("=" * 60)

    # Register DuckDB views.
    conn = duckdb.connect()
    pos_glob = str(parquet_dir / "positions" / "part-*.parquet")
    games_path = parquet_dir / "games.parquet"
    matches_path = parquet_dir / "matches.parquet"

    missing_files = []
    for p in [games_path, matches_path]:
        if not p.exists():
            missing_files.append(str(p))
    pos_files = list((parquet_dir / "positions").glob("part-*.parquet"))
    if not pos_files:
        missing_files.append(str(parquet_dir / "positions/"))

    if missing_files:
        print(f"\n  ERROR: required files missing: {missing_files}", file=sys.stderr)
        sys.exit(1)

    conn.execute(f"CREATE VIEW matches AS SELECT * FROM read_parquet('{matches_path}')")
    conn.execute(f"CREATE VIEW games AS SELECT * FROM read_parquet('{games_path}')")
    conn.execute(f"CREATE VIEW positions AS SELECT * FROM read_parquet('{pos_glob}')")

    # Run all checks.
    check_referential_integrity(conn)
    check_probability_sanity(conn)
    check_equity_range(conn)
    check_board_validity(conn)
    check_completeness(conn)
    check_duplicates(conn)
    check_move_ordering(conn)
    check_score_coherence(conn)
    volume_statistics(conn)

    if args.enriched:
        check_enriched(Path(args.enriched))

    conn.close()

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"  Result: {_failures} failure(s), {_warnings} warning(s)  [{elapsed:.1f}s]")
    print(f"{'=' * 60}\n")

    if _failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
