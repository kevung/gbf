# BE.9 — Integration & End-to-End

## Objective

Wire BE.1–BE.8 into the existing explorer: add a "Barycentric" tab
with three sub-tabs (Global, Clouds, Trajectory), share the selection
and match-focus stores across them, proxy the Python service in dev,
and provide a single shell script that runs the full pipeline and
launches everything for local use.

## Pre-requisites

- BE.1..BE.8 merged.
- Existing frontend stack (`explorer/`) builds and runs.

## Files created / modified

Created:
- `scripts/run_barycentric_stack.sh` — orchestration script.
- `explorer/src/views/Barycentric.svelte` — coordinator view.

Modified:
- `explorer/src/App.svelte` — add "Barycentric" top-level tab.
- `explorer/vite.config.js` — proxy `/api/bary/*` → `localhost:8100`.
- `README.md` — add "Barycentric Explorer" section under the
  Explorer docs.
- `data/barycentric/analysis.md` — add a short "Interactive Explorer"
  note pointing at the new tab.

## `Barycentric.svelte` (coordinator)

Responsibilities:
- Hold the three sub-views in a sub-tab layout (Global / Clouds /
  Trajectory).
- Host `SelectionPanel` and `PositionDetail` drawer overlays.
- Import and wire the shared stores: `selectionStore` and
  `matchInFocus` (from `lib/selection-store.js`, BE.8).
- Handle URL state (optional but recommended):
  - `#/barycentric/global?variant=normal&color=mwc`
  - `#/barycentric/clouds?cell=a7_b7_normal`
  - `#/barycentric/trajectory?position=abc123…`

Sketch:

```svelte
<script>
  import { selectionStore, matchInFocus } from '../lib/selection-store.js';
  import BaryGlobalScatter    from './BaryGlobalScatter.svelte';
  import BaryScoreClouds      from './BaryScoreClouds.svelte';
  import BaryMatchTrajectory  from './BaryMatchTrajectory.svelte';
  import SelectionPanel       from '../components/SelectionPanel.svelte';

  let subTab = $state('global'); // 'global' | 'clouds' | 'trajectory'
</script>

<div class="bary-coordinator">
  <nav class="sub-tabs">
    <button class:active={subTab==='global'}
            on:click={() => subTab='global'}>Global scatter</button>
    <button class:active={subTab==='clouds'}
            on:click={() => subTab='clouds'}>Score clouds</button>
    <button class:active={subTab==='trajectory'}
            on:click={() => subTab='trajectory'}>Match trajectory</button>
  </nav>

  <div class="body">
    {#if subTab==='global'}
      <BaryGlobalScatter onSelectionChange={sel => selectionStore.set(sel)} />
    {:else if subTab==='clouds'}
      <BaryScoreClouds   onSelectionChange={sel => selectionStore.set(sel)} />
    {:else}
      <BaryMatchTrajectory />
    {/if}
  </div>

  <SelectionPanel />
</div>
```

## `App.svelte` diff

Add a top-level tab entry alongside the existing Projection / Themes /
Dashboard tabs:

```svelte
<nav>
  <button ... >Setup</button>
  <button ... >Explorer</button>
  <button ... >Projection</button>
  <button ... >Themes</button>
  <button ... >Barycentric</button>   <!-- NEW -->
  <button ... >Dashboard</button>
  <button ... >Help</button>
</nav>

{#if tab === 'barycentric'}
  <Barycentric />
{/if}
```

Activating the tab triggers `refreshTrigger`-style re-fetch in
descendants (same pattern as Projection).

## `vite.config.js` proxy

```js
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api/bary': {
        target: 'http://localhost:8100',
        changeOrigin: true,
      },
      '/api/viz':  'http://localhost:8080',  // existing
      // …other proxies
    },
  },
});
```

## `run_barycentric_stack.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Build derived parquet (idempotent: skips if up-to-date).
if [[ ! -f data/barycentric/barycentric_v2.parquet ]]; then
  python scripts/compute_barycentric_v2.py \
    --enriched data/parquet/positions_enriched \
    --games    data/parquet/games.parquet \
    --output   data/barycentric
fi

if [[ ! -f data/barycentric/cell_keys.parquet ]]; then
  python scripts/compute_cell_keys.py \
    --input  data/barycentric/barycentric_v2.parquet \
    --output data/barycentric/cell_keys.parquet \
    --audit  data/barycentric/crawford_audit.txt
fi

