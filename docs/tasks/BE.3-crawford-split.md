# BE.3 — 1-Away Crawford / Post-Crawford Cell Split

## Objective

Introduce a `crawford_variant` dimension alongside `(score_away_p1,
score_away_p2)` so that 1-away cells are split into three variants —
`normal`, `crawford`, `post_crawford` — in every cell-keyed artifact
and visualization. Under the existing single-axis cell keying, CRA
and PCR positions at the same score end up in the same cloud but obey
qualitatively different cube rules, which distorts the statistics and
the per-cell geometry.

## Pre-requisites

- BE.1 (barycentric_v2.parquet carries `crawford`, `is_post_crawford`).
- BE.2 (bootstrap grouping already accepts extra keys).

## Why

- **Crawford game**: exactly one game per match where the opponent is
  1-away; the cube is frozen at 1. Outcome stakes are fixed at 1/2/3
  points, no cube escalation, no take/drop decisions. Cube gap should
  be ~0.
- **Post-Crawford**: every game after Crawford until match end. Cube
  is live, with the well-known "free-drop" tactical consequences. Cube
  gap and displacement statistics are distinct from both normal cells
  and from Crawford.
- **Normal**: everything else. Includes 1-away rows where both
  `crawford=False` and `is_post_crawford=False` (e.g. 1a-3a before the
  leader clinched their 1-away, which is a transient state). In a
  well-formed match this should be empty; log counts as a data-quality
  metric.

Users care about comparing cube-gap patterns across regimes, and a
common analysis mistake is to average all three together. Splitting
prevents this.

## Inputs

- `data/barycentric/barycentric_v2.parquet` (columns `crawford`,
  `is_post_crawford`, `score_away_p1`, `score_away_p2`).

## Outputs

### `data/barycentric/cell_keys.parquet`

A small lookup table (< 300 rows) used by the service and frontend:

| Column              | Description                                             |
|---------------------|---------------------------------------------------------|
| `cell_id`           | `"a{p1}_b{p2}_{variant}"`.                              |
| `score_away_p1`     |                                                         |
| `score_away_p2`     |                                                         |
| `crawford_variant`  | `normal` / `crawford` / `post_crawford`.                |
| `display_label`     | `"3a-5a"` or `"1a-3a CRA"` / `"1a-3a PCR"`.             |
| `is_one_away`       | `score_away_p1==1 OR score_away_p2==1`.                 |

### `data/barycentric/crawford_audit.txt`

Audit artifact:

- Total positions per variant.
- For each match in a sample, confirm there is ≤ 1 Crawford game.
- Cross-tab: share of `cube_value ∈ {1, 2, 4, 8+}` per variant.
- Count of "anomalous" rows at 1-away where both flags are false.

## Method

### Rules (deterministic classification)

```python
is_one_away = (score_away_p1 == 1) | (score_away_p2 == 1)
variant = (
    when(~is_one_away).then("normal")
    .when(crawford).then("crawford")
    .when(is_post_crawford).then("post_crawford")
    .otherwise("normal")  # anomalous; log count
)
```

Notes:
- For a 1-away cell where neither flag is set (rare in well-formed
  data), we fall back to `normal` so the row is never lost.
- We do **not** try to reconcile the two flags per match here (that's
  a data-pipeline concern, not an explorer concern). BE.3 reports the
  anomaly count; fixing the source data is out of scope.

### Integration points

1. **BE.2 bootstrap** groups by `(score_away_p1, score_away_p2,
   crawford_variant)` using the expression above.
2. **BE.4 service**: all `cell_id` references are looked up via
   `cell_keys.parquet`. Endpoints accept either a `cell_id` string or
   `(score_p1, score_p2, variant)`.
3. **BE.6 score-clouds view**: the 15×15 grid layout widens rows 1
   and columns 1 to show `normal / CRA / PCR` side-by-side at 1-away
   intersections. For 1a-1a, all three variants may be present.

### Stand-alone script

`scripts/compute_cell_keys.py` — ~80 lines. Reads
`barycentric_v2.parquet`, computes variants, emits the lookup parquet
and the audit text.

## Complexity

Low. One polars pass, pure metadata.

## Verification

1. **Uniqueness** — `cell_keys.parquet` has no duplicate
   `(score_p1, score_p2, variant)` rows.

2. **Per-match Crawford count** — sample 1 000 matches, count
   positions per match in variant=`crawford`; should be ≤ one game's
   worth of moves per match.

3. **Cube distribution** — in variant=`crawford`,
   `count(cube_value > 1) == 0` (cube frozen). In variant=`post_crawford`,
   `count(cube_value > 1) > 0`.

4. **Anomalous rows** — anomaly count at 1-away with both flags false
   is < 1 % of 1-away rows; log and warn if higher.

5. **Label consistency** — for every non-1-away cell, `display_label`
   matches the RG convention `"{a}a-{b}a"`.

## Usage

```bash
python scripts/compute_cell_keys.py \
  --input  data/barycentric/barycentric_v2.parquet \
  --output data/barycentric/cell_keys.parquet \
  --audit  data/barycentric/crawford_audit.txt
```

## UI surfacing

The `display_label` column is what the frontend renders. When drawing
15×15 grids, the 1-away row and column use a sub-cell layout:

```
           1a     2a  3a  4a  ...  15a
         ┌─┬─┬─┐ ┌──┐ ┌──┐ ┌──┐
    1a   │N│C│P│ │N │ │N │ …
         ├─┼─┼─┤ │C │ │N │
    2a   │N│ │ │ │P │ …
    3a   │N│ │ │
    ...
```

Where cell `1a-2a` shows three mini-panels (normal/CRA/PCR), `2a-1a`
same, `3a-1a` same, etc. Non-1-away cells stay single-panel.

Color encoding per variant in mini-panels:
- `normal` — default cell background.
- `crawford` — dashed border + "CRA" badge.
- `post_crawford` — dotted border + "PCR" badge.
