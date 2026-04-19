# BE.1 — Perspective-Corrected Barycentric + Trajectory Keys

## Objective

Rebuild the barycentric dataset so that every computed quantity is
coherent regardless of which player is on roll, and carries the keys
(`game_id`, `match_id`, `move_number`) needed by the match-trajectory
view. Output a new parquet `data/barycentric/barycentric_v2.parquet`
alongside the existing `barycentric.parquet` (kept untouched for
backward compatibility with `analysis.md`).

## Pre-requisites

- `data/parquet/positions_enriched/` (S0.4 output).
- `data/parquet/games.parquet` (for `match_id`).
- `scripts/compute_barycentric.py` (RG.1 reference implementation;
  **do not modify**, BE.1 creates a sibling script).

## Why this fiche is needed

`compute_barycentric.py` assigns `a = score_away_p1`, `b = score_away_p2`
as "our / opponent", but the outcome probabilities
(`eval_win`, `eval_win_g`, `eval_win_bg`, `eval_lose_g`, `eval_lose_bg`)
come from `positions_enriched` with the player on roll as "us".
Concretely, `eval_win = P(player_on_roll wins the game)`. When
`player_on_roll == 2`, the existing script pairs `eval_win` (= P(P2
wins)) with the destination `(score_p1, score_p2 − 3C)` which is the
destination for a P1 win. This produces an incorrect cubeless MWC for
~50 % of rows and prevents trajectory reconstruction (MWC values would
flip sign every half-move).

The correction is mechanical:
- Compute the barycenter in the on-roll-POV coordinate frame first.
- Publish a second set of columns in P1-POV (mirror axes + flip MWC
  when on_roll == 2).

## Inputs

Column selection (from `positions_enriched`):

| Column              | Required | Type  | Notes                                 |
|---------------------|----------|-------|---------------------------------------|
| `position_id`       | yes      | str   | Primary key.                          |
| `game_id`           | yes      | str   | Join key for `games.parquet`.         |
| `move_number`       | yes      | int16 | Move ordinal inside the game.         |
| `player_on_roll`    | yes      | int8  | 1 or 2.                               |
| `eval_win`          | yes      | f32   | P(on_roll wins).                      |
| `eval_win_g`        | yes      | f32   | P(on_roll wins ≥ gammon).             |
| `eval_win_bg`       | yes      | f32   | P(on_roll wins ≥ backgammon).         |
| `eval_lose_g`       | yes      | f32   | P(on_roll loses ≥ gammon).            |
| `eval_lose_bg`      | yes      | f32   | P(on_roll loses ≥ backgammon).        |
| `eval_equity`       | yes      | f64   | Cubeful equity (on_roll POV).         |
| `score_away_p1`     | yes      | int16 | P1 away score (1..15).                |
| `score_away_p2`     | yes      | int16 | P2 away score (1..15).                |
| `cube_value`        | yes      | int   | 0 = centered (treat as 1).            |
| `crawford`          | yes      | bool  | True if this game is the Crawford.    |
| `is_post_crawford`  | yes      | bool  | True if post-Crawford.                |
| `decision_type`     | opt      | str   | checker / cube action / etc.          |
| `match_phase`       | opt      | str   | Kept for UI filters.                  |
| `gammon_threat`     | opt      | f32   |                                       |
| `gammon_risk`       | opt      | f32   |                                       |
| `dgr`               | opt      | bool  | Dead-gammon-race flag.                |

Filter in-script:
- `score_away_p1 ∈ [1, 15]`, `score_away_p2 ∈ [1, 15]` (MET range).
- `eval_win.is_not_null() AND eval_equity.is_not_null()`.
- `player_on_roll IN (1, 2)`.

## Outputs

### `data/barycentric/barycentric_v2.parquet`

One row per input position. Columns:

