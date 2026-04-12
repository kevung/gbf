# S1 — Exploration & Pattern Discovery (Part C: S1.9)

## Objective

Classify every position in the BMAB dataset into canonical backgammon
strategic themes (Magriel, Woolsey, Robertie).

## Pre-requisites

S0.4 (feature engineering), S0.7 (trajectory graph — for Phase B window
pass).

## Sub-steps

### S1.9 — Thematic Position Classification ✅

**Objective**: Label each of ~81.5M positions with up to 26 canonical
backgammon themes (multi-label + primary theme).

**Implementation**: `scripts/classify_position_themes.py`
**Library**: `scripts/lib/theme_rules.py` (predicates),
`scripts/lib/board_predicates.py` (board-scan helpers)
**Dictionary**: `docs/themes/theme_dictionary.md`
**Tests**: `tests/test_theme_rules.py` (59 tests)

**Input**: `positions_enriched/` (S0.4).
**Output**:
- `position_themes/part-*-*.parquet` — same partition shape as input.
  Keys: `position_id`, `game_id`, `move_number`. 26 boolean columns
  (`theme_opening`, `theme_blitz`, `theme_race`, etc.), derived
  `primary_theme` (Utf8) and `theme_count` (Int8), plus ancillary
  `max_gap_p1` (Int8) and `can_hit_this_roll_p1` (Bool).
- `themes/theme_frequencies.csv` — per-theme count, proportion, mean error,
  mean equity, mean move_number.
- `themes/theme_cooccurrence.csv` — 26×26 upper-triangular Jaccard matrix.

**Dependencies**: S0.4.
**Complexity**: High.

**Two-phase architecture**:

**Phase A — Structural classification** (23 structural + 2 new-feature themes):
- One partition file at a time, Polars lazy, selective column read.
- Derives 5 ancillary columns from board arrays before evaluating predicates:
  `num_checkers_back_p2`, `anchors_back_p1`, `ace_anchor_only_p1`,
  `max_gap_p1`, `can_hit_this_roll_p1`.
- Applies 23 structural predicates + Connectivity + Hit-or-Not.
- `primary_theme` resolved by priority (terminal phases first).

**Phase B — Trajectory classification** (3 game-history themes):
- `--trajectory` flag. Per-partition window pass using game-ordered
  `shift(1).over("game_id")` and `rolling_max(K).over("game_id")`.
- Breaking Anchor: detects anchor count decrease from previous move.
- Post-Blitz Turnaround: opponent ahead after recent blitz window.
- Post-Ace-Point Games: race/bearoff following recent ace-point window.

**26 themes** (grouped):

| Group | Themes |
|-------|--------|
| Opening/Early | Opening, Flexibility, Middle Game |
| Structural | 5-Point, Blitz, One Man Back, Holding, Priming |
| Board Features | Connectivity, Hit or Not? |
| Contact Battles | Crunch, Late Blitz, Containment |
| Cube-Adjacent | Action Doubles, Too Good to Double?, Playing Gammon, Saving Gammon |
| Anchored | Ace-Point, Back Games |
| Trajectory | Breaking Anchor, Post-Blitz Turnaround, Post-Ace-Point |
| Endgame | Bearing Off vs Contact, Various Endgames, Race, Bearoff |

**Primary theme priority** (terminal phases first):
Bearoff > Race > Bearing Off vs Contact > Back Games > Ace-Point >
Containment > Holding > Priming > Late Blitz > Blitz >
Post-Blitz Turnaround > Post-Ace-Point > Breaking Anchor >
Playing Gammon > Too Good > Saving Gammon > Action Doubles >
Crunch > 5-Point > Hit-or-Not > Connectivity > Flexibility >
One Man Back > Middle Game > Opening > Various Endgames.

**Processing strategy** (81.5M rows):
- Phase A: ~15–25 min (sequential partitions, selective column read).
- Phase B: ~10–20 min (per-partition window pass, in-place update).
- Single-machine, matches existing S1/S2 script profiles.

**Verification**:
1. `pytest tests/test_theme_rules.py` — 59 tests (positive + counter-examples).
2. Single-partition spot check: Race+Bearoff don't overlap with contact;
   Opening clusters around move_number ≤ 6; Back Games + Ace-Point < 5%;
   theme_count peaks at 1–3.
3. Full dataset run: row-count equality with input.

**Usage**:
```bash
# Phase A (structural themes)
python scripts/classify_position_themes.py \
  --enriched data/parquet/positions_enriched \
  --output data/parquet/position_themes \
  --summary data/themes

# Phase B (trajectory themes)
python scripts/classify_position_themes.py \
  --enriched data/parquet/positions_enriched \
  --output data/parquet/position_themes \
  --trajectory

# Single partition test
python scripts/classify_position_themes.py \
  --enriched data/parquet/positions_enriched \
  --output /tmp/themes_test \
  --summary /tmp/themes_summary \
  --limit 1
```