if [[ ! -f data/barycentric/bootstrap_cells.parquet ]]; then
  python scripts/bootstrap_cells.py \
    --input  data/barycentric/barycentric_v2.parquet \
    --output data/barycentric/bootstrap_cells.parquet \
    --report data/barycentric/bootstrap_report.txt \
    --k 50 --draw-size 500000
fi

# 2. Launch service in the background.
python scripts/barycentric_service.py \
  --bary   data/barycentric/barycentric_v2.parquet \
  --cells  data/barycentric/cell_keys.parquet \
  --boot   data/barycentric/bootstrap_cells.parquet \
  --enriched data/parquet/positions_enriched \
  --games  data/parquet/games.parquet \
  --matches data/parquet/matches.parquet \
  --port   8100 &
SERVICE_PID=$!

# 3. Frontend (foreground).
(cd explorer && npm install && npm run dev)
kill "$SERVICE_PID"
```

Add `make bary-stack` as a convenience target.

## End-to-end acceptance test

Run `./scripts/run_barycentric_stack.sh`. Open `http://localhost:5173`
and navigate through this script:

1. **Barycentric → Global Scatter**.
   Expect: canvas with striped scatter, color by MWC.
   Action: Shift-drag over `(bary_p1_b ∈ [5, 8], bary_p1_a ∈ [5, 8])`.
   Expect: selection panel opens with ≥ 200 cards, each with
   `score_away_*` mostly in the 7..9 range.

2. **Toggle σ overlay** (toolbar).
   Expect: ellipses appear at each cell; low-support cells (1-away
   CRA variants) show dashed borders + `?` glyph.

3. **Switch to Score Clouds**.
   Action: click the 1a-1a cell.
   Expect: CellDetail opens showing Normal + PCR sub-panels (no
   CRA at 1a-1a). Sub-panel densities match `n_total` in
   `/api/bary/cells`.

4. **Select in a cell**.
   Action: inside a full-size 9a-9a cell view, Shift-drag a tight
   rectangle.
   Expect: selection panel cards all have `score_away_p1 == 9 AND
   score_away_p2 == 9`.

5. **Click "Trace match" on a card**.
   Expect: top-level sub-tab auto-switches to Trajectory. Polyline +
   MWC chart render; last position matches the outcome of that
   match from `matches.parquet` (winner's MWC → 1.0).

6. **POV toggle**.
   Action: in Trajectory, POV dropdown → P2.
   Expect: MWC curve mirrors around y=0.5; axes of the polyline
   swap.

7. **Crawford / Post-Crawford**.
   Expect: in the trajectory of a long match, at least one game is
   visually highlighted (dashed stroke / shaded band) as Crawford
   or Post-Crawford.

8. **Detail drawer**.
   Action: click `Detail` on a card.
   Expect: full board renders; context block shows
   `crawford_variant`, `bary_p1_*`, `mwc_p1`, `cube_gap_p1`.

9. **CSV export**.
   Action: click CSV button on a 50-card selection.
   Expect: file download; header row matches BE.8 spec;
   `mwc_p1` values are in [0, 1].

## Documentation updates

`README.md` new section (linked from `README.md`):

```markdown
### Barycentric Explorer

After running the full pipeline, launch the interactive tool:

    ./scripts/run_barycentric_stack.sh

Then open <http://localhost:5173> and navigate to **Barycentric**.
Three views are available:

- **Global scatter** — every position's barycenter in score space;
  draw a rectangle to select positions and inspect them as board
  cards.
- **Score clouds** — per-cell barycenter scatter, with CRA and PCR
  variants shown separately at 1-away scores.
- **Match trajectory** — click any point to trace the entire match
  it belongs to, with MWC evolution plotted in a companion chart.
```

`data/barycentric/analysis.md` appendix:

```markdown
## 8. Interactive Explorer

The static plots in this document are now also available as an
interactive tool; see the "Barycentric" tab in the explorer
(`./scripts/run_barycentric_stack.sh`). The interactive version uses
a perspective-corrected version of the dataset
(`barycentric_v2.parquet`) and bootstrap-averaged cell statistics,
so numbers there may differ slightly from the figures above.
```

## Complexity

Low-Medium. Mostly glue code; the coordinator is small and the run
script is mechanical. The main risk is race conditions between
frontend and service readiness — the shell script does not wait for
`:8100` to answer; if that becomes an issue, add a `curl --retry`
pre-check before launching the Vite dev server.

## Verification

Covered by the end-to-end script above. In addition:

- `make bary-stack` completes without errors on a clean machine that
  already has the source parquet files.
- `npm run build` in `explorer/` still succeeds after the changes.
- Existing Projection / Themes tabs continue to work (no regressions).
