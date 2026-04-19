# BE.5 — Global Scatter View (Frontend)

## Objective

Interactive Svelte component that renders the dataset-wide scatter of
barycenters in score space (RG.6's static PNG, but live), supports
zoom/pan, and lets the user draw a rectangle to select positions. The
selection is handed off to the shared selection panel (BE.8) which
opens a list of board cards.

## Pre-requisites

- BE.4 endpoints live (`/api/bary/scatter?mode=global`,
  `/api/bary/cells`, `POST /api/bary/select`).
- BE.2 cell aggregates available for optional σ overlays.
- Vite proxy wired (BE.9).

## Files created

- `explorer/src/views/BaryGlobalScatter.svelte` — the view.
- `explorer/src/lib/bary-api.js` — shared fetch helpers for all BE.*
  views (defines `fetchScatter`, `fetchCells`, `postSelect`,
  `fetchMatch`, `fetchPosition` used by BE.5/6/7/8).
- `explorer/src/lib/color-scales.js` — RdBu diverging scale matching
  the RG plots.

## UI layout

```
┌──────────────────────────────────────────────────────────────┐
│ Toolbar: Color: [MWC ▾]  Variant: [all ▾]  Cube: [1..8]     │
│          Decision: [checker ▾]  σ overlay: [off/ellipse]    │
│          Selection: rectangle  —  Reset view                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│          ┌─────────────────────────────────────┐             │
│          │                                     │             │
│          │   canvas (zoom/pan, scatter,        │             │
│          │   optional σ ellipses per cell,     │             │
│          │   rectangle selection with          │             │
│          │   shift-drag)                       │             │
│          │                                     │             │
│          └─────────────────────────────────────┘             │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Status: 112 500 points · selection: 543 positions            │
└──────────────────────────────────────────────────────────────┘
```

The selection panel (BE.8) opens as a right-side drawer when the user
releases a non-empty rectangle.

## Axis convention

- X axis = `bary_p1_b` (opponent-of-P1 away), increasing left→right
  from 0 to 15.
- Y axis = `bary_p1_a` (P1 away), increasing top→bottom from 0 to 15
  (y-inverted to match RG plots).
- Grid lines at integer scores (gray, thin).
- Bound: draw area `[-0.5, 16] × [-0.5, 16]` (room for edge cases
  where `bary_*` reaches 0 or a hair over the score).

## Rendering

- **Canvas, not SVG**. Up to ~112 500 points; SVG is too slow for
  zoom. Use `<canvas>` with high-DPI support (devicePixelRatio).
- On mount, request `GET /api/bary/scatter?mode=global&per_cell=500`.
  Redraw the canvas when the data arrives.
- **Color** — RdBu diverging, centered at 0.5 on `mwc_p1`. Vmin=0,
  vmax=1.
- **Point size** — 2 px base. Alpha 0.15 to mimic the RG global
  scatter. Bump to 4 px + α 1.0 for the hovered point.
- **σ overlay** (toggle): for each cell with
  `low_support == false`, draw an ellipse centered at
  `(mean_bary_p1_b, mean_bary_p1_a)` with semi-axes `k·std_bary_p1_*`
  (k user-configurable, default 2) rotated by the principal
  eigenvector of the covariance matrix (from
  `cov_bary_p1_ab_mean`). Low-support cells (`low_support==true`)
  draw with a dashed border + "?" glyph to signal unreliable.

## Interactions

- **Pan**: left-drag with plain click.
- **Zoom**: wheel zoom centered on cursor; touchpad pinch supported
  via the same wheel handler.
- **Rectangle select**: Shift-drag. Live preview as a translucent
  rectangle. On mouse-up, convert viewport rect → data rect, call
  `POST /api/bary/select`, emit `{ rect, total, positions }` to the
  parent.
- **Hover tooltip**: nearest-neighbor via a fixed-resolution grid
  bucket index over the point array. Tooltip shows
  `"{score} | MWC {mwc_p1:.3f} | cube {cube_value} | disp
  |{magnitude:.2f}|"`.

## Props & state

```svelte
<script>
  let { onSelectionChange } = $props();
  let points     = $state([]);     // from /scatter
  let cells      = $state([]);     // from /cells (for σ overlay)
  let filters    = $state({ variant: 'all', cubeMin: 1, cubeMax: 64,
                            decisionTypes: [] });
  let colorBy    = $state('mwc_p1');
  let showSigma  = $state(false);
  let viewport   = $state({ x: -0.5, y: -0.5, w: 16.5, h: 16.5 });
  let hovered    = $state(null);
  let selection  = $state(null);   // { rect, total, positions }
</script>
```

## Data flow

1. Mount — concurrent fetch of `/scatter?mode=global` and
   `/cells?sampling=bootstrap`.
2. Filters change — client-side filter on the already-loaded points;
   overlays re-render from `cells`.
3. Rectangle select — `onSelectionChange({ rect, total, positions })`
   propagates to the parent `Barycentric.svelte` which writes to a
   shared store consumed by `SelectionPanel` (BE.8).

## Performance

- 112 500 canvas circles × α-blend at 60 fps needs GPU help. Option:
  use a single `ImageData` with precomputed point stamps, or the
  `regl` / `pixi.js` layer already used in TileMap. Default path:
  plain Canvas2D with batched arcs + `globalAlpha` — this handles
  ~200 k points at 30 fps which is adequate.
- Re-render is debounced (16 ms) during pan/zoom.
- Hover uses a lazily-built 256×256 grid index.

## Component skeleton

```svelte
<script>
  import { onMount } from 'svelte';
  import { fetchScatter, fetchCells, postSelect } from '../lib/bary-api.js';
  import { rdbu } from '../lib/color-scales.js';
  import { drawScatter, drawSigmaEllipses, xyToScreen, screenToXy }
    from '../lib/canvas-bary.js';

  let { onSelectionChange } = $props();
  // ... state as above ...

  onMount(async () => {
    const [scatter, cellAgg] = await Promise.all([
      fetchScatter({ mode: 'global', per_cell: 500 }),
      fetchCells({ sampling: 'bootstrap' }),
    ]);
    points = scatter.points;
    cells  = cellAgg.cells;
    requestDraw();
  });

  // Drag handlers …
  async function handleRectRelease(rect) {
    const resp = await postSelect({
      mode: 'global',
      rect,
      filters: { crawford_variant: filters.variant, … },
      limit: 500, offset: 0,
    });
    selection = { rect, total: resp.total, positions: resp.positions };
    onSelectionChange?.(selection);
  }
</script>

<div class="bary-global">
  <BaryToolbar bind:filters bind:colorBy bind:showSigma onReset={...} />
  <canvas bind:this={canvas} on:pointerdown={onDown}
                             on:pointermove={onMove}
                             on:pointerup={onUp}
                             on:wheel={onWheel}></canvas>
  <div class="status">{points.length.toLocaleString()} pts
    {#if selection}· selection: {selection.total}{/if}</div>
</div>
```

## Complexity

Medium. Most of the work is canvas plumbing; API bindings are
straightforward.

## Verification

- Manual:
  1. Load view. Expect the same striped structure as RG's
     `global_scatter.png`.
  2. Shift-drag over the `7a-7a` cloud; selection drawer opens with
     > 200 cards and most scores in `~(5..8)` range.
  3. Zoom to the sparse `13a-3a` region; selection returns fewer but
     coherent cards; display_label is `"13a-3a"` with color near red
     (MWC ~0.06).
  4. Toggle σ overlay → ellipses appear; small cells have visible
     dashed borders.
  5. Change color-by to `cube_gap_p1` → color scale shifts to that
     range with an updated legend.
- Automated (Playwright / Vitest):
  - Mock `/scatter` returning a fixed point set; assert
     `document.querySelector('canvas')` renders.
  - Simulate a shift-drag; assert `postSelect` is called with the
     expected rect (converted from screen to data coords).
