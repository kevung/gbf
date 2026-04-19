<script>
  /**
   * BE.6 — Score Clouds View
   *
   * 15×15 grid of CellThumb mini-canvases. 1-away cells show up to three
   * stacked sub-panels (Normal / Crawford / Post-Crawford). Clicking a cell
   * opens a CellDetail overlay. An LRU cache (64 entries) backs the lazy
   * per-cell scatter fetches.
   */
  import { onMount }      from 'svelte';
  import { fetchCells, fetchScatter } from '../lib/bary-api.js';
  import CellThumb  from '../components/CellThumb.svelte';
  import CellDetail from '../components/CellDetail.svelte';

  // ── Props ──────────────────────────────────────────────────────────────────

  let { onSelectionChange = null } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let cells       = $state([]);
  let loading     = $state(true);
  let error       = $state(null);
  let openCell    = $state(null);   // full cell object when detail is open
  let variantView = $state('split');
  let colorBy     = $state('mwc_p1');
  let showArrow   = $state(true);

  // ── LRU cache for cell scatter samples ─────────────────────────────────────

  const CACHE_SIZE = 64;
  const sampleCache = new Map(); // cell_id → Point[]

  async function getCellPoints(cellId) {
    if (sampleCache.has(cellId)) {
      const pts = sampleCache.get(cellId);
      sampleCache.delete(cellId);
      sampleCache.set(cellId, pts); // move to end (MRU)
      return pts;
    }
    const data = await fetchScatter({ mode: 'cell', cell_id: cellId, limit: 500 });
    const pts  = data.points ?? [];
    if (sampleCache.size >= CACHE_SIZE) {
      sampleCache.delete(sampleCache.keys().next().value);
    }
    sampleCache.set(cellId, pts);
    return pts;
  }

  // ── Cell lookup: grouped[a][b] = { normal, crawford, post_crawford } ────────

  let grouped = $derived(buildGrouped(cells));

  function buildGrouped(allCells) {
    const map = {};
    for (let a = 1; a <= 15; a++) {
      map[a] = {};
      for (let b = 1; b <= 15; b++) {
        map[a][b] = { normal: null, crawford: null, post_crawford: null };
      }
    }
    for (const c of allCells) {
      const a = c.score_away_p1, b = c.score_away_p2;
      if (a >= 1 && a <= 15 && b >= 1 && b <= 15) {
        map[a][b][c.crawford_variant] = c;
      }
    }
    return map;
  }

  // Row / column indices 1..15
  const SCORES = Array.from({ length: 15 }, (_, i) => i + 1);

  // ── Mount ──────────────────────────────────────────────────────────────────

  onMount(async () => {
    try {
      const data = await fetchCells({ sampling: 'bootstrap' });
      cells = data.cells ?? [];
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  });

  // ── Helpers ────────────────────────────────────────────────────────────────

  function isOneAway(a, b) { return a === 1 || b === 1; }

  /** Which variant cells to show for position (a, b) given variantView. */
  function thumbsForCell(a, b) {
    const g = grouped[a]?.[b];
    if (!g) return [];

    if (variantView === 'normal')       return g.normal       ? [g.normal]       : [];
    if (variantView === 'crawford')     return g.crawford     ? [g.crawford]     : [];
    if (variantView === 'post_crawford') return g.post_crawford ? [g.post_crawford] : [];

    // 'split': show all present variants; non-1-away cells only have normal
    if (!isOneAway(a, b)) return g.normal ? [g.normal] : [];
    return [g.normal, g.crawford, g.post_crawford].filter(Boolean);
  }
</script>

<div class="score-clouds">

  <!-- Toolbar -->
  <div class="toolbar">
    <label>
      Variant
      <select bind:value={variantView}>
        <option value="split">split CRA/PCR</option>
        <option value="normal">only normal</option>
        <option value="crawford">only crawford</option>
        <option value="post_crawford">only post-crawford</option>
      </select>
    </label>

    <label>
      Color
      <select bind:value={colorBy}>
        <option value="mwc_p1">MWC</option>
        <option value="cube_gap_p1">cube gap</option>
        <option value="cubeful_equity_p1">cubeful equity</option>
      </select>
    </label>

    <label>
      <input type="checkbox" bind:checked={showArrow} />
      σ arrow
    </label>

    {#if loading}
      <span class="status-msg">Loading cells…</span>
    {:else if error}
      <span class="status-msg error">Error: {error}</span>
    {:else}
      <span class="status-msg">{cells.length} cells loaded</span>
    {/if}
  </div>

  <!-- Axis header row -->
  <div class="axis-header">
    <div class="corner-cell"></div>
    {#each SCORES as b}
      <div class="col-header">{b}a</div>
    {/each}
  </div>

  <!-- Grid -->
  <div class="grid-scroll">
    {#each SCORES as a}
      <div class="grid-row">
        <div class="row-header">{a}a</div>
        {#each SCORES as b}
          <div class="grid-cell" class:one-away={isOneAway(a, b) && variantView === 'split'}>
            {#each thumbsForCell(a, b) as cell (cell.cell_id)}
              <CellThumb
                {cell}
                {colorBy}
                {showArrow}
                {getCellPoints}
                onClick={c => openCell = c}
              />
            {/each}
          </div>
        {/each}
      </div>
    {/each}
  </div>

  <!-- CellDetail overlay -->
  {#if openCell}
    <CellDetail
      cell={openCell}
      {getCellPoints}
      onClose={() => openCell = null}
      onSelectionChange={sel => {
        onSelectionChange?.(sel);
      }}
    />
  {/if}

</div>

<style>
  .score-clouds {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #1a1b26;
    color: #c0caf5;
    font-size: 12px;
  }

  /* ── Toolbar ── */
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
  }
  .toolbar label {
    display: flex; align-items: center; gap: 4px; white-space: nowrap;
  }
  .toolbar select {
    background: #1a1b26; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 2px 5px; font-size: 12px;
  }
  .toolbar input[type="checkbox"] { cursor: pointer; }
  .status-msg { color: #9aa5ce; }
  .status-msg.error { color: #f7768e; }

  /* ── Axis headers ── */
  .axis-header {
    display: flex;
    flex-shrink: 0;
    padding-left: 2px;
    background: #1e2030;
    border-bottom: 1px solid #2a2d3e;
  }
  .corner-cell { width: 26px; flex-shrink: 0; }
  .col-header  {
    flex: 1;
    min-width: 0;
    text-align: center;
    font-size: 9px;
    color: #565f89;
    padding: 2px 0;
  }

  /* ── Grid scroll area ── */
  .grid-scroll {
    flex: 1;
    overflow: auto;
  }

  .grid-row {
    display: flex;
    align-items: flex-start;
    gap: 2px;
    padding: 1px 2px;
    border-bottom: 1px solid #1e2030;
  }

  .row-header {
    width: 24px;
    flex-shrink: 0;
    font-size: 9px;
    color: #565f89;
    padding-top: 4px;
    text-align: right;
    padding-right: 3px;
  }

  .grid-cell {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
</style>
