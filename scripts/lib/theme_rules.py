"""Thematic position classifier rules.

Each theme is exposed as a module-level function returning a Polars
boolean expression (``pl.Expr``). Predicates reference columns present
in ``positions_enriched`` plus five ancillary columns the classifier
adds before evaluation:

    num_checkers_back_p2     sum of board_p2[19..24]
    anchors_back_p1          count of board_p1[20..24] >= 2
    ace_anchor_only_p1       board_p1[24] >= 2 AND board_p1[19..23] all < 2
    max_gap_p1               scripts.lib.board_predicates.max_gap_p1
    can_hit_this_roll_p1     scripts.lib.board_predicates.can_hit_this_roll

Trajectory themes (Breaking Anchor, Post-Blitz Turnaround,
Post-Ace-Point) use lagged or rolling columns that are only populated
after the ``--trajectory`` subcommand has run.

The canonical source for theme definitions and citations is
``docs/themes/theme_dictionary.md``.
"""

from __future__ import annotations

import polars as pl


# ── Phase axes ──────────────────────────────────────────────────────

def _is_contact() -> pl.Expr:
    return pl.col("match_phase") == 0


def _is_race() -> pl.Expr:
    return pl.col("match_phase") == 1


def _is_bearoff() -> pl.Expr:
    return pl.col("match_phase") == 2


# ── Theme predicates (Phase A — structural) ─────────────────────────

def theme_opening() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("move_number") <= 6)
        & (pl.col("num_borne_off_p1") == 0)
        & (pl.col("num_borne_off_p2") == 0)
        & (pl.col("num_on_bar_p1") == 0)
        & (pl.col("num_on_bar_p2") == 0)
        & (pl.col("pip_count_p1") >= 150)
        & (pl.col("pip_count_p2") >= 150)
    )


def theme_flexibility() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("move_number") <= 12)
        & (pl.col("num_builders_p1") >= 3)
        & (pl.col("longest_prime_p1") <= 2)
        & (pl.col("num_blots_p1") >= 2)
        & (pl.col("num_points_made_p1") <= 5)
    )


def theme_middle_game() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("move_number") > 6)
        & ((pl.col("pip_count_p1") + pl.col("pip_count_p2")) >= 150)
        & (pl.col("num_borne_off_p1") == 0)
        & (pl.col("num_borne_off_p2") == 0)
    )


def theme_5_point() -> pl.Expr:
    # board_p1[5] >= 2 or board_p2[5] >= 2 (the 5-point in either POV).
    b1_5 = pl.col("board_p1").list.get(5).cast(pl.Int32) >= 2
    b2_5 = pl.col("board_p2").list.get(5).cast(pl.Int32) >= 2
    return (
        _is_contact()
        & (pl.col("move_number") <= 14)
        & (b1_5 | b2_5)
        & (pl.col("num_checkers_back_p1") <= 2)
        & (pl.col("num_checkers_back_p2") <= 2)
    )


def theme_blitz() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("move_number") <= 18)
        & (pl.col("home_board_points_p1") >= 3)
        & ((pl.col("num_on_bar_p2") > 0) | (pl.col("num_blots_p2") >= 2))
        & (pl.col("pip_count_p1") <= 135)
        & (pl.col("num_checkers_back_p1") <= 2)
    )


def theme_one_man_back() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("num_checkers_back_p1") == 1)
        & (pl.col("longest_prime_p2") >= 4)
    )


def theme_holding() -> pl.Expr:
    # Single deep anchor (not two — that's Back Game), racing deficit.
    return (
        _is_contact()
        & (pl.col("num_checkers_back_p1") >= 2)
        & (pl.col("back_anchor_p1") >= 20)
        & (pl.col("pip_count_diff") >= 10)
        & (pl.col("anchors_back_p1") == 1)
    )


def theme_priming() -> pl.Expr:
    return (
        _is_contact()
        & ((pl.col("longest_prime_p1") >= 4) | (pl.col("longest_prime_p2") >= 4))
    )


def theme_connectivity() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("max_gap_p1") <= 2)
        & (pl.col("num_blots_p1") <= 1)
        & (pl.col("outfield_blots_p1") == 0)
    )


def theme_hit_or_not() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("decision_type") == "checker")
        & (pl.col("num_blots_p2") >= 1)
        & pl.col("can_hit_this_roll_p1")
    )


