# BE.2 — Bootstrap Resampling for Cell Statistics

## Objective

Replace single-sample per-cell aggregates (RG.1's
`barycentric_aggregates.csv`) with **bootstrap-averaged** estimates
that carry an uncertainty (std across sub-samples). This produces
representative statistics that the interactive views can show with σ
overlays (error ellipses, faded color for low-support cells).

## Pre-requisites

- BE.1 complete: `data/barycentric/barycentric_v2.parquet` exists.

## Why

Per the user brief:

> I would like also that the representation should be representative:
> for example, sub-sample from the 16M positions, compute the
> representation, then choose another sub sample of the same size
> (with enough positions), and repeat this a lot of time, then average
> to have a pertinent representation (if possible, give information
> about standard deviation for the different point).

Concretely: the single 500 k sample used by RG.1 leaves rare cells
(`13a-3a`, n=118; `8a-15a`, n=492) very noisy while diagonal cells are
over-supported. We cannot fix that by sampling more from rare cells
(the physics is what it is), but we **can** quantify the noise by
drawing K independent sub-samples and reporting mean ± σ on every
cell-level statistic. This σ is what the UI will surface.

## Inputs

- `data/barycentric/barycentric_v2.parquet` (BE.1).

Key columns used:
- `score_away_p1`, `score_away_p2`, `cube_eff`, `crawford`,
  `is_post_crawford`.
- All P1-POV metrics: `bary_p1_a`, `bary_p1_b`, `disp_p1_a`,
  `disp_p1_b`, `disp_magnitude_p1`, `cubeless_mwc_p1`,
  `cubeful_equity_p1`, `cube_gap_p1`.

## Outputs

### `data/barycentric/bootstrap_cells.parquet`

One row per `(score_away_p1, score_away_p2, crawford_variant,
sampling_mode)`:

| Column                        | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `cell_id`                     | Stable string `"a{p1}_b{p2}_{variant}"`.            |
| `score_away_p1`, `score_away_p2` | Cell coordinates.                                 |
| `crawford_variant`            | `"normal"`, `"crawford"`, `"post_crawford"`.        |
| `sampling_mode`               | `"uniform"` or `"stratified"`.                      |
| `n_total`                     | Size of cell in the full v2 parquet.                |
| `n_draws`                     | Number of draws in which the cell had data.        |
| `draw_size`                   | Rows per draw (CLI `--draw-size`).                  |
| `mean_n_in_draw`              | Average number of cell rows per draw.               |
| For each metric M in the set below:                                                |
| `M_mean`                      | Mean across draws.                                  |
| `M_std`                       | σ across draws (uncertainty).                       |
| `M_p05`, `M_p95`              | 5 / 95 percentiles across draws.                    |
| `low_support`                 | bool: true if `n_total < min_per_cell` or           |
|                               | `n_draws < 0.5 * K` (drives UI fading).             |

Metrics set:
`mean_bary_p1_a`, `mean_bary_p1_b`, `mean_disp_p1_a`, `mean_disp_p1_b`,
`mean_disp_magnitude_p1`, `mean_cubeless_mwc_p1`, `mean_cube_gap_p1`,
`mean_cubeful_equity_p1`.

Covariances (for proper error ellipses in the UI):
`cov_bary_p1_ab_mean`, `cov_bary_p1_ab_std` — computed per draw as
`cov(bary_p1_a, bary_p1_b)` over the cell rows, then aggregated.

### `data/barycentric/bootstrap_report.txt`

- Global parameters (K, draw_size, seed).
- Number of cells × 3 variants × 2 sampling modes.
- Top 10 "noisy" cells by `mean_cubeless_mwc_p1_std`.
- Top 10 "stable" cells by the same metric.
- List of cells with `low_support = True`.

## Method

### CLI parameters

| Flag                       | Default | Description                                                       |
|----------------------------|---------|-------------------------------------------------------------------|
| `--input`                  | `data/barycentric/barycentric_v2.parquet` | Source parquet.          |
| `--output`                 | `data/barycentric/bootstrap_cells.parquet` | Output parquet.         |
| `--report`                 | `data/barycentric/bootstrap_report.txt`   | Text report.             |
| `--k`                      | 50      | Number of bootstrap draws.                                        |
| `--draw-size`              | 500000  | Rows per draw (uniform mode).                                     |
| `--stratified-per-cell`    | 500     | Rows per cell per draw (stratified mode).                         |
| `--min-per-cell`           | 50      | Low-support threshold on `n_total`.                               |
| `--min-per-cell-draw`      | 10      | Skip cell in a draw if fewer rows than this.                      |
| `--seed`                   | 42      | Base seed; draw `k` uses `seed + k`.                              |
| `--modes`                  | `uniform,stratified` | Comma-separated list of sampling modes.                |
| `--with-replacement`       | false   | Classical bootstrap (true) vs sub-sample without replacement.     |

Rationale: user asked for sub-sampling (no replacement implied). We
default to **without replacement** for the uniform mode — conceptually
"choose a different sub-sample each time". An optional `--with-
replacement` mode supports classical bootstrap for confidence
intervals.

### Algorithm

