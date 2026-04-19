<script>
  /**
   * BE.8 — SelectionPanel
   * Side panel listing positions from a rect selection (BE.5/BE.6).
   * Virtualized list, sort, quick-filter, pagination, CSV export,
   * and a right-hand drawer for full PositionDetail.
   */
  import { postSelect, fetchPosition } from '../lib/bary-api.js';
  import BoardCard      from './BoardCard.svelte';
  import PositionDetail from './PositionDetail.svelte';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    selection = null,   // { mode, cell_id, rect, total, positions }
    onClose   = null,
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let sortField    = $state('move_played_error');
  let sortOrder    = $state('desc');
  let filterText   = $state('');
  let drawerPos    = $state(null);    // full position detail object
  let drawerLoading = $state(false);
  let loadingMore  = $state(false);

  // Local copy of positions so we can append pages
  let localPositions = $state([]);
  let localTotal     = $state(0);

  // Sync incoming selection → local state
  $effect(() => {
    if (selection) {
      localPositions = [...(selection.positions ?? [])];
      localTotal     = selection.total ?? 0;
    }
  });

  // ── Derived: filtered + sorted list ───────────────────────────────────────

  let displayed = $derived(() => {
    let pts = localPositions;
    const q = filterText.trim().toLowerCase();
    if (q) {
      pts = pts.filter(p =>
        (p.position_id  ?? '').toLowerCase().includes(q) ||
        (p.match_id     ?? '').toLowerCase().includes(q) ||
        (p.move_played  ?? '').toLowerCase().includes(q) ||
        (p.best_move    ?? '').toLowerCase().includes(q)
      );
    }
    const sign = sortOrder === 'desc' ? -1 : 1;
    return [...pts].sort((a, b) => {
      const av = a[sortField] ?? 0, bv = b[sortField] ?? 0;
      return sign * (av < bv ? -1 : av > bv ? 1 : 0);
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  async function loadMore() {
    if (!selection || loadingMore) return;
    if (localPositions.length >= localTotal) return;
    loadingMore = true;
    try {
      const body = {
        mode:    selection.mode    ?? 'global',
        cell_id: selection.cell_id ?? undefined,
        rect:    selection.rect,
        sort:    { field: sortField, order: sortOrder },
        limit:   200,
        offset:  localPositions.length,
      };
      const resp = await postSelect(body);
      localPositions = [...localPositions, ...(resp.positions ?? [])];
      localTotal = resp.total ?? localTotal;
    } finally {
      loadingMore = false;
    }
  }

  function onListScroll(e) {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
      loadMore();
    }
  }

  // ── Re-request when sort changes ──────────────────────────────────────────

  $effect(() => {
    const _sf = sortField;
    const _so = sortOrder;
    if (!selection?.rect) return;
    // Re-fetch first page with new sort
    localPositions = [];
    loadingMore = true;
    postSelect({
      mode:    selection.mode    ?? 'global',
      cell_id: selection.cell_id ?? undefined,
      rect:    selection.rect,
      sort:    { field: _sf, order: _so },
      limit:   200,
      offset:  0,
    }).then(resp => {
      localPositions = resp.positions ?? [];
      localTotal = resp.total ?? 0;
    }).catch(() => {}).finally(() => { loadingMore = false; });
  });

  // ── Detail drawer ─────────────────────────────────────────────────────────

  async function openDetail(pos) {
    drawerLoading = true;
    drawerPos = null;
    try {
      drawerPos = await fetchPosition(pos.position_id);
    } finally {
      drawerLoading = false;
    }
  }

  // ── CSV export ─────────────────────────────────────────────────────────────

  const CSV_COLS = [
    'position_id','match_id','game_id','move_number',
    'score_away_p1','score_away_p2','crawford_variant','cube_value',
    'decision_type','move_played','best_move','move_played_error',
    'mwc_p1','cube_gap_p1','bary_p1_a','bary_p1_b',
  ];

  async function exportCsv() {
    let pts = localPositions;
    if (pts.length < localTotal) {
      const ok = confirm(
        `Only ${pts.length} of ${localTotal} positions loaded.\n` +
        `Fetch all (up to 50 000)? This may take a moment.`
      );
      if (ok) {
        const resp = await postSelect({
          mode:    selection.mode    ?? 'global',
          cell_id: selection.cell_id ?? undefined,
          rect:    selection.rect,
          sort:    { field: sortField, order: sortOrder },
          limit:   50000,
          offset:  0,
        });
        pts = resp.positions ?? [];
      }
    }
    const header = CSV_COLS.join(',');
    const rows = pts.map(p =>
      CSV_COLS.map(c => {
        const v = p[c];
        if (v == null) return '';
        const s = String(v);
        return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
      }).join(',')
    );
    const csv = [header, ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'selection.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── Rect description ──────────────────────────────────────────────────────

  let rectDesc = $derived(() => {
    const r = selection?.rect;
    if (!r) return '';
    return `x ∈ [${r.x0?.toFixed(1)}, ${r.x1?.toFixed(1)}], y ∈ [${r.y0?.toFixed(1)}, ${r.y1?.toFixed(1)}]`;
  });
</script>

<div class="selection-panel">

  <!-- Header bar -->
  <div class="panel-header">
    <div class="header-top">
      <span class="panel-title">
        Selection — {localTotal.toLocaleString()} position{localTotal !== 1 ? 's' : ''}
      </span>
      <div class="spacer"></div>
      <button class="icon-btn" title="Export CSV" onclick={exportCsv}>CSV ⬇</button>
      <button class="icon-btn close" onclick={() => onClose?.()}>✕</button>
    </div>
    {#if rectDesc()}
      <div class="rect-desc">{rectDesc()}</div>
    {/if}
    <div class="controls-row">
      <label class="ctrl">
        Sort
        <select bind:value={sortField}>
          <option value="move_played_error">error</option>
          <option value="mwc_p1">MWC</option>
          <option value="disp_magnitude_p1">|disp|</option>
          <option value="move_number">move #</option>
        </select>
        <select bind:value={sortOrder}>
          <option value="desc">▾</option>
          <option value="asc">▴</option>
        </select>
      </label>
      <input
        class="filter-input"
        type="text"
        placeholder="Filter…"
        bind:value={filterText}
      />
    </div>
  </div>

  <!-- Card list -->
  {#if displayed().length === 0 && !loadingMore}
    <div class="empty-msg">
      {localTotal === 0
        ? 'No positions in this region. Try widening the rectangle.'
        : 'No matches for the current filter.'}
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="card-list" role="list" onscroll={onListScroll}>
      {#each displayed() as pos (pos.position_id)}
        <div role="listitem">
          <BoardCard {pos} onDetail={openDetail} />
        </div>
      {/each}
      {#if loadingMore}
        <div class="loading-row">Loading…</div>
      {:else if localPositions.length < localTotal}
        <div class="load-more-hint">
          {localPositions.length.toLocaleString()} / {localTotal.toLocaleString()} loaded
          — scroll to load more
        </div>
      {/if}
    </div>
  {/if}

  <!-- Detail drawer overlay -->
  {#if drawerPos || drawerLoading}
    <div class="drawer">
      <div class="drawer-header">
        <span class="drawer-title">Position Detail</span>
        <div class="spacer"></div>
        <button class="icon-btn close" onclick={() => { drawerPos = null; drawerLoading = false; }}>✕</button>
      </div>
      <div class="drawer-body">
        {#if drawerLoading}
          <div class="loading-row">Loading…</div>
        {:else}
          <PositionDetail position={drawerPos} />
        {/if}
      </div>
    </div>
  {/if}

</div>

<style>
  .selection-panel {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #1a1b26;
    color: #c0caf5;
    font-size: 12px;
    border-left: 1px solid #3b4261;
  }

  /* ── Header ── */
  .panel-header {
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    padding: 6px 10px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .header-top {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .panel-title { font-weight: 600; color: #c0caf5; font-size: 13px; }
  .spacer      { flex: 1; }
  .rect-desc   { font-size: 10px; color: #565f89; }

  .controls-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .ctrl {
    display: flex; align-items: center; gap: 3px;
    font-size: 11px; color: #9aa5ce;
  }
  .ctrl select {
    background: #1a1b26; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 1px 4px; font-size: 11px;
  }
  .filter-input {
    flex: 1; min-width: 80px;
    background: #1a1b26; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 2px 6px; font-size: 11px;
  }
  .filter-input::placeholder { color: #565f89; }

  .icon-btn {
    background: #2a2d3e; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 2px 7px; cursor: pointer; font-size: 11px;
    white-space: nowrap;
  }
  .icon-btn:hover { background: #3b4261; }
  .icon-btn.close { font-size: 13px; padding: 1px 8px; }

  /* ── Card list ── */
  .card-list {
    flex: 1;
    overflow-y: auto;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .empty-msg {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #565f89;
    font-size: 12px;
    padding: 24px;
    text-align: center;
  }
  .loading-row {
    text-align: center;
    color: #565f89;
    padding: 8px;
    font-size: 11px;
  }
  .load-more-hint {
    text-align: center;
    color: #3b4261;
    font-size: 10px;
    padding: 4px;
  }

  /* ── Detail drawer ── */
  .drawer {
    position: absolute;
    inset: 0;
    background: #1a1b26;
    border-left: 1px solid #3b4261;
    display: flex;
    flex-direction: column;
    z-index: 10;
  }
  .drawer-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
  }
  .drawer-title { font-weight: 600; color: #c0caf5; font-size: 13px; }
  .drawer-body  { flex: 1; overflow-y: auto; padding: 8px; }
</style>