def theme_crunch() -> pl.Expr:
    # Structural approximation — Phase B can refine with trajectory deltas.
    return (
        _is_contact()
        & (pl.col("num_blots_p1") >= 3)
        & (pl.col("num_points_made_p1") <= 4)
        & (pl.col("num_checkers_back_p1") >= 2)
        & (pl.col("back_anchor_p1") >= 20)
    )


def theme_action_doubles() -> pl.Expr:
    gammon_stakes = pl.col("gammon_threat") + pl.col("gammon_risk")
    return (
        (pl.col("decision_type") == "cube")
        & pl.col("cube_action_optimal").is_in(["Double/Take", "Double/Pass"])
        & pl.col("eval_win").is_between(0.55, 0.75)
        & (gammon_stakes >= 0.25)
    )


def theme_late_blitz() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("move_number") >= 15)
        & (pl.col("home_board_points_p1") >= 4)
        & ((pl.col("num_on_bar_p2") > 0) | (pl.col("num_blots_p2") >= 2))
        & (pl.col("pip_count_p2") <= 120)
    )


def theme_too_good() -> pl.Expr:
    return (
        (pl.col("decision_type") == "cube")
        & (pl.col("cube_action_optimal") == "No Double")
        & (pl.col("eval_win") >= 0.75)
        & (pl.col("gammon_threat") >= 0.40)
    )


def theme_ace_point() -> pl.Expr:
    # Guard against the starting position, where board_p1[24] == 2 and
    # B1[19..23] are all empty — that's the opening, not an Ace-Point game.
    return (
        _is_contact()
        & (pl.col("num_checkers_back_p1") >= 2)
        & pl.col("ace_anchor_only_p1")
        & (
            (pl.col("move_number") > 8)
            | (pl.col("home_board_points_p2") >= 3)
        )
    )


def theme_back_game() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("anchors_back_p1") >= 2)
        & (pl.col("pip_count_diff") >= 20)
    )


def theme_containment() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("pip_count_diff") <= -10)
        & (pl.col("longest_prime_p1") >= 4)
        & (pl.col("num_checkers_back_p2") >= 1)
        & (pl.col("home_board_points_p1") >= 5)
    )


def theme_playing_gammon() -> pl.Expr:
    return (
        _is_contact()
        & (pl.col("home_board_points_p1") >= 5)
        & ((pl.col("num_on_bar_p2") > 0) | (pl.col("num_checkers_back_p2") >= 2))
        & (pl.col("gammon_threat") >= 0.30)
        & (pl.col("eval_win") >= 0.65)
    )


def theme_saving_gammon() -> pl.Expr:
    return (
        (_is_contact() | _is_race())
        & (pl.col("eval_win") <= 0.10)
        & (pl.col("gammon_risk") >= 0.30)
        & (pl.col("num_borne_off_p1") == 0)
        & (pl.col("num_checkers_back_p1") == 0)
    )


def theme_bearoff_vs_contact() -> pl.Expr:
    # Starting bearoff while opponent still has a back anchor that can hit.
    return (
        _is_contact()
        & (pl.col("num_borne_off_p1") >= 1)
        & (pl.col("num_checkers_back_p2") >= 2)
        & (pl.col("pip_count_p1") <= 60)
    )


def theme_various_endgames() -> pl.Expr:
    # Applied AFTER all other endgame-shaped themes so it acts as a catch-all.
    # The ``& ~any_other_endgame`` exclusion is imposed by the orchestrator
    # (see classify_position_themes.py) — this predicate just narrows to
    # low-pip contact positions.
    return (
        _is_contact()
        & (pl.col("pip_count_p1") <= 70)
        & (pl.col("pip_count_p2") <= 70)
    )


def theme_race() -> pl.Expr:
    return _is_race()


def theme_bearoff() -> pl.Expr:
    return _is_bearoff()


# ── Trajectory themes (Phase B — require lagged/rolling columns) ────

def theme_breaking_anchor() -> pl.Expr:
    """Prior move had a deep anchor (>=2 at 20..24); this move does not."""
    return (
        (pl.col("prev_anchors_back_p1").fill_null(0) >= 1)
        & (pl.col("prev_num_checkers_back_p1").fill_null(0) >= 2)
        & (pl.col("num_checkers_back_p1") < pl.col("prev_num_checkers_back_p1").fill_null(0))
    )


def theme_post_blitz_turnaround() -> pl.Expr:
    """Blitz occurred in the prior K moves but failed — opponent reestablished."""
    return (
        pl.col("blitz_in_window").fill_null(False)
        & _is_contact()
        & (pl.col("num_checkers_back_p2") >= 2)
        & (pl.col("num_on_bar_p2") == 0)
        & pl.col("eval_win").is_between(0.30, 0.70)
    )


