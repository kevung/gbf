<script>
  /**
   * BE.8 — BoardCard
   * Compact card for one position from a selection result.
   * Shows mini board, analysis row, move row, and action buttons.
   */
  import Board from './Board.svelte';
  import { matchInFocus } from '../lib/selection-store.js';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    pos,              // PositionSummary object
    onDetail = null,  // (pos) => void — open detail drawer
  } = $props();

  // ── Colour helper (inline RdBu) ────────────────────────────────────────────

  const RDBU = [
    [103,0,31],[178,24,43],[214,96,77],[244,165,130],[253,219,199],
    [247,247,247],[209,229,240],[146,197,222],[67,147,195],[33,102,172],[5,48,97],
  ];
  function rdbu(t) {
    const s = Math.max(0, Math.min(1, t)) * (RDBU.length - 1);
    const lo = Math.floor(s), hi = Math.min(lo + 1, RDBU.length - 1);
    const f = s - lo;
    return `rgb(${Math.round(RDBU[lo][0]+f*(RDBU[hi][0]-RDBU[lo][0]))},${Math.round(RDBU[lo][1]+f*(RDBU[hi][1]-RDBU[lo][1]))},${Math.round(RDBU[lo][2]+f*(RDBU[hi][2]-RDBU[lo][2]))})`;
  }

  // ── Derived values ─────────────────────────────────────────────────────────

  let mwcColor = $derived(rdbu(pos.mwc_p1 ?? 0.5));
  let header   = $derived(
    `#${pos.move_number} · ${pos.display_label ?? `${pos.score_away_p1}a–${pos.score_away_p2}a`} · cube ${pos.cube_value ?? 1}`
  );
  let hasMoveInfo = $derived(pos.decision_type === 'checker' && pos.move_played != null);
  let moveDiffers = $derived(pos.best_move != null && pos.best_move !== pos.move_played);
  let hasErr      = $derived((pos.move_played_error ?? 0) > 0.001);
  let crawfordBadge = $derived(
    pos.crawford === true ? 'CRA'
    : pos.is_post_crawford === true ? 'PCR'
    : null
  );
</script>

<div class="board-card">
  <!-- Header -->
  <div class="card-header">
    <span class="card-title">{header}</span>
    {#if crawfordBadge}
      <span class="badge">{crawfordBadge}</span>
    {/if}
  </div>

  <!-- Body: mini board + analysis -->
  <div class="card-body">
    {#if pos.board}
      <div class="mini-board">
        <Board
          board={pos.board}
          barX={pos.bar_x ?? 0}
          barO={pos.bar_o ?? 0}
          borneOffX={pos.borne_off_x ?? 0}
          borneOffO={pos.borne_off_o ?? 0}
          cubeLog2={Math.round(Math.log2(pos.cube_value ?? 1))}
          cubeOwner={pos.cube_owner ?? 0}
          awayX={pos.score_away_p1 ?? 0}
          awayO={pos.score_away_p2 ?? 0}
          sideToMove={pos.player_on_roll ?? 0}
        />
      </div>
    {/if}

    <!-- Analysis -->
    <div class="card-analysis">
      <div class="analysis-row">
        <span class="mwc-val" style="color:{mwcColor}">
          MWC {(pos.mwc_p1 ?? 0.5).toFixed(3)}
        </span>
        {#if pos.cube_gap_p1 != null}
          <span class="gap-val">gap {pos.cube_gap_p1 >= 0 ? '+' : ''}{pos.cube_gap_p1.toFixed(3)}</span>
        {/if}
        {#if pos.disp_magnitude_p1 != null}
          <span class="disp-val">|D| {pos.disp_magnitude_p1.toFixed(2)}</span>
        {/if}
      </div>

      {#if hasMoveInfo}
        <div class="move-row">
          <span class="move-label">played</span>
          <span class="move-val">{pos.move_played}</span>
          {#if moveDiffers}
            <span class="move-label">best</span>
            <span class="move-val best">{pos.best_move}</span>
          {/if}
          {#if hasErr}
            <span class="err-val">err {(pos.move_played_error).toFixed(3)}</span>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <!-- Actions -->
  <div class="card-actions">
    <button class="btn" onclick={() => onDetail?.(pos)}>Detail</button>
    <button class="btn trace" onclick={() => matchInFocus.set(pos.position_id)}>
      Trace match
    </button>
  </div>
</div>

<style>
  .board-card {
    background: #1e2030;
    border: 1px solid #2a2d3e;
    border-radius: 4px;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 11px;
    color: #9aa5ce;
  }
  .board-card:hover { border-color: #3b4261; }

  .card-header {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    color: #c0caf5;
  }
  .badge {
    background: #3d59a1; color: #7aa2f7;
    border-radius: 2px; padding: 0 3px; font-size: 9px;
  }

  .card-body {
    display: flex;
    gap: 6px;
    align-items: flex-start;
  }
  .mini-board {
    flex-shrink: 0;
    width: 100px;
    overflow: hidden;
  }
  .mini-board :global(svg) {
    width: 100%;
    height: auto;
  }

  .card-analysis {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .analysis-row, .move-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    align-items: baseline;
  }

  .mwc-val   { font-weight: 600; }
  .gap-val   { color: #9aa5ce; }
  .disp-val  { color: #9aa5ce; }
  .move-label { color: #565f89; }
  .move-val   { color: #c0caf5; }
  .move-val.best { color: #9ece6a; }
  .err-val    { color: #f7768e; }

  .card-actions {
    display: flex;
    gap: 4px;
  }
  .btn {
    background: #2a2d3e; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 2px 8px; cursor: pointer; font-size: 10px;
  }
  .btn:hover  { background: #3b4261; }
  .btn.trace  { color: #7aa2f7; }
</style>