| Column                 | Type   | Description                                              |
|------------------------|--------|----------------------------------------------------------|
| `position_id`          | str    | Primary key.                                             |
| `game_id`              | str    |                                                          |
| `match_id`             | str    | From `games.parquet`.                                    |
| `game_number`          | int16  | Game index inside the match (copied from games).         |
| `move_number`          | int16  |                                                          |
| `player_on_roll`       | int8   | 1 / 2.                                                   |
| `score_away_p1`        | int16  |                                                          |
| `score_away_p2`        | int16  |                                                          |
| `cube_value`           | int    | Raw (0 allowed).                                         |
| `cube_eff`             | int    | `max(cube_value, 1)` used for outcome stakes.            |
| `crawford`             | bool   |                                                          |
| `is_post_crawford`     | bool   |                                                          |
| `decision_type`        | str    |                                                          |
| **On-roll-POV block** (for RG.* reproducibility):                                     |
| `bary_onroll_a`        | f64    | Expected "own" away after the game.                      |
| `bary_onroll_b`        | f64    | Expected "opp" away after the game.                      |
| `disp_onroll_a`        | f64    | `bary_onroll_a - our_away`.                              |
| `disp_onroll_b`        | f64    | `bary_onroll_b - opp_away`.                              |
| `cubeless_mwc_onroll`  | f64    | P(on_roll wins match | cubeless).                        |
| `cubeful_equity_onroll`| f64    | = `eval_equity`.                                         |
| **P1-POV block** (canonical for all downstream views):                                |
| `bary_p1_a`            | f64    | Expected P1 away after game.                             |
| `bary_p1_b`            | f64    | Expected P2 away after game.                             |
| `disp_p1_a`            | f64    | `bary_p1_a - score_away_p1`.                             |
| `disp_p1_b`            | f64    | `bary_p1_b - score_away_p2`.                             |
| `disp_magnitude_p1`    | f64    | `sqrt(disp_p1_a² + disp_p1_b²)`.                         |
| `cubeless_mwc_p1`      | f64    | P(P1 wins match | cubeless).                             |
| `cubeless_equity_p1`   | f64    | `2·cubeless_mwc_p1 − 1`.                                 |
| `cubeful_equity_p1`    | f64    | `eval_equity` if on_roll==1, else `-eval_equity`.        |
| `cube_gap_p1`          | f64    | `cubeful_equity_p1 - cubeless_equity_p1`.                |
| **Ancillary**:                                                                        |
| `match_phase`          | str    | Optional, passthrough.                                   |
| `gammon_threat`        | f32    | Optional.                                                |
| `gammon_risk`          | f32    | Optional.                                                |
| `dgr`                  | bool   | Optional.                                                |

### `data/barycentric/barycentric_v2_report.txt`

Sanity report including:
- Row count, elapsed time.
- Distribution of `player_on_roll` (fraction of rows where the fix
  materially changes `mwc`).
- Mean |Δ(mwc_p1, mwc_v1)| by on-roll side.
- Mean `mwc_p1` per score cell vs Kazaross MET — expected deviation
  should be ≤ the current +0.0054 bias after the fix (and may be
  smaller).
- Top 10 cells with highest absolute change vs v1.

## Method

1. **Build MET lookup** — reuse `build_met_lookup()` from existing
   `compute_barycentric.py` (copy, do not import; keeping scripts
   independent is the project convention).
2. **Load positions** — partition-by-partition scan; concatenate
   lazily with polars streaming if the full 16 M rows exceed memory;
   else in-memory concat.
3. **On-roll-POV barycenter**:
   - `our_away = when(on_roll==1).then(score_away_p1).otherwise(score_away_p2)`.
   - `opp_away = when(on_roll==1).then(score_away_p2).otherwise(score_away_p1)`.
   - Six probabilities: `p_wbg = eval_win_bg`, `p_wg = eval_win_g −
     eval_win_bg`, `p_ws = eval_win − eval_win_g`, `p_ls = (1 − eval_win) −
     eval_lose_g`, `p_lg = eval_lose_g − eval_lose_bg`, `p_lbg = eval_lose_bg`.
   - Six destinations (clipped at 0):
     - Win BG: `(our_away, opp_away − 3·cube_eff)`
     - Win G:  `(our_away, opp_away − 2·cube_eff)`
     - Win S:  `(our_away, opp_away − 1·cube_eff)`
     - Lose S: `(our_away − 1·cube_eff, opp_away)`
     - Lose G: `(our_away − 2·cube_eff, opp_away)`
     - Lose BG:`(our_away − 3·cube_eff, opp_away)`
   - Left-join MET lookup on each destination → `met1 … met6`.
   - `bary_onroll_a = Σ pᵢ · dest_aᵢ`, `bary_onroll_b = Σ pᵢ · dest_bᵢ`,
     `cubeless_mwc_onroll = Σ pᵢ · metᵢ`.
   - `disp_onroll_* = bary_onroll_* − (our_away, opp_away)`.