def theme_post_ace_point() -> pl.Expr:
    """An ace-point anchor was broken in the prior K moves and p1 races home."""
    return (
        pl.col("ace_point_in_window").fill_null(False)
        & (pl.col("num_checkers_back_p1") <= 1)
        & (_is_contact() | _is_race())
        & (pl.col("pip_count_p1") <= 90)
    )


# ── Registry and priority ordering ──────────────────────────────────

# Phase A themes: (column_name, predicate_fn).  Order does not matter
# for label assignment — booleans are independent.
PHASE_A_THEMES: list[tuple[str, callable]] = [
    ("theme_opening", theme_opening),
    ("theme_flexibility", theme_flexibility),
    ("theme_middle_game", theme_middle_game),
    ("theme_5_point", theme_5_point),
    ("theme_blitz", theme_blitz),
    ("theme_one_man_back", theme_one_man_back),
    ("theme_holding", theme_holding),
    ("theme_priming", theme_priming),
    ("theme_connectivity", theme_connectivity),
    ("theme_hit_or_not", theme_hit_or_not),
    ("theme_crunch", theme_crunch),
    ("theme_action_doubles", theme_action_doubles),
    ("theme_late_blitz", theme_late_blitz),
    ("theme_too_good", theme_too_good),
    ("theme_ace_point", theme_ace_point),
    ("theme_back_game", theme_back_game),
    ("theme_containment", theme_containment),
    ("theme_playing_gammon", theme_playing_gammon),
    ("theme_saving_gammon", theme_saving_gammon),
    ("theme_bearoff_vs_contact", theme_bearoff_vs_contact),
    ("theme_various_endgames", theme_various_endgames),
    ("theme_race", theme_race),
    ("theme_bearoff", theme_bearoff),
]

PHASE_B_THEMES: list[tuple[str, callable]] = [
    ("theme_breaking_anchor", theme_breaking_anchor),
    ("theme_post_blitz_turnaround", theme_post_blitz_turnaround),
    ("theme_post_ace_point", theme_post_ace_point),
]

ALL_THEME_COLUMNS: list[str] = [name for name, _ in PHASE_A_THEMES + PHASE_B_THEMES]

# Priority for ``primary_theme`` resolution (terminal phases first,
# then specific strategic types, falling back to general phases).
PRIMARY_PRIORITY: list[str] = [
    "theme_bearoff",
    "theme_race",
    "theme_bearoff_vs_contact",
    "theme_back_game",
    "theme_ace_point",
    "theme_containment",
    "theme_holding",
    "theme_priming",
    "theme_late_blitz",
    "theme_blitz",
    "theme_post_blitz_turnaround",
    "theme_post_ace_point",
    "theme_breaking_anchor",
    "theme_playing_gammon",
    "theme_too_good",
    "theme_saving_gammon",
    "theme_action_doubles",
    "theme_crunch",
    "theme_5_point",
    "theme_hit_or_not",
    "theme_connectivity",
    "theme_flexibility",
    "theme_one_man_back",
    "theme_middle_game",
    "theme_opening",
    "theme_various_endgames",
]


def primary_theme_expr(columns_present: list[str]) -> pl.Expr:
    """Build a when/then chain that picks the first true theme in
    ``PRIMARY_PRIORITY`` that is also present in ``columns_present``.
    Returns the human-readable theme name (without ``theme_`` prefix)
    or ``"unclassified"`` if no theme fires.
    """
    priority = [c for c in PRIMARY_PRIORITY if c in columns_present]
    if not priority:
        return pl.lit("unclassified").cast(pl.Utf8)

    expr = pl.when(pl.col(priority[0])).then(
        pl.lit(priority[0].removeprefix("theme_"))
    )
    for col in priority[1:]:
        expr = expr.when(pl.col(col)).then(pl.lit(col.removeprefix("theme_")))
    return expr.otherwise(pl.lit("unclassified")).cast(pl.Utf8)


def theme_count_expr(columns_present: list[str]) -> pl.Expr:
    """Sum of boolean theme columns that are present in the frame."""
    present = [c for c in ALL_THEME_COLUMNS if c in columns_present]
    if not present:
        return pl.lit(0).cast(pl.Int8)
    return sum(pl.col(c).cast(pl.Int8) for c in present)
