# BE.6 — Score Clouds View (Frontend)

## Objective

Per-score-cell scatter of barycenters, laid out as a 15×15 grid
(plus CRA/PCR sub-panels at the 1-away row/column). Clicking a cell
opens a full-size cell view where the user can draw a rectangle and
select positions, identical to the BE.5 workflow but scoped to one
cell.

## Pre-requisites

- BE.3 `cell_keys.parquet` with variants.
- BE.4 endpoints: `GET /api/bary/scatter?mode=cell&cell_id=…`,
  `GET /api/bary/cells`, `POST /api/bary/select`.
- BE.5 shared canvas helpers (`lib/canvas-bary.js`, color scales).

## Files created

- `explorer/src/views/BaryScoreClouds.svelte` — grid + cell overlay.
- `explorer/src/components/CellThumb.svelte` — one mini-panel.
- `explorer/src/components/CellDetail.svelte` — expanded single-cell
  view.

## UI layout

```
┌──────────────────────────────────────────────────────────────┐
│ Toolbar: Variant view: [split CRA/PCR ▾]  Color: [MWC ▾]    │
│          σ arrow overlay: [off/on]                           │
├──────────────────────────────────────────────────────────────┤
│    x=1a      2a      3a      4a                       15a   │
│ y  ┌──┐ ┌──┐ ┌──┐    ┌──┐    ┌──┐            ┌──┐           │
│ 1a │N │ │N │ │N │    │N │    │N │     ...    │N │           │
│    │C │ │  │ │  │    │  │    │  │            │  │           │
│    │P │ │  │ │  │    │  │    │  │            │  │           │
│    └──┘ └──┘ └──┘    └──┘    └──┘            └──┘           │
│ 2a ┌──┐ ┌──┐ ┌──┐    …                                       │
│    │N │ │N │ │N │                                            │
│    │C │ │  │ │  │                                            │
│    └──┘ └──┘ └──┘                                            │
│ ...                                                          │
└──────────────────────────────────────────────────────────────┘
```

Clicking any sub-panel opens a `CellDetail` overlay covering most of
the viewport.

## `CellThumb.svelte`

Props: `{ cell, colorBy, showArrow }`.

- Renders the cell's stratified sample (lazy — fetch when the thumb
  enters the viewport via `IntersectionObserver`).
- Mini canvas 100×100 px.
- Crosshair at current cell's `(p2_away, p1_away)`.
- Optional σ arrow: from crosshair, arrow to `(mean_bary_p1_b,
  mean_bary_p1_a)` with stroke width ∝ `1 / mwc_p1_std`.
- Footer: `{display_label}` + `n_total`.

Loading state: skeleton background while fetching.

## `CellDetail.svelte`

Full-size single-cell canvas, with:
- Zoom/pan (same as BE.5).
- Rectangle selection (same Shift-drag pattern).
- Fixed axis range `[low-0.5, high+0.5]` around the cell's
  destination envelope (computed from the bootstrap p05/p95 plus a
  margin).
- Crosshair at `(p2_away, p1_away)`.
- Overlays (toggleable):
  - Bootstrap mean displacement arrow.
  - Covariance ellipse (2σ).
- Header: `display_label` + variant badge, `n_total`.
- Close button returns to the grid.

## `BaryScoreClouds.svelte` state

```js
let { onSelectionChange } = $props();
let cells   = $state([]);
let openCell = $state(null);     // cell_id of expanded cell
let variantView = $state('split'); // 'split' | 'normal' | 'crawford' | 'post_crawford'
let colorBy     = $state('mwc_p1');
let showArrow   = $state(true);
```

On mount: `GET /api/bary/cells?sampling=bootstrap` to populate the
grid. Each `CellThumb` lazily fetches its scatter sample.

## Interactions

- Hover cell → show tooltip `"{display_label} — n={n_total} — mwc
  {mean_mwc_p1:.2f} ± {std_mwc_p1:.3f}"`.
- Click cell → open `CellDetail`.
- Inside `CellDetail`, shift-drag → `POST /api/bary/select` with
  `cell_id` set and the rect in cell-local coords; emit upward.

## Layout details

- Non-1-away cells: single sub-panel.
- `1a-Xa` rows (x=1..15) and `Xa-1a` columns: three sub-panels
  stacked vertically (N/C/P). Panel height × 3 in that row.
- `1a-1a` cell: unusual — Crawford can't happen at 1a-1a, so only
  Normal + PCR. Panel accordingly.
- Toolbar toggle "Variant view: split | only normal | only crawford |
  only post_crawford" collapses the layout back to a flat 15×15
  when the user wants a uniform grid.

## Fetching strategy

- Grid load: ≤ 225 cells × 3 variants = ~300 cells → one
  `/api/bary/cells` for aggregates, but do NOT fetch all scatter
  samples up front. Instead:
  - Visible cells (within viewport ± 200 px) request
    `/scatter?mode=cell&cell_id=…&limit=500`.
  - LRU cache of 64 cell samples in frontend memory.

## Verification

- Manual:
  1. Grid renders 225+ thumbnails; diagonal cells are densely blue
     in the center, fading to the RdBu extremes on off-diagonal
     cells.
  2. 1a-5a thumb is almost entirely blue; 5a-1a almost entirely red
     — matching `analysis.md` §4.
  3. Click `1a-2a`. Expect three sub-panels: Normal (tiny), Crawford
     (small), Post-Crawford (larger, cube values > 1).
  4. Open CellDetail on 7a-7a. Shift-drag a rectangle → selection
     panel opens with cards all at `score_away_p1==7,
     score_away_p2==7`.
  5. σ arrow toggle: arrows become visible in CellDetail,
     corresponding to BE.2's `mean_disp_p1_*`.
  6. Variant-view dropdown to "only crawford" hides non-1-away cells,
     keeping only 1-away CRA sub-panels (small n).

## Complexity

Medium. Mostly layout code and the `IntersectionObserver`-driven
lazy-loading pattern. Reuses BE.5's canvas helpers.
