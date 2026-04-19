# BE.7 — Match Trajectory Overlay View (Frontend)

## Objective

Third main view of the Barycentric Explorer. Given a seed position
(chosen by clicking a point in BE.5/BE.6 or from a board card in
BE.8), fetch the entire match it belongs to and render:

1. **Trajectory polyline** in score space — a line through every
   position's `(bary_p1_b, bary_p1_a)` in match order.
2. **MWC chart** — companion line plot of `mwc_p1` vs move index,
   showing how match equity evolved; vertical markers for game
   boundaries; shaded spans for Crawford / Post-Crawford games.
3. **Perspective toggle** — switch between P1 POV (default) and P2
   POV; curves mirror around `y=0.5` on the MWC chart.

## Pre-requisites

- BE.4 endpoint: `GET /api/bary/match/{position_id}` returning
  positions already in P1 POV and sorted by `(game_number,
  move_number)`.
- BE.5 canvas helpers (`lib/canvas-bary.js`, `lib/color-scales.js`).
- Optional: the existing `explorer/src/components/Chart.svelte` for
  the MWC line chart (reuse if it handles categorical X).

## Files created

- `explorer/src/views/BaryMatchTrajectory.svelte` — coordinator.
- `explorer/src/components/TrajectoryCanvas.svelte` — score-space
  polyline canvas.
- `explorer/src/components/MwcChart.svelte` — MWC vs move index.

## UI layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Header: Michel Lamote (P1) vs Gaz Owen (P2) — to 11 — 5 games           │
│ POV: [P1 ▾]     Show: [◉ Trajectory  ◉ MWC chart]                       │
├────────────────────────────────────┬─────────────────────────────────────┤
│                                    │                                     │
│   trajectory canvas (score space)  │  MWC chart (vs move index)          │
│   polyline + colored nodes +       │  line, game boundaries as dashed    │
│   hovered highlight                │  verticals, CRA/PCR shaded spans    │
│                                    │                                     │
├────────────────────────────────────┴─────────────────────────────────────┤
│ Move detail: #17 · 5a-6a · cube 2 · mwc 0.62 · err 0.012                 │
│ Games timeline (mini strip):  [G1 ▮▮▮▮]  [G2 ▮▮]  [G3 ▮▮▮▮▮]            │
└──────────────────────────────────────────────────────────────────────────┘
```

## Data flow

- Coordinator `Barycentric.svelte` holds a `matchInFocus` store: when
  another view (BE.5/BE.6/BE.8) emits a "trace match" event with a
  `position_id`, the store updates.
- `BaryMatchTrajectory.svelte` reacts via `$derived`: on change, it
  calls `fetchMatch(position_id)` and feeds the two children.

## `TrajectoryCanvas.svelte`

Props: `{ match, pov, hoveredMoveIndex, onHover }`.

- Full score-space canvas with the same axis conventions as BE.5.
- Light background scatter (optional): faded global scatter from
  `/api/bary/scatter?mode=global` cached in a shared store to give
  visual context ("where does this match's trajectory sit among all
  positions?"). Toggle `backgroundScatter: on/off` in toolbar.
- Polyline:
  - Drawn in sequence through positions[i].bary_p1_{b,a}.
  - Nodes colored by MWC (RdBu diverging).
  - Seed position: ring + thicker stroke.
  - Crawford game segments: **dashed** stroke.
  - Cube actions (rows where `decision_type` is a cube event and
    `cube_action_played` is not null): small square marker on the
    node.
- Hovered move: highlighted node, and `onHover(i)` fires so the MWC
  chart highlights the same.

### POV swap

When `pov === 'p2'`, remap on the client:
- `x' = bary_p1_a` (so P2 away is on the x-axis)
- `y' = bary_p1_b`
- `mwc = 1 - mwc_p1`
We don't re-query the server; the P1-POV payload contains enough.

## `MwcChart.svelte`

Props: `{ match, pov, hoveredMoveIndex, onHover }`.

- X axis: move index 0..N (global across the match, consecutive).
  Major ticks at game boundaries.
- Y axis: `mwc_p1` (or `1 - mwc_p1` for P2 POV); range [0, 1].
- Plot a single line, points colored same RdBu scale.
- Dashed vertical: game boundaries (between `positions[i-1]` and
  `positions[i]` where `game_number` changes).
- Shaded bands:
  - Crawford game: light-yellow background.
  - Post-Crawford games: light-orange background.
- Hover: crosshair, tooltip matches `MoveDetail` payload below.

Uses `Chart.svelte` if already present; otherwise a small d3-based
implementation. Keep the interface pov-agnostic.

## `MoveDetail` footer

Shared bottom strip rendered by `BaryMatchTrajectory.svelte`:

```
#{move_number} · game {game_number} · on-roll P{player_on_roll} ·
score {score_away_p1}a-{score_away_p2}a {variant-badge} ·
cube {cube_value} · mwc {mwc:.3f} · gap {cube_gap:.3f} ·
dec {decision_type}{' · err ' + err if err > 0}
```

Click "Open board" → uses BE.8's PositionDetail drawer for full
board.

## Interactions

- Hover on trajectory node → highlights on both canvas and chart.
- Click node → load board via `/api/bary/position/{position_id}`.
- `POV` dropdown → instantly re-derives coordinates on the client.
- `Show` checkboxes → hide/show each sub-view.
- Keyboard: arrow-left/right steps through moves (updates
  `hoveredMoveIndex`).

## Games timeline mini-strip

Compact visual of all games in the match: one block per game, width
proportional to `move_count`, colored by that game's final
`points_won × winner sign`. Hover → filter the trajectory to only
that game (the rest is drawn at α=0.2).

## Performance & edge cases

- Typical match: 200–600 positions; canvas draws in < 10 ms.
- Very long matches (e.g. consultation, 21-point): still manageable.
  If node count > 1 000, downsample the polyline for the background
  pass but keep full resolution for hover detection.
- Position not in `barycentric_v2.parquet` (e.g. away > 15): the
  backend filters them out. Display a warning "N positions outside
  MET range omitted".

## POV toggle implementation detail

The server returns P1-POV exclusively. POV swap is a pure client
transform. This avoids re-fetching and keeps caching simple:

```js
function povTransform(p, pov) {
  if (pov === 'p1') return { x: p.bary_p1_b, y: p.bary_p1_a, mwc: p.mwc_p1 };
  return          { x: p.bary_p1_a, y: p.bary_p1_b, mwc: 1 - p.mwc_p1 };
}
```

## Verification

- Manual:
  1. Pick a known short match from fixtures; trace it. Confirm:
     - `positions.length` matches the number of moves in the SGF.
     - The last position's `score_away_*` reaches `(0, b)` or
       `(a, 0)`, matching the match outcome (or, if the match ended
       before the MET boundary, the last in-range position).
     - The MWC chart ends near 1 for the winner's POV.
  2. Toggle POV to P2 → chart mirrors.
  3. Hovering on the chart highlights the matching node on the
     canvas (and vice versa).
  4. Crawford game span is visually distinct.
- Automated:
  - Unit test `povTransform` on representative data.
  - Mocked `fetchMatch` → render, assert polyline node count matches
    positions length.

## Complexity

Medium-High. The interactive compositing (shared hover, POV swap,
Crawford shading, cube markers) is where most of the code lives,
but each piece is small.

## Usage note

When the view is opened from BE.8's "Open trajectory" button, the
coordinator passes the seed `position_id` via the shared
`matchInFocus` store. The view must handle the degenerate case where
the store is empty (no position selected yet): render a placeholder
"Select a position from Global Scatter or Score Clouds to trace its
match".
