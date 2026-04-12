# Thematic Position Dictionary (S1.9)

Canonical source for the 26 theme labels used by
`scripts/classify_position_themes.py`. Each entry gives the backgammon
definition, the rule predicate, and a citation. The predicates are the
single source of truth — when the Python in `scripts/lib/theme_rules.py`
disagrees with the text here, the Python wins and this document should
be updated to match.

Notation: `B1[i]`, `B2[i]` are `board_p1` and `board_p2` at index `i`
(0 = bar, 1..24 = points from each player's own POV, 25 = off). All
other identifiers are columns in `positions_enriched`. Ancillary
columns (`num_checkers_back_p2`, `anchors_back_p1`, `ace_anchor_only_p1`,
`max_gap_p1`, `can_hit_this_roll_p1`) are computed by
`classify_position_themes.py` just before the predicates run.

Phase axes used below:
- `is_contact  = match_phase == 0`
- `is_race     = match_phase == 1`
- `is_bearoff  = match_phase == 2`

---

## Phase A — Structural themes

### The Opening
Canonical early-game state: both players have full armies, no hits yet,
cube still centered. (Magriel, *Backgammon*, ch. 3.)
```
is_contact & move_number <= 6
  & num_borne_off_p1 == 0 & num_borne_off_p2 == 0
  & num_on_bar_p1 == 0 & num_on_bar_p2 == 0
  & pip_count_p1 >= 150 & pip_count_p2 >= 150
```

### Flexibility
Many builders and few committed points — the position is "soft,"
maximising choices for future points. Characteristic of games where
neither side has yet committed to a concrete strategy. (Robertie,
*Advanced Backgammon* vol. 1.)
```
is_contact & move_number <= 12
  & num_builders_p1 >= 3 & longest_prime_p1 <= 2
  & num_blots_p1 >= 2 & num_points_made_p1 <= 5
```

### The Middle Game
Post-opening contact play. Either side may still commit to blitz, prime,
hold, or back-game. Overlap with more specific contact themes is
expected. (Woolsey, *How to Play Tournament Backgammon*.)
```
is_contact & move_number > 6
  & (pip_count_p1 + pip_count_p2) >= 150
  & num_borne_off_p1 == 0 & num_borne_off_p2 == 0
```

### The 5-Point
The battle for the 5-points (p1's and p2's). Typically early
middle-game. (Magriel, *Backgammon*, "The 5-Point".)
```
is_contact & move_number <= 14
  & (B1[5] >= 2 | B2[5] >= 2)
  & num_checkers_back_p1 <= 2 & num_checkers_back_p2 <= 2
```

### The Blitz
Aggressive attack on opponent's back checkers while building an early
home board. (Robertie, *Modern Backgammon*, "Blitzes".)
```
is_contact & move_number <= 18
  & home_board_points_p1 >= 3
  & (num_on_bar_p2 > 0 | num_blots_p2 >= 2)
  & pip_count_p1 <= 135 & num_checkers_back_p1 <= 2
```

### One Man Back
Exactly one p1 checker in opponent's home while opponent is building a
prime to trap it. Critical escape / timing game. (Magriel, *Backgammon*,
"The One-Checker Game".)
```
is_contact & num_checkers_back_p1 == 1 & longest_prime_p2 >= 4
```

### Holding Games
Single deep anchor (2+ checkers on one point at 20-24), pip deficit,
waiting for hits. (Robertie, *Advanced Backgammon* vol. 2.)
```
is_contact & num_checkers_back_p1 >= 2 & back_anchor_p1 >= 20
  & pip_count_diff >= 10 & anchors_back_p1 == 1
```

### Priming Games
Either side has built a 4+ prime. (Magriel, *Backgammon*, "Priming
Games".)
```
is_contact & (longest_prime_p1 >= 4 | longest_prime_p2 >= 4)
```

### Connectivity
Well-connected army: short gaps between checkers, few blots. Indicates
a flexible mid-game structure. (Woolsey, *The Backgammon
Encyclopedia*.)
```
is_contact & max_gap_p1 <= 2
  & num_blots_p1 <= 1 & outfield_blots_p1 == 0
```

### Hit or Not?
The checker-play decision when p2 has a blot that p1 can structurally
hit on the current roll. Classic checker-play fork. (Woolsey,
*How to Play Tournament Backgammon*.)
```
is_contact & decision_type == "checker"
  & num_blots_p2 >= 1 & can_hit_this_roll_p1
```

### Crunch Positions
Forced to break a point due to bad dice; ragged structure. Phase A uses
a structural approximation; Phase B can refine with trajectory
deltas. (Magriel, *Backgammon*, "Crunches".)
```
is_contact & num_blots_p1 >= 3 & num_points_made_p1 <= 4
  & num_checkers_back_p1 >= 2 & back_anchor_p1 >= 20
```

### Action Doubles
Cube decision where correct action is Double/Take or Double/Pass, with
significant gammon stakes (volatile). (Robertie, *Modern Backgammon*,
"Action Doubles".)
```
decision_type == "cube"
  & cube_action_optimal in ("Double/Take", "Double/Pass")
  & 0.55 <= eval_win <= 0.75
  & (gammon_threat + gammon_risk) >= 0.25
```

### Late Game Blitz
Blitz pressure after move 15 — often closeout attempts in the late
middle game. (Robertie, *Modern Backgammon*, "Late Attack".)
```
is_contact & move_number >= 15 & home_board_points_p1 >= 4
  & (num_on_bar_p2 > 0 | num_blots_p2 >= 2)
  & pip_count_p2 <= 120
```

### Too Good to Double?
Winning position where the correct cube action is No Double — doubling
would give up gammon equity. (Magriel, *Backgammon*, "Too Good to
Double".)
```
decision_type == "cube" & cube_action_optimal == "No Double"
  & eval_win >= 0.75 & gammon_threat >= 0.40
```

### Ace-Point Games
Only back anchor is the opponent's ace-point (p1-index 24). Low-gammon
defensive game. (Magriel, *Backgammon*, "Ace-Point Games".)
```
is_contact & num_checkers_back_p1 >= 2 & ace_anchor_only_p1
  & (move_number > 8 | home_board_points_p2 >= 3)
```
The `move_number > 8 | home_board_points_p2 >= 3` guard excludes the
starting position, which trivially satisfies `ace_anchor_only_p1`.

### Back Games
Two anchors in opponent's home (20..24), pip deficit — long positional
game waiting for shots. (Woolsey, *Backgammon Openings* vol. 2.)
```
is_contact & anchors_back_p1 >= 2 & pip_count_diff >= 20
```

### The Containment Game
p1 ahead in race but p2 trapped behind a prime / closed board. (Magriel,
*Backgammon*, "Containment".)
```
is_contact & pip_count_diff <= -10 & longest_prime_p1 >= 4
  & num_checkers_back_p2 >= 1 & home_board_points_p1 >= 5
```

### Playing for a Gammon
Winning position where the gammon is in reach — closed/near-closed
board, opponent trapped. (Robertie, *Advanced Backgammon* vol. 2,
"Playing for a Gammon".)
```
is_contact & home_board_points_p1 >= 5
  & (num_on_bar_p2 > 0 | num_checkers_back_p2 >= 2)
  & gammon_threat >= 0.30 & eval_win >= 0.65
```

### Saving the Gammon
Losing badly with gammon risk; priority is to bring checkers home.
(Woolsey, *How to Play Tournament Backgammon*, "Saving the Gammon".)
```
(is_contact | is_race) & eval_win <= 0.10 & gammon_risk >= 0.30
  & num_borne_off_p1 == 0 & num_checkers_back_p1 == 0
```

### Bearing Off Against Contact
p1 starting bearoff while p2 still has a back anchor. The most
error-prone bearoff scenario. (Magriel, *Backgammon*, "Bearoffs with
Contact".)
```
is_contact & num_borne_off_p1 >= 1
  & num_checkers_back_p2 >= 2 & pip_count_p1 <= 60
```

### Various Endgames
Catch-all: contact endgame technicalities that don't match any of the
specific endgame themes above. Suppressed when any of
{Bearoff-vs-Contact, Back Game, Ace-Point, Containment, Holding} fires.
```
is_contact & pip_count_p1 <= 70 & pip_count_p2 <= 70
  & !(bearoff_vs_contact | back_game | ace_point | containment | holding)
```

### The Race
No contact remains. (Magriel, *Backgammon*, "The Race".)
```
match_phase == 1
```

### The Bearoff
All checkers in home boards on both sides. (Magriel, *Backgammon*,
"The Bearoff".)
```
match_phase == 2
```

---

## Phase B — Trajectory themes

These depend on prior positions from the same game and only fire after
`classify_position_themes.py --trajectory` has run.

### Breaking Anchor
Prior move had a deep anchor (>=2 checkers at 20..24); this move no
longer does. (Magriel, *Backgammon*, "Breaking the Anchor".)
```
prev_anchors_back_p1 >= 1 & prev_num_checkers_back_p1 >= 2
  & num_checkers_back_p1 < prev_num_checkers_back_p1
```

### Post-Blitz Turnaround Games
A blitz attempt occurred in the last K=8 moves but failed — opponent
escaped the bar and reestablished. (Robertie, *Modern Backgammon*,
"Failed Blitzes".)
```
blitz_in_window & is_contact
  & num_checkers_back_p2 >= 2 & num_on_bar_p2 == 0
  & 0.30 <= eval_win <= 0.70
```

### Post-Ace-Point Games
An ace-point anchor was active in the last K=8 moves and p1 is now
racing home. (Magriel, *Backgammon*, "Post-Ace-Point Games".)
```
ace_point_in_window & num_checkers_back_p1 <= 1
  & (is_contact | is_race) & pip_count_p1 <= 90
```

---

## Primary theme priority

When a position has multiple themes, `primary_theme` is resolved by
taking the first theme (from top to bottom) that fires:

1. The Bearoff
2. The Race
3. Bearing Off Against Contact
4. Back Games
5. Ace-Point Games
6. The Containment Game
7. Holding Games
8. Priming Games
9. Late Game Blitz
10. The Blitz
11. Post-Blitz Turnaround
12. Post-Ace-Point Games
13. Breaking Anchor
14. Playing for a Gammon
15. Too Good to Double?
16. Saving the Gammon
17. Action Doubles
18. Crunch Positions
19. The 5-Point
20. Hit or Not?
21. Connectivity
22. Flexibility
23. One Man Back
24. The Middle Game
25. The Opening
26. Various Endgames

Positions that match none of the predicates get `primary_theme =
"unclassified"`. Overlapping theme information is preserved in the
26 boolean columns; `primary_theme` exists only for single-label
reporting.