```python
metrics = ["bary_p1_a", "bary_p1_b", "disp_p1_a", "disp_p1_b",
           "disp_magnitude_p1", "cubeless_mwc_p1", "cube_gap_p1",
           "cubeful_equity_p1"]

def run_mode(mode):
    draw_means = []   # list[DataFrame] one per draw, grouped per cell
    for k in range(K):
        rng_seed = seed + k
        if mode == "uniform":
            draw = full.sample(n=draw_size, seed=rng_seed, with_replacement=wr)
        else:  # stratified
            draw = (full
                    .group_by(cell_keys)
                    .map_groups(lambda g: g.sample(
                        n=min(stratified_per_cell, len(g)), seed=rng_seed,
                        with_replacement=wr)))
        agg = (draw.group_by(cell_keys)
                   .agg([pl.len().alias("n_draw"),
                         *[pl.col(m).mean().alias(f"mean_{m}") for m in metrics],
                         pl.cov("bary_p1_a","bary_p1_b").alias("cov_bary_p1_ab")])
                   .filter(pl.col("n_draw") >= min_per_cell_draw))
        agg = agg.with_columns(pl.lit(k).alias("k"))
        draw_means.append(agg)
    stacked = pl.concat(draw_means)
    final = (stacked.group_by(cell_keys)
                    .agg([
                        pl.len().alias("n_draws"),
                        pl.col("n_draw").mean().alias("mean_n_in_draw"),
                        *[pl.col(f"mean_{m}").mean().alias(f"mean_{m}_mean")
                          for m in metrics],
                        *[pl.col(f"mean_{m}").std().alias(f"mean_{m}_std")
                          for m in metrics],
                        *[pl.col(f"mean_{m}").quantile(0.05).alias(f"mean_{m}_p05")
                          for m in metrics],
                        *[pl.col(f"mean_{m}").quantile(0.95).alias(f"mean_{m}_p95")
                          for m in metrics],
                        pl.col("cov_bary_p1_ab").mean().alias("cov_bary_p1_ab_mean"),
                        pl.col("cov_bary_p1_ab").std().alias("cov_bary_p1_ab_std"),
                    ]))
    return final
```

`cell_keys` = `[score_away_p1, score_away_p2, crawford_variant]` where
`crawford_variant` is computed via the rules defined in BE.3. This
fiche *does* materialize the `crawford_variant` column from
`barycentric_v2` flags (reads `crawford`, `is_post_crawford` from the
parquet) so that BE.2 and BE.3 can ship independently. BE.3's job is
to publish the canonical mapping + UI adjustments.

### Memory & performance

With K=50 × 500 k = 25 M rows of aggregate outputs, memory is
dominated by `stacked` at ~50 k cells × 50 draws × 10 numeric
columns ≈ 25 M floats ≈ 200 MB. Fits easily.

Full-parquet scan per draw is the bottleneck: 16 M rows × 50 draws
with IO-bound scanning. Two optimizations:
- Load `barycentric_v2.parquet` once into a polars LazyFrame backed by
  in-memory columns (keeps ~3 GB). Sampling reuses that frame.
- For uniform mode, precompute once a `RNG.permutation(n_total)` and
  slice windows of `draw_size` — turns it into K contiguous slices,
  no per-draw sampling cost.

### `n_total` vs `n_draws`

- `n_total` is the count in the full v2 parquet (authoritative).
- `n_draws` is how many of the K draws produced a valid aggregate for
  the cell. For large cells `n_draws == K`; for tiny cells it may be
  0, and that row ships with `*_std = NaN` and `low_support = True`.

## Complexity

Medium. The script is ~200 lines of polars. Runtime target: < 12 min
for K=50 on 16 M rows.

## Verification

1. **Convergence** — `mean_cubeless_mwc_p1_std` decreases with
   `draw_size` for a given cell; when `draw_size == n_total`, std must
   be 0 (all draws identical, modulo without-replacement vs full set
   — with replacement it should still ≪ 1e-3).

2. **Order of magnitude** — diagonal cells with n > 5 000 in the full
   dataset should have `mean_cubeless_mwc_p1_std < 0.005`. Small cells
   (n < 500) should have `mean_cubeless_mwc_p1_std > 0.01`.

3. **Consistency with v1** — for normal cells (not CRA/PCR), the
   `mean_cubeless_mwc_p1_mean` should match BE.1's single-sample cell
   means within the reported std.

4. **Cells × variants coverage** — the final output should have
   exactly `(15×15 non-1away) + 2×(1-away rows/cols with 3 variants)`
   rows per sampling mode when all cells are populated. Missing cells
   imply rare score combinations (acceptable; log them).

## Usage

```bash
python scripts/bootstrap_cells.py \
  --input  data/barycentric/barycentric_v2.parquet \
  --output data/barycentric/bootstrap_cells.parquet \
  --report data/barycentric/bootstrap_report.txt \
  --k 50 --draw-size 500000 --seed 42

# Smoke test
python scripts/bootstrap_cells.py \
  --input  data/barycentric/barycentric_v2.parquet \
  --output /tmp/bootstrap_cells.parquet \
  --report /tmp/bootstrap_report.txt \
  --k 5 --draw-size 50000
```
