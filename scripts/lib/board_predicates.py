"""Board-level helper predicates used by the theme classifier.

These are pure Python functions meant to be applied via Polars
``map_elements`` on the ``board_p1`` / ``board_p2`` list columns. They
cover the two board-scan features that are not already in
``positions_enriched`` but that several theme predicates need:

- ``max_gap_p1(board_p1)`` — largest empty-point stretch between the
  back-most p1 checker and point 7 (Connectivity theme).
- ``can_hit_this_roll(board_p1, board_p2, dice)`` — structural
  reachability of a hit on this roll (Hit-or-Not theme).

Board convention (matches ``compute_features.py``):
- ``board[0]``     = on-bar count
- ``board[1..24]`` = points from each player's own POV (1 = home ace)
- ``board[25]``    = borne-off count
- A p2 checker at p2-index ``j`` is on p1-coordinate ``25 - j``.
"""

from __future__ import annotations

from typing import Sequence


def max_gap_p1(board_p1: Sequence[int]) -> int:
    """Return the longest run of empty points between p1's back-most
    checker (excluding bar) and point 7 inclusive.

    A low value indicates good connectivity. Returns 0 if no checkers
    remain in the outfield/back or the back-most checker is inside the
    home board.
    """
    back = 0
    for i in range(24, 0, -1):
        if board_p1[i] > 0:
            back = i
            break
    if back <= 7:
        return 0

    best = cur = 0
    for i in range(7, back + 1):
        if board_p1[i] == 0:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _blot_positions_p1_coord(board_p2: Sequence[int]) -> list[int]:
    """p2 blot positions, expressed in p1's coordinate system (1..24)."""
    return [25 - j for j in range(1, 25) if board_p2[j] == 1]


def _p2_made_p1_coord(board_p2: Sequence[int]) -> set[int]:
    """p2 made points (>=2), in p1's coordinate system."""
    return {25 - j for j in range(1, 25) if board_p2[j] >= 2}


def can_hit_this_roll(
    board_p1: Sequence[int],
    board_p2: Sequence[int],
    dice: Sequence[int] | None,
) -> bool:
    """Return True if p1 can hit a p2 blot on this roll.

    Structural reachability only — does not enumerate legal move
    sequences. Covers direct hits with each die, combined hits using
    both dice with a non-blocked intermediate, and bar-entry hits.
    Doubles are treated as a single direct die (the combined-direction
    logic suffices for the theme threshold; false negatives on
    4-step doubles hits are acceptable for theme classification).
    """
    if dice is None or len(dice) < 2:
        return False
    d1, d2 = int(dice[0]), int(dice[1])

    blots = _blot_positions_p1_coord(board_p2)
    if not blots:
        return False

    # Bar case — p1 must enter before hitting from the outfield. Bar
    # entry lands at p1-points 25-die (i.e. d1 enters on point 25-d1 on
    # the opponent home board).
    if board_p1[0] > 0:
        for d in {d1, d2}:
            entry = 25 - d
            if entry in blots:
                return True
        return False

    p1_pos = {i for i in range(1, 25) if board_p1[i] > 0}
    p2_made = _p2_made_p1_coord(board_p2)

    # Direct hits.
    for y in blots:
        for d in {d1, d2}:
            src = y + d
            if src <= 24 and src in p1_pos:
                return True

    # Combined hit using both dice: checker at y+d1+d2, intermediate at
    # y+d1 or y+d2 must not be a p2 made point.
    if d1 != d2:
        for y in blots:
            src = y + d1 + d2
            if src <= 24 and src in p1_pos:
                if (y + d1) <= 24 and (y + d1) not in p2_made:
                    return True
                if (y + d2) <= 24 and (y + d2) not in p2_made:
                    return True
    else:
        # Doubles: consider 2-step and 3-step hits as well, each
        # intermediate checked against p2 made points.
        d = d1
        for y in blots:
            for k in (2, 3, 4):
                src = y + k * d
                if src > 24 or src not in p1_pos:
                    continue
                intermediates_clear = True
                for m in range(1, k):
                    inter = y + m * d
                    if inter in p2_made:
                        intermediates_clear = False
                        break
                if intermediates_clear:
                    return True

    return False
