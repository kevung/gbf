# BE.8 — Selection Panel (Board Cards + Detail Drawer)

## Objective

Shared UI component stack that lists positions returned by a region
selection (BE.5 / BE.6) as annotated "board cards" and lets the user
drill into a single position, export the list, or jump into the
trajectory view.

## Pre-requisites

- BE.4 `/api/bary/select` and `/api/bary/position/{id}` endpoints.
- Existing components:
  - `explorer/src/components/Board.svelte` — mini board renderer.
  - `explorer/src/components/PositionDetail.svelte` — full detail
    view (reuse wholesale for the drill-in drawer).
  - `explorer/src/components/AnalysisTable.svelte` — compact analysis
    card (reuse layout inspiration).

## Files created

- `explorer/src/components/SelectionPanel.svelte` — the side panel.
- `explorer/src/components/BoardCard.svelte` — one card.
- `explorer/src/lib/selection-store.js` — tiny svelte store holding
  the current selection (shared across BE.5/6/7).

## Panel structure

```
┌─────────────────────────────────────────────┐
│ Selection — 543 positions (showing 200)     │
│ Sort: [error ▾]  Filter: [search…]   CSV ⬇ │
├─────────────────────────────────────────────┤
│ ┌─────────────────────────┐                 │
│ │ #17 · 5a-6a · cube 2    │ ← BoardCard     │
│ │ [ mini board image ]    │                 │
│ │ MWC 0.62 · gap +0.04    │                 │
│ │ played 13/9  best 13/9  │                 │
│ │ err 0.012               │                 │
│ │ [Detail] [Trace match]  │                 │
│ └─────────────────────────┘                 │
│ ┌─────────────────────────┐                 │
│ │ ...                     │                 │
│ └─────────────────────────┘                 │
│                                             │
│   (virtualized list; loads more on scroll)  │
└─────────────────────────────────────────────┘
```

## `BoardCard.svelte`

Props: `{ pos, onDetail, onTrace }`.

Fields rendered from the `PositionSummary` payload:
- Header: `#{move_number} · {display_label} · cube {cube_value}`.
- Mini Board: pass `board_p1`, `board_p2`, `dice`, `cube_owner`,
  `player_on_roll` to `Board.svelte` in thumbnail mode.
- Analysis row:
  - `MWC {mwc_p1:.3f}` colored by RdBu.
  - `gap {cube_gap_p1:+.3f}`.
  - `disp |D| {|disp|:.2f}` from `disp_magnitude_p1`.
- Move row (only when `decision_type == 'checker'`):
  - `played <move_played>`.
  - `best <best_move>` if differs.
  - `err <move_played_error:.3f>`.
- Footer actions:
  - `Detail` — opens a drawer with `PositionDetail.svelte`.
  - `Trace match` — emits `matchInFocus = pos.position_id` so
    `BaryMatchTrajectory.svelte` reacts.

Card is ~140 px tall; board thumbnail ~100 px wide.

## `SelectionPanel.svelte`

Props: `{ selection, onClose }`.

- Reads `selection` from `selection-store.js`:
  `{ rect, total, positions, filters, mode, cell_id }`.
- Top bar:
  - Title `Selection — {total} positions`.
  - Subtitle: description of the rect (e.g. `x ∈ [4, 7], y ∈ [3, 6]`
    and current filters).
  - Sort dropdown: `error ▾ | mwc | |disp| | move_number`.
  - Quick-filter text box: matches any substring in
    `{position_id, match_id, move_played, best_move}`.
  - CSV export button (see below).
  - Close `×`.
- Body: virtualized list (`svelte-virtual-list` or a simple
  slice-and-render pattern) showing BoardCards.
- On scroll past the last loaded card, fetch the next page via
  `POST /api/bary/select` with incremented `offset`. Load until all
  `total` positions are available or the user stops.

### CSV export

Columns: `position_id, match_id, game_id, move_number, score_away_p1,
score_away_p2, crawford_variant, cube_value, decision_type,
move_played, best_move, move_played_error, mwc_p1, cube_gap_p1,
bary_p1_a, bary_p1_b`. Uses the client's in-memory positions; if not
all `total` have been loaded, a dialog asks the user to confirm
fetching the rest (up to a 50 k cap).

## Detail drawer

When a card's "Detail" is clicked:

- `fetchPosition(position_id)` → the rich payload (see BE.4 §5).
- Rendered by `PositionDetail.svelte` inside a right-hand drawer that
  overlays the selection panel.
- Drawer shows:
  - Full-size board.
  - Analysis table (pip counts, eval breakdown, played/best move).
  - Context block: barycentric coordinates, MWC, cube gap,
    `crawford_variant` badge.
  - Link to `Trace match`.

## `selection-store.js`

```js
import { writable } from 'svelte/store';

export const selectionStore = writable({
  mode: null,        // 'global' | 'cell'
  cell_id: null,
  rect: null,
  filters: null,
  total: 0,
  positions: [],
  loading: false,
});

export const matchInFocus = writable(null);   // position_id

export function clearSelection() {
  selectionStore.set({ mode: null, cell_id: null, rect: null,
                       filters: null, total: 0, positions: [],
                       loading: false });
}
```

## Interactions between views

- BE.5/BE.6 call `setSelection({...})` → `selectionStore` updates →
  `SelectionPanel` opens automatically.
- BE.8 card click → `matchInFocus.set(position_id)` → BE.7 reacts.
- BE.9 coordinator (`Barycentric.svelte`) hosts the panel + drawer
  so they overlay every sub-view consistently.

## Empty states

- No selection yet: panel is hidden.
- Selection returns 0 positions: panel shows "No positions in this
  region. Try widening the rectangle or relaxing filters."
- API error: panel shows the error text and a `Retry` button.

## Performance

- List virtualization required — 500 cards is routine, 10 000 is
  possible with the CSV export path.
- Avoid re-fetching on sort: sort client-side over the loaded pages,
  reset to server-side sort only if the user sorts a field we can
  push down (all of them can; keep simple: re-request on sort
  change).
- Mini-board rendering uses a cached sprite of checkers; each board
  is ~100 DOM nodes, 50 cards = 5 000 nodes — acceptable with
  virtualization.

## Verification

- Manual:
  1. Draw a rectangle on BE.5; panel opens with the right number of
     cards; first card's `score_away_*` are inside the rectangle.
  2. Sort by `error` descending — top card has the largest
     `move_played_error`.
  3. Quick-filter "13/9" — only cards whose `move_played` or
     `best_move` contain that substring remain.
  4. Click `Trace match` on a card → BE.7 loads that match.
  5. Click `Detail` → drawer opens with the full board.
  6. CSV export of 50 cards downloads a well-formed file with the
     expected column header.
- Automated:
  - Mount `SelectionPanel` with a fixture selection → assert card
    count and sort.
  - Click-simulate `Trace match` → assert `matchInFocus` updates.

## Complexity

Low-Medium. Reuses `Board.svelte` and `PositionDetail.svelte` heavily;
new code is mostly layout, virtualization, and CSV export.