4. **P1-POV projection**:
   - When `on_roll == 1`: `bary_p1_a = bary_onroll_a`,
     `bary_p1_b = bary_onroll_b`, `mwc_p1 = cubeless_mwc_onroll`.
   - When `on_roll == 2`: `bary_p1_a = bary_onroll_b`,
     `bary_p1_b = bary_onroll_a`, `mwc_p1 = 1 − cubeless_mwc_onroll`.
   - `disp_p1_a = bary_p1_a − score_away_p1`,
     `disp_p1_b = bary_p1_b − score_away_p2`.
   - `cubeful_equity_p1 = eval_equity` if on_roll==1 else `-eval_equity`.
   - `cube_gap_p1 = cubeful_equity_p1 − (2·mwc_p1 − 1)`.
5. **Join match_id** — `df.join(games[['game_id','match_id',
   'game_number']], on='game_id', how='left')`.
6. **Select & write parquet** — sort by `(match_id, game_number,
   move_number)` so trajectory queries are disk-ordered.
7. **Sanity report** — compute the diagnostic metrics and write the
   text report.

## Complexity

Medium. Polars-vectorized like the RG.1 script; expected runtime on
16 M rows: 5–10 min on a laptop, 8–12 GB peak RAM. If memory is tight,
switch to partition-at-a-time lazy sinks (`sink_parquet`).

## Verification

1. **Unit test** — `tests/test_compute_barycentric_v2.py`:
   - Synthetic two-row frame with identical physics but inverted
     `player_on_roll`; after BE.1 both rows have the same `bary_p1_a`,
     `bary_p1_b`, `cubeless_mwc_p1` to within 1e-9.
   - Cube-eff handling: row with `cube_value == 0` produces the same
     destinations as a row with `cube_value == 1`.
   - Bounds: `bary_p1_a ≥ 0`, `bary_p1_b ≥ 0`, `mwc_p1 ∈ [0, 1]`.

2. **Aggregate check** — mean `mwc_p1` per cell vs Kazaross MET; max
   absolute deviation across cells should be ≤ 0.08 (current v1 value),
   and the mean deviation should have shifted (the +0.0054 v1 bias
   was on-roll biased; the symmetric P1-POV should either be ~0 or a
   different sign).

3. **Cross-check with `eval_equity`** — for positions with
   `player_on_roll == 2`, `|cubeful_equity_p1 − (−eval_equity)| < 1e-9`.

4. **Trajectory monotonicity smoke test** — for a handful of matches,
   `mwc_p1` series should not flip sign between consecutive positions
   in the absence of blunders (smoother than v1).

## Usage

```bash
# Full dataset
python scripts/compute_barycentric_v2.py \
  --enriched data/parquet/positions_enriched \
  --games    data/parquet/games.parquet \
  --output   data/barycentric \
  --away-max 15

# Smoke run on one partition
python scripts/compute_barycentric_v2.py \
  --enriched data/parquet/positions_enriched \
  --games    data/parquet/games.parquet \
  --output   /tmp/barycentric_v2_test \
  --limit-partitions 1
```

Options:
- `--enriched PATH` — input parquet dir (required).
- `--games PATH` — games.parquet for match_id join (required).
- `--output PATH` — output directory (default `data/barycentric`).
- `--away-max N` — drop rows outside [1, N] (default 15).
- `--limit-partitions N` — for testing.
- `--sample N` — sub-sample N rows (used for quick iteration; the
  final pipeline should NOT sample here — sampling belongs to BE.2).

## Migration notes

- Keep `data/barycentric/barycentric.parquet` (v1) in place; do not
  overwrite. `visualize_barycentric.py` (RG.2–RG.6) continues to
  consume v1 so existing PNGs remain reproducible.
- All BE.* frontend/backend code reads v2 exclusively.
- The old `barycentric_aggregates.csv` is superseded by BE.2's
  `bootstrap_cells.parquet` for any interactive use.
