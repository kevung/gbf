"""Unit tests for S1.9 theme predicates.

For each theme we verify:
  - a positive fixture triggers the predicate,
  - at least one textbook counter-example does not.

Fixtures use the minimum schema each predicate references. Board
columns use Python lists of 26 ints (bar + 1..24 + off), matching
compute_features.py conventions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

# Make scripts/lib importable as top-level "lib" package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import theme_rules as tr  # noqa: E402
from lib.board_predicates import can_hit_this_roll, max_gap_p1  # noqa: E402


# ── Fixture builder ────────────────────────────────────────────────

STARTING_BOARD = [0] + [0]*24 + [0]
# Starting position from p1 POV: 2 on 24, 5 on 13, 3 on 8, 5 on 6.
for idx, n in [(24, 2), (13, 5), (8, 3), (6, 5)]:
    STARTING_BOARD[idx] = n
STARTING_BOARD = tuple(STARTING_BOARD)

STARTING_BOARD_P2 = list(STARTING_BOARD)  # symmetric at start


def _board(**points: int) -> list[int]:
    """Build a 26-slot board with checkers on named points.

    Keys: ``bar``, ``off``, ``p1``..``p24``. Missing points are zero.
    """
    b = [0] * 26
    if "bar" in points:
        b[0] = points["bar"]
    if "off" in points:
        b[25] = points["off"]
    for k, v in points.items():
        if k in ("bar", "off"):
            continue
        if k.startswith("p"):
            idx = int(k[1:])
            b[idx] = v
    return b


def _row(**kwargs):
    """Produce a single-row DataFrame with sensible defaults so every
    predicate can evaluate. Override any field via kwargs.
    """
    defaults = {
        "position_id": 1,
        "game_id": "g1",
        "move_number": 10,
        "decision_type": "checker",
        "dice": [3, 2],
        "board_p1": list(STARTING_BOARD),
        "board_p2": list(STARTING_BOARD_P2),
        "match_phase": 0,
        "pip_count_p1": 167,
        "pip_count_p2": 167,
        "pip_count_diff": 0,
        "num_on_bar_p1": 0,
        "num_on_bar_p2": 0,
        "num_borne_off_p1": 0,
        "num_borne_off_p2": 0,
        "num_blots_p1": 0,
        "num_blots_p2": 0,
        "num_points_made_p1": 5,
        "num_points_made_p2": 5,
        "home_board_points_p1": 2,
        "home_board_points_p2": 2,
        "longest_prime_p1": 2,
        "longest_prime_p2": 2,
        "back_anchor_p1": 24,
        "num_checkers_back_p1": 2,
        "num_checkers_back_p2": 2,
        "num_builders_p1": 1,
        "outfield_blots_p1": 0,
        "eval_win": 0.5,
        "gammon_threat": 0.1,
        "gammon_risk": 0.1,
        "cube_action_optimal": None,
        "anchors_back_p1": 1,
        "ace_anchor_only_p1": True,
        "max_gap_p1": 1,
        "can_hit_this_roll_p1": False,
    }
    defaults.update(kwargs)
    return pl.DataFrame([defaults])


def _fires(df: pl.DataFrame, predicate_fn) -> bool:
    return bool(df.select(predicate_fn().alias("x"))["x"][0])


# ── Phase-A theme tests ────────────────────────────────────────────

def test_opening_positive_on_starting_move():
    df = _row(move_number=2, pip_count_p1=167, pip_count_p2=167)
    assert _fires(df, tr.theme_opening)


def test_opening_negative_late_game():
    df = _row(move_number=20, pip_count_p1=80, pip_count_p2=80)
    assert not _fires(df, tr.theme_opening)


def test_flexibility_positive_with_builders_no_prime():
    df = _row(num_builders_p1=4, longest_prime_p1=2, num_blots_p1=3,
              num_points_made_p1=4, move_number=8)
    assert _fires(df, tr.theme_flexibility)


def test_flexibility_negative_with_prime():
    df = _row(num_builders_p1=4, longest_prime_p1=5, num_blots_p1=3,
              num_points_made_p1=4, move_number=8)
    assert not _fires(df, tr.theme_flexibility)


def test_middle_game_positive():
    df = _row(move_number=14, pip_count_p1=120, pip_count_p2=115)
    assert _fires(df, tr.theme_middle_game)


def test_middle_game_negative_in_opening():
    df = _row(move_number=3, pip_count_p1=167, pip_count_p2=167)
    assert not _fires(df, tr.theme_middle_game)


def test_5_point_positive():
    b1 = _board(p5=2, p6=2, p13=5, p24=2)
    df = _row(board_p1=b1, num_checkers_back_p1=2, num_checkers_back_p2=2,
              move_number=8)
    assert _fires(df, tr.theme_5_point)


def test_5_point_negative_late():
    b1 = _board(p5=2, p6=2, p24=2)
    df = _row(board_p1=b1, move_number=25)
    assert not _fires(df, tr.theme_5_point)


def test_blitz_positive():
    df = _row(move_number=10, home_board_points_p1=4, num_on_bar_p2=1,
              pip_count_p1=120, num_checkers_back_p1=2)
    assert _fires(df, tr.theme_blitz)


def test_blitz_negative_no_opponent_pressure():
    df = _row(move_number=10, home_board_points_p1=4, num_on_bar_p2=0,
              num_blots_p2=0, pip_count_p1=120, num_checkers_back_p1=2)
    assert not _fires(df, tr.theme_blitz)


def test_one_man_back_positive():
    df = _row(num_checkers_back_p1=1, longest_prime_p2=5)
    assert _fires(df, tr.theme_one_man_back)


def test_one_man_back_negative_without_opponent_prime():
    df = _row(num_checkers_back_p1=1, longest_prime_p2=2)
    assert not _fires(df, tr.theme_one_man_back)


def test_holding_positive():
    df = _row(num_checkers_back_p1=2, back_anchor_p1=21, pip_count_diff=25,
              anchors_back_p1=1)
    assert _fires(df, tr.theme_holding)


def test_holding_negative_two_anchors_is_back_game_not_holding():
    df = _row(num_checkers_back_p1=4, back_anchor_p1=22, pip_count_diff=25,
              anchors_back_p1=2)
    assert not _fires(df, tr.theme_holding)


def test_priming_positive():
    df = _row(longest_prime_p1=5)
    assert _fires(df, tr.theme_priming)


def test_priming_negative_in_race():
    df = _row(longest_prime_p1=1, longest_prime_p2=2, match_phase=1)
    assert not _fires(df, tr.theme_priming)


def test_connectivity_positive():
    df = _row(max_gap_p1=1, num_blots_p1=0, outfield_blots_p1=0)
    assert _fires(df, tr.theme_connectivity)


def test_connectivity_negative_with_outfield_blot():
    df = _row(max_gap_p1=1, num_blots_p1=0, outfield_blots_p1=2)
    assert not _fires(df, tr.theme_connectivity)


def test_hit_or_not_positive():
    df = _row(num_blots_p2=1, can_hit_this_roll_p1=True,
              decision_type="checker")
    assert _fires(df, tr.theme_hit_or_not)


def test_hit_or_not_negative_cube_decision():
    df = _row(num_blots_p2=1, can_hit_this_roll_p1=True,
              decision_type="cube")
    assert not _fires(df, tr.theme_hit_or_not)


def test_crunch_positive():
    df = _row(num_blots_p1=4, num_points_made_p1=3, num_checkers_back_p1=3,
              back_anchor_p1=22)
    assert _fires(df, tr.theme_crunch)


def test_crunch_negative_healthy_structure():
    df = _row(num_blots_p1=1, num_points_made_p1=7, num_checkers_back_p1=2)
    assert not _fires(df, tr.theme_crunch)


def test_action_doubles_positive():
    df = _row(decision_type="cube", cube_action_optimal="Double/Take",
              eval_win=0.65, gammon_threat=0.2, gammon_risk=0.1)
    assert _fires(df, tr.theme_action_doubles)


def test_action_doubles_negative_low_volatility():
    df = _row(decision_type="cube", cube_action_optimal="Double/Take",
              eval_win=0.65, gammon_threat=0.05, gammon_risk=0.05)
    assert not _fires(df, tr.theme_action_doubles)


def test_late_blitz_positive():
    df = _row(move_number=18, home_board_points_p1=5, num_on_bar_p2=1,
              pip_count_p2=100)
    assert _fires(df, tr.theme_late_blitz)


def test_late_blitz_negative_early():
    df = _row(move_number=8, home_board_points_p1=5, num_on_bar_p2=1,
              pip_count_p2=100)
    assert not _fires(df, tr.theme_late_blitz)


def test_too_good_positive():
    df = _row(decision_type="cube", cube_action_optimal="No Double",
              eval_win=0.85, gammon_threat=0.55)
    assert _fires(df, tr.theme_too_good)


def test_too_good_negative_low_equity():
    df = _row(decision_type="cube", cube_action_optimal="No Double",
              eval_win=0.55, gammon_threat=0.15)
    assert not _fires(df, tr.theme_too_good)


def test_ace_point_positive():
    df = _row(num_checkers_back_p1=3, ace_anchor_only_p1=True)
    assert _fires(df, tr.theme_ace_point)


def test_ace_point_negative_with_other_back_points():
    df = _row(num_checkers_back_p1=3, ace_anchor_only_p1=False)
    assert not _fires(df, tr.theme_ace_point)


def test_back_game_positive():
    df = _row(anchors_back_p1=2, pip_count_diff=30)
    assert _fires(df, tr.theme_back_game)


def test_back_game_negative_single_anchor():
    df = _row(anchors_back_p1=1, pip_count_diff=30)
    assert not _fires(df, tr.theme_back_game)


def test_containment_positive():
    df = _row(pip_count_diff=-25, longest_prime_p1=5,
              num_checkers_back_p2=2, home_board_points_p1=5)
    assert _fires(df, tr.theme_containment)


def test_containment_negative_without_prime():
    df = _row(pip_count_diff=-25, longest_prime_p1=2,
              num_checkers_back_p2=2, home_board_points_p1=5)
    assert not _fires(df, tr.theme_containment)


def test_playing_gammon_positive():
    df = _row(home_board_points_p1=6, num_on_bar_p2=1, gammon_threat=0.45,
              eval_win=0.80)
    assert _fires(df, tr.theme_playing_gammon)


def test_playing_gammon_negative_losing_position():
    df = _row(home_board_points_p1=6, num_on_bar_p2=1, gammon_threat=0.10,
              eval_win=0.40)
    assert not _fires(df, tr.theme_playing_gammon)


def test_saving_gammon_positive():
    df = _row(eval_win=0.05, gammon_risk=0.4, num_borne_off_p1=0,
              num_checkers_back_p1=0)
    assert _fires(df, tr.theme_saving_gammon)


def test_saving_gammon_negative_winning():
    df = _row(eval_win=0.7, gammon_risk=0.1)
    assert not _fires(df, tr.theme_saving_gammon)


def test_bearoff_vs_contact_positive():
    df = _row(match_phase=0, num_borne_off_p1=2, num_checkers_back_p2=2,
              pip_count_p1=45)
    assert _fires(df, tr.theme_bearoff_vs_contact)


def test_bearoff_vs_contact_negative_race():
    df = _row(match_phase=1, num_borne_off_p1=2, num_checkers_back_p2=0,
              pip_count_p1=45)
    assert not _fires(df, tr.theme_bearoff_vs_contact)


def test_various_endgames_positive_low_pip_contact():
    df = _row(match_phase=0, pip_count_p1=60, pip_count_p2=60)
    assert _fires(df, tr.theme_various_endgames)


def test_various_endgames_negative_opening_pip():
    df = _row(pip_count_p1=167, pip_count_p2=167)
    assert not _fires(df, tr.theme_various_endgames)


def test_race_positive():
    df = _row(match_phase=1)
    assert _fires(df, tr.theme_race)


def test_race_negative_in_contact():
    df = _row(match_phase=0)
    assert not _fires(df, tr.theme_race)


def test_bearoff_positive():
    df = _row(match_phase=2)
    assert _fires(df, tr.theme_bearoff)


def test_bearoff_negative_in_race():
    df = _row(match_phase=1)
    assert not _fires(df, tr.theme_bearoff)


# ── Board predicate helpers ────────────────────────────────────────

def test_max_gap_p1_starting_position():
    gap = max_gap_p1(list(STARTING_BOARD))
    # Points 7,9-12,14-23 empty, 8 and 13 populated, 24 populated.
    # Largest gap between 7 and 24 is points 14..23 = 10 empties, but 13
    # is populated so gap is 10 consecutive (14..23).
    assert gap == 10


def test_max_gap_p1_empty_outfield():
    b = _board(p1=5, p2=5, p3=5)
    assert max_gap_p1(b) == 0  # no checker beyond point 7


def test_can_hit_direct():
    # p1 at point 10, p2 blot at p1-coord 7 (p2's point 18); dice 3,2.
    b1 = _board(p10=1, p6=5)
    b2 = _board()
    b2[25 - 7] = 1  # p2's point 18 => p1-coord 7
    assert can_hit_this_roll(b1, b2, [3, 2]) is True


def test_can_hit_no_blot():
    b1 = _board(p10=1)
    b2 = _board(p6=2)  # p2 made point, not a blot
    assert can_hit_this_roll(b1, b2, [3, 2]) is False


def test_can_hit_from_bar():
    b1 = _board(bar=1)
    b2 = _board()
    b2[25 - 23] = 1  # p2 blot on p1-coord 23 = enters with die 2
    assert can_hit_this_roll(b1, b2, [2, 5]) is True


# ── Phase B trajectory predicates (structural shape) ──────────────

def test_breaking_anchor_positive():
    df = pl.DataFrame([{
        "prev_anchors_back_p1": 1,
        "prev_num_checkers_back_p1": 3,
        "num_checkers_back_p1": 1,
    }])
    assert _fires(df, tr.theme_breaking_anchor)


def test_breaking_anchor_negative_no_change():
    df = pl.DataFrame([{
        "prev_anchors_back_p1": 1,
        "prev_num_checkers_back_p1": 3,
        "num_checkers_back_p1": 3,
    }])
    assert not _fires(df, tr.theme_breaking_anchor)


def test_post_blitz_turnaround_positive():
    df = _row(match_phase=0, num_checkers_back_p2=2, num_on_bar_p2=0,
              eval_win=0.5)
    df = df.with_columns(pl.lit(True).alias("blitz_in_window"))
    assert _fires(df, tr.theme_post_blitz_turnaround)


def test_post_blitz_turnaround_negative_without_prior_blitz():
    df = _row(match_phase=0, num_checkers_back_p2=2, num_on_bar_p2=0,
              eval_win=0.5)
    df = df.with_columns(pl.lit(False).alias("blitz_in_window"))
    assert not _fires(df, tr.theme_post_blitz_turnaround)


def test_post_ace_point_positive():
    df = _row(match_phase=1, num_checkers_back_p1=1, pip_count_p1=70)
    df = df.with_columns(pl.lit(True).alias("ace_point_in_window"))
    assert _fires(df, tr.theme_post_ace_point)


def test_post_ace_point_negative_without_prior_ace():
    df = _row(match_phase=1, num_checkers_back_p1=1, pip_count_p1=70)
    df = df.with_columns(pl.lit(False).alias("ace_point_in_window"))
    assert not _fires(df, tr.theme_post_ace_point)


# ── primary_theme resolver ────────────────────────────────────────

def test_primary_theme_picks_most_specific():
    # A position that is both priming and middle game should resolve to
    # priming (higher priority).
    df = pl.DataFrame([{
        "theme_priming": True,
        "theme_middle_game": True,
        "theme_opening": False,
    }])
    resolved = df.select(
        tr.primary_theme_expr(df.columns).alias("primary_theme")
    )["primary_theme"][0]
    assert resolved == "priming"


def test_primary_theme_unclassified_when_nothing_fires():
    df = pl.DataFrame([{
        "theme_priming": False,
        "theme_middle_game": False,
    }])
    resolved = df.select(
        tr.primary_theme_expr(df.columns).alias("primary_theme")
    )["primary_theme"][0]
    assert resolved == "unclassified"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
