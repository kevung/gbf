# Reverse Gammon — Barycentric Visualization in MWC Space

## Objective

Represent each position purely by its analysis data and match score,
ignoring the board layout. Each position becomes a geometric point: the
probability-weighted centroid (barycenter) of the six possible outcome
destinations in the score plane, with match winning chances from the
Kazaross-XG2 MET as the projection onto a scalar axis.

This "reverse gammon" view reduces a position to its statistical
fingerprint: where does this position push the match?

## Pre-requisites

S0.4 (feature engineering — `positions_enriched` parquet with eval
columns), S3.2 (MET verification — Kazaross-XG2 reference tables).

---

## Mathematical Framework

### Six Outcomes

Position at score `(a, b)` with cube value `C` and XG analysis
`(w, g, bg, gl, bgl)`:

| # | Outcome        | Prob `p_i`      | Destination `(a', b')`      |
|---|----------------|-----------------|------------------------------|
| 1 | Win backgammon | `bg`            | `(a, max(b - 3C, 0))`       |
| 2 | Win gammon     | `g - bg`        | `(a, max(b - 2C, 0))`       |
| 3 | Win simple     | `w - g`         | `(a, max(b - C, 0))`        |
| 4 | Lose simple    | `(1-w) - gl`    | `(max(a - C, 0), b)`        |
| 5 | Lose gammon    | `gl - bgl`      | `(max(a - 2C, 0), b)`       |
| 6 | Lose backgammon| `bgl`           | `(max(a - 3C, 0), b)`       |

Convention: `MET(0, b) = 1.0` (match won), `MET(a, 0) = 0.0` (match
lost).

### Cubeless Barycenter (2D)

Score-space barycenter: `B = Sum p_i * (a'_i, b'_i)`.

Displacement vector: `D = B - (a, b)` — direction and magnitude of
expected score movement.

### Cubeless MWC (1D)

`MWC_cubeless = Sum p_i * MET(a'_i, b'_i)` — scalar, used as color.

### Cubeful Representation

Cube gap: `cube_gap = eval_equity - (2 * MWC_cubeless - 1)`.

Approaches (incremental):
- **(A)** Dual encoding: barycenter as position, cube_gap as size/color.
- **(B)** MET inversion: find score whose MET matches cubeful MWC, draw
  a segment from cubeless to cubeful point.
- **(C)** Effective probability redistribution (research extension).

---

## Sub-steps

### RG.1 — Compute Barycentric Coordinates

**Script**: `scripts/compute_barycentric.py`
**Input**: `data/parquet/positions_enriched/`
**Output**: `data/barycentric/` (parquet + CSV aggregates)
**Complexity**: Medium.

**Method**:
1. Build MET lookup DataFrame (225 cells + edge cases for a=0, b=0)
2. Compute 6 outcome probabilities per row (vectorized Polars)
3. Compute 6 destination score pairs (clamped at 0)
4. Join each destination with MET lookup (6 left-joins)
5. Compute: `bary_a`, `bary_b`, `disp_a`, `disp_b`, `cubeless_mwc`,
   `cubeless_equity`, `cube_gap`, `disp_magnitude`
6. Aggregate per score cell: mean/std of all computed fields
7. Write parquet (per-position) + CSV (per-cell aggregates)

**Output columns**: `position_id, score_away_p1, score_away_p2,
cube_value, crawford, bary_a, bary_b, disp_a, disp_b,
disp_magnitude, cubeless_mwc, cubeless_equity, cubeful_equity,
cube_gap, match_phase, gammon_threat, gammon_risk, decision_type`

---

### RG.2 — Displacement Vector Field

**Script**: `scripts/visualize_barycentric.py`
**Input**: `data/barycentric/` aggregates
**Output**: `data/barycentric/plots/displacement_field.png`
**Complexity**: Low.

15x15 quiver plot over the score grid:
- Arrow direction = mean displacement `(disp_a, disp_b)`
- Arrow length = mean displacement magnitude (volatility)
- Arrow color = mean cubeless MWC (blue=winning, red=losing)

---

### RG.3 — Cube Gap Heatmap

**Input**: Per-cell aggregates
**Output**: `data/barycentric/plots/cube_gap_heatmap.png`
**Complexity**: Low.

15x15 grid, color = `mean(cube_gap)` per score cell. Shows where cube
ownership matters most.

---

### RG.4 — MWC Distribution Histograms

**Input**: Per-position barycentric parquet
**Output**: `data/barycentric/plots/mwc_distributions/`
**Complexity**: Low.

Per score cell: histogram of `cubeless_mwc`. Overlay Kazaross MET as
vertical line. Small multiples grid or selected cells.

---

### RG.5 — Per-Cell Barycenter Scatter Clouds

**Input**: Per-position barycentric parquet (sampled)
**Output**: `data/barycentric/plots/score_clouds/`
**Complexity**: Medium.

For selected score cells: scatter of `(bary_b, bary_a)` with crosshair
at current score. Color = cubeless MWC, size = |cube_gap|.

---

### RG.6 — Global Scatter

**Input**: Stratified sample (~500 per cell)
**Output**: `data/barycentric/plots/global_scatter.png`
**Complexity**: Low.

All barycenters in score space. Color by origin score or cubeless MWC.

---

## Practical Considerations

- **Cube value 0 (centered)**: treat as C=1 for outcome stakes
- **Crawford**: compute normally with C=1, flag separately
- **Away > 15**: exclude (outside MET table) or Janowski approximation
- **Dead gammons**: destinations collapse, barycenter compressed — flag
  `dgr=True` positions
- **Scale**: vectorized Polars handles 16M rows; scatter uses sampling

## Verification

- Equal w/l at tied score with no gammons: barycenter at `(n-C/2, n-C/2)`
- Early-game mean `cubeless_mwc` per cell ~ Kazaross MET (cross-check S3.2)
- Mean `cube_gap > 0` at non-Crawford, non-DMP scores
- Displacement arrows point toward winning for favored player
