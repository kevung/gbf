"""Unit tests for BE.1 — compute_barycentric_v2.py

Key invariants:
  1. Perspective symmetry: two rows representing the same physical position
     but with player_on_roll swapped (eval_win/lose_g/bg adjusted accordingly)
     produce the same bary_p1_a, bary_p1_b, cubeless_mwc_p1.
  2. cube_value == 0 treated as cube_eff == 1.
  3. Bounds: bary_p1_a >= 0, bary_p1_b >= 0, mwc_p1 in [0, 1].
  4. eval_equity cross-check: cubeful_equity_p1 == -eval_equity when on_roll==2.
  5. On-roll-POV values preserved correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_barycentric_v2 import build_met_lookup, compute_barycentric_v2  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pos(**kwargs) -> dict:
    """Build a minimal position row; caller overrides defaults."""
    defaults = {
        "position_id": "test_001",
        "game_id": "g1",
        "move_number": 1,
        "player_on_roll": 1,
        "eval_win": 0.50,
        "eval_win_g": 0.20,
        "eval_win_bg": 0.02,
        "eval_lose_g": 0.18,
        "eval_lose_bg": 0.01,
        "eval_equity": 0.0,
        "score_away_p1": 7,
        "score_away_p2": 7,
        "cube_value": 1,
        "crawford": False,
        "is_post_crawford": False,
    }
    return {**defaults, **kwargs}


def run(rows: list[dict]) -> pl.DataFrame:
    met = build_met_lookup()
    df = pl.DataFrame(rows).with_columns([
        pl.col("eval_win").cast(pl.Float32),
        pl.col("eval_win_g").cast(pl.Float32),
        pl.col("eval_win_bg").cast(pl.Float32),
        pl.col("eval_lose_g").cast(pl.Float32),
        pl.col("eval_lose_bg").cast(pl.Float32),
        pl.col("eval_equity").cast(pl.Float64),
        pl.col("score_away_p1").cast(pl.Int16),
        pl.col("score_away_p2").cast(pl.Int16),
        pl.col("cube_value").cast(pl.Int32),
        pl.col("player_on_roll").cast(pl.Int8),
        pl.col("move_number").cast(pl.Int16),
    ])
    return compute_barycentric_v2(df, met)


# ---------------------------------------------------------------------------
# Test 1: perspective symmetry
# ---------------------------------------------------------------------------

def test_perspective_symmetry_equal_scores():
    """Same physical position, player_on_roll swapped → same P1-POV values.

    This invariant requires TRULY symmetric probabilities at an equal score:
    P(win) = 0.5, and win-gammon == lose-gammon, win-bg == lose-bg.
    Under those conditions bary_onroll_a == bary_onroll_b at equal score, so
    swapping axes (on_roll==2 → P1-POV) preserves bary_p1_a and bary_p1_b.
    """
    # Symmetric: eval_win=0.5, eval_win_g = eval_lose_g = 0.20,
    # eval_win_bg = eval_lose_bg = 0.02
    common = dict(
        eval_win=0.50, eval_win_g=0.20, eval_win_bg=0.02,
        eval_lose_g=0.20, eval_lose_bg=0.02,
        score_away_p1=7, score_away_p2=7,
    )
    p1_row = make_pos(position_id="sym_001", player_on_roll=1,
                      eval_equity=0.0, **common)
    p2_row = make_pos(position_id="sym_002", player_on_roll=2,
                      eval_equity=0.0, **common)

    out = run([p1_row, p2_row])
    r1 = out.row(0, named=True)
    r2 = out.row(1, named=True)

    # With symmetric probs at equal score, bary_p1_a and bary_p1_b must agree.
    assert abs(r1["bary_p1_a"] - r2["bary_p1_a"]) < 1e-6, (
        f"bary_p1_a differs: {r1['bary_p1_a']:.6f} vs {r2['bary_p1_a']:.6f}")
    assert abs(r1["bary_p1_b"] - r2["bary_p1_b"]) < 1e-6, (
        f"bary_p1_b differs: {r1['bary_p1_b']:.6f} vs {r2['bary_p1_b']:.6f}")
    assert abs(r1["cubeless_mwc_p1"] - r2["cubeless_mwc_p1"]) < 1e-6, (
        f"cubeless_mwc_p1 differs: {r1['cubeless_mwc_p1']:.6f} vs "
        f"{r2['cubeless_mwc_p1']:.6f}")


def test_perspective_symmetry_asymmetric_scores():
    """Same position at asymmetric score, on_roll swapped → bary axes swap."""
    # Score: p1=5a, p2=10a, cube=1
    # on_roll=1: eval_win=0.65 (p1 is ahead)
    # on_roll=2: eval_win=0.65 from p2's POV → P(p1 wins) = 0.35
    # => mwc_p1 for r2 should equal 1 - mwc_onroll_r2 = 1 - P(p2 wins | cubeless)

    p1_row = make_pos(
        position_id="asym_001",
        player_on_roll=1,
        eval_win=0.65, eval_win_g=0.25, eval_win_bg=0.03,
        eval_lose_g=0.10, eval_lose_bg=0.01,
        eval_equity=0.30,
        score_away_p1=5, score_away_p2=10,
    )
    p2_row = make_pos(
        position_id="asym_002",
        player_on_roll=2,
        # p2 is on roll with p2=10a away; from p2's perspective their chance
        # to win the game = 1 - 0.65 = 0.35 (p1 has the better game position)
        eval_win=0.35, eval_win_g=0.10, eval_win_bg=0.01,
        eval_lose_g=0.25, eval_lose_bg=0.03,
        eval_equity=-0.30,  # from p2 POV (p2 trailing)
        score_away_p1=5, score_away_p2=10,
    )

    out = run([p1_row, p2_row])
    r1 = out.row(0, named=True)
    r2 = out.row(1, named=True)

    # mwc_p1 must agree
    assert abs(r1["cubeless_mwc_p1"] - r2["cubeless_mwc_p1"]) < 1e-6, (
        f"mwc_p1 differs: {r1['cubeless_mwc_p1']:.6f} vs {r2['cubeless_mwc_p1']:.6f}")

    # bary_p1_a (P1 away) must agree
    assert abs(r1["bary_p1_a"] - r2["bary_p1_a"]) < 1e-6, (
        f"bary_p1_a differs: {r1['bary_p1_a']:.6f} vs {r2['bary_p1_a']:.6f}")

    # cubeful_equity_p1: r1 uses +0.30 (on_roll=p1), r2 uses -(-0.30)=+0.30
    assert abs(r1["cubeful_equity_p1"] - 0.30) < 1e-9
    assert abs(r2["cubeful_equity_p1"] - 0.30) < 1e-9


# ---------------------------------------------------------------------------
# Test 2: cube_value == 0 treated as 1
# ---------------------------------------------------------------------------

def test_cube_zero_equals_cube_one():
    """cube_value=0 and cube_value=1 produce identical results."""
    row_c0 = make_pos(position_id="cube0", cube_value=0)
    row_c1 = make_pos(position_id="cube1", cube_value=1)

    out = run([row_c0, row_c1])
    r0 = out.row(0, named=True)
    r1 = out.row(1, named=True)

    for col in ["bary_p1_a", "bary_p1_b", "cubeless_mwc_p1", "bary_onroll_a"]:
        assert abs(r0[col] - r1[col]) < 1e-9, (
            f"{col}: cube=0 gives {r0[col]:.9f}, cube=1 gives {r1[col]:.9f}")


# ---------------------------------------------------------------------------
# Test 3: bounds
# ---------------------------------------------------------------------------

def test_bounds():
    """bary_p1_a/b >= 0, cubeless_mwc_p1 in [0, 1]."""
    rows = [
        make_pos(position_id="b1", player_on_roll=1,
                 eval_win=0.01, eval_win_g=0.0, eval_win_bg=0.0,
                 eval_lose_g=0.90, eval_lose_bg=0.50, score_away_p1=1, score_away_p2=1),
        make_pos(position_id="b2", player_on_roll=2,
                 eval_win=0.99, eval_win_g=0.80, eval_win_bg=0.40,
                 eval_lose_g=0.0, eval_lose_bg=0.0, score_away_p1=1, score_away_p2=1),
        make_pos(position_id="b3", player_on_roll=1,
                 eval_win=0.50, eval_win_g=0.20, eval_win_bg=0.02,
                 eval_lose_g=0.18, eval_lose_bg=0.01,
                 score_away_p1=15, score_away_p2=15, cube_value=4),
    ]
    out = run(rows)
    for row in out.iter_rows(named=True):
        assert row["bary_p1_a"] >= -1e-9, f"bary_p1_a < 0: {row['bary_p1_a']}"
        assert row["bary_p1_b"] >= -1e-9, f"bary_p1_b < 0: {row['bary_p1_b']}"
        assert 0.0 - 1e-9 <= row["cubeless_mwc_p1"] <= 1.0 + 1e-9, (
            f"mwc_p1 out of [0,1]: {row['cubeless_mwc_p1']}")


# ---------------------------------------------------------------------------
# Test 4: cubeful_equity_p1 sign cross-check
# ---------------------------------------------------------------------------

def test_cubeful_equity_sign():
    """cubeful_equity_p1 == +eval_equity when on_roll=1, -eval_equity when on_roll=2."""
    eq = 0.345
    row1 = make_pos(position_id="eq1", player_on_roll=1, eval_equity=eq)
    row2 = make_pos(position_id="eq2", player_on_roll=2, eval_equity=eq)

    out = run([row1, row2])
    r1 = out.row(0, named=True)
    r2 = out.row(1, named=True)

    assert abs(r1["cubeful_equity_p1"] - eq) < 1e-9, (
        f"on_roll=1: expected {eq}, got {r1['cubeful_equity_p1']}")
    assert abs(r2["cubeful_equity_p1"] - (-eq)) < 1e-9, (
        f"on_roll=2: expected {-eq}, got {r2['cubeful_equity_p1']}")


# ---------------------------------------------------------------------------
# Test 5: on-roll-POV preserved
# ---------------------------------------------------------------------------

def test_onroll_pov_preserved():
    """bary_onroll_a/b should equal the result you'd get from the old script
    (treating our_away = score_away_p1 when on_roll=1)."""
    row = make_pos(
        player_on_roll=1,
        eval_win=0.60, eval_win_g=0.24, eval_win_bg=0.02,
        eval_lose_g=0.14, eval_lose_bg=0.01,
        score_away_p1=5, score_away_p2=8, cube_value=2,
    )
    out = run([row])
    r = out.row(0, named=True)

    # For on_roll=1: our_away=5, opp_away=8, cube_eff=2
    # Destinations: win wins (our=5 stays), opp: 8-6=2, 8-4=4, 8-2=6
    # Lose: our: 5-2=3, 5-4=1, 5-6=0(clipped), opp=8
    p_wbg = 0.02
    p_wg  = 0.24 - 0.02   # 0.22
    p_ws  = 0.60 - 0.24   # 0.36
    p_ls  = (1.0 - 0.60) - 0.14   # 0.26
    p_lg  = 0.14 - 0.01   # 0.13
    p_lbg = 0.01

    # On-roll-POV: our=p1=5 (wins), opp=p2=8
    # bary_onroll_a = sum(p_i * da_i):
    # da1=5, da2=5, da3=5 (win → our stays), da4=3, da5=1, da6=0
    # bary_onroll_b = sum(p_i * db_i):
    # db1=2, db2=4, db3=6, db4=8, db5=8, db6=8
    expected_bary_a = (p_wbg*5 + p_wg*5 + p_ws*5 +
                       p_ls*3 + p_lg*1 + p_lbg*0)
    expected_bary_b = (p_wbg*2 + p_wg*4 + p_ws*6 +
                       p_ls*8 + p_lg*8 + p_lbg*8)

    assert abs(r["bary_onroll_a"] - expected_bary_a) < 1e-5, (
        f"bary_onroll_a: {r['bary_onroll_a']:.6f} vs {expected_bary_a:.6f}")
    assert abs(r["bary_onroll_b"] - expected_bary_b) < 1e-5, (
        f"bary_onroll_b: {r['bary_onroll_b']:.6f} vs {expected_bary_b:.6f}")

    # For on_roll=1, P1-POV == on-roll-POV
    assert abs(r["bary_p1_a"] - r["bary_onroll_a"]) < 1e-9
    assert abs(r["bary_p1_b"] - r["bary_onroll_b"]) < 1e-9


# ---------------------------------------------------------------------------
# Test 6: disp and disp_magnitude
# ---------------------------------------------------------------------------

def test_displacement_columns():
    """disp_p1_a = bary_p1_a - score_away_p1, disp_magnitude = sqrt(da²+db²)."""
    row = make_pos(score_away_p1=7, score_away_p2=7, player_on_roll=1)
    out = run([row])
    r = out.row(0, named=True)

    assert abs(r["disp_p1_a"] - (r["bary_p1_a"] - 7)) < 1e-9
    assert abs(r["disp_p1_b"] - (r["bary_p1_b"] - 7)) < 1e-9
    expected_mag = (r["disp_p1_a"]**2 + r["disp_p1_b"]**2)**0.5
    assert abs(r["disp_magnitude_p1"] - expected_mag) < 1e-9


# ---------------------------------------------------------------------------
# Test 7: cube_gap_p1
# ---------------------------------------------------------------------------

def test_cube_gap():
    """cube_gap_p1 = cubeful_equity_p1 - cubeless_equity_p1."""
    row = make_pos(eval_equity=0.15, player_on_roll=1)
    out = run([row])
    r = out.row(0, named=True)

    expected_gap = r["cubeful_equity_p1"] - r["cubeless_equity_p1"]
    assert abs(r["cube_gap_p1"] - expected_gap) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: large cube clips to 0
# ---------------------------------------------------------------------------

def test_large_cube_clips():
    """Very large cube should push destinations to 0 (not negative)."""
    row = make_pos(cube_value=32, score_away_p1=3, score_away_p2=3,
                   player_on_roll=1,
                   eval_win=0.55, eval_win_g=0.20, eval_win_bg=0.01,
                   eval_lose_g=0.18, eval_lose_bg=0.01)
    out = run([row])
    r = out.row(0, named=True)
    assert r["bary_p1_a"] >= 0
    assert r["bary_p1_b"] >= 0
