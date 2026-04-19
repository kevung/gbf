<script>
  /**
   * BE.7 — Match Trajectory View
   * Coordinator: fetches match data for a given seed position_id,
   * splits layout between TrajectoryCanvas (score space) and MwcChart
   * (MWC vs move index), with shared hover state and POV toggle.
   */
  import { fetchMatch }          from '../lib/bary-api.js';
  import TrajectoryCanvas        from '../components/TrajectoryCanvas.svelte';
  import MwcChart                from '../components/MwcChart.svelte';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    positionId          = null,    // seed position to trace; null → placeholder
    backgroundPoints    = [],
    onClickPosition     = null,    // (position_id) => void
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let match            = $state(null);
  let loading          = $state(false);
  let error            = $state(null);
  let pov              = $state('p1');
  let hoveredMoveIndex = $state(null);
  let showTrajectory   = $state(true);
  let showMwcChart     = $state(true);
  let focusGameNumber  = $state(null);   // null → all games

  // ── Fetch on positionId change ─────────────────────────────────────────────

  $effect(() => {
    const id = positionId;
    if (!id) { match = null; return; }
    loading = true;
    error   = null;
    fetchMatch(id)
      .then(data => { match = data; loading = false; })
      .catch(e  => { error  = e.message; loading = false; });
  });

  // ── Derived helpers ────────────────────────────────────────────────────────

  let positions = $derived(match?.positions ?? []);
  let hoveredPos = $derived(
    hoveredMoveIndex != null ? positions[hoveredMoveIndex] : null
  );

  // Games timeline: one entry per unique game_number
  let games = $derived(() => {
    const map = new Map();
    for (const p of positions) {
      if (!map.has(p.game_number)) {
        map.set(p.game_number, { game_number: p.game_number, count: 0,
          points_won: p.points_won ?? 0, crawford: p.crawford === true,
          post_crawford: p.is_post_crawford === true });
      }
      map.get(p.game_number).count++;
    }
    return [...map.values()];
  });

  // ── Header info ───────────────────────────────────────────────────────────

  let headerText = $derived(() => {
    if (!match) return '';
    const m = match;
    const p1 = m.player1_name ?? 'P1';
    const p2 = m.player2_name ?? 'P2';
    const length = m.match_length ?? '?';
    const gc = games().length;
    return `${p1} vs ${p2} — to ${length} — ${gc} game${gc !== 1 ? 's' : ''}`;
  });

  // ── Keyboard navigation ────────────────────────────────────────────────────

  function onKeydown(e) {
    if (!positions.length) return;
    if (e.key === 'ArrowRight') {
      hoveredMoveIndex = Math.min((hoveredMoveIndex ?? -1) + 1, positions.length - 1);
      e.preventDefault();
    } else if (e.key === 'ArrowLeft') {
      hoveredMoveIndex = Math.max((hoveredMoveIndex ?? 1) - 1, 0);
      e.preventDefault();
    }
  }

  // ── Variant badge helper ───────────────────────────────────────────────────

  function variantBadge(p) {
    if (p.crawford === true) return 'CRA';
    if (p.is_post_crawford === true) return 'PCR';
    return null;
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="trajectory-view"
  tabindex="0"
  onkeydown={onKeydown}
>

  <!-- Header -->
  <div class="header">
    {#if match}
      <span class="match-title">{headerText()}</span>
    {:else if loading}
      <span class="status-msg">Loading match…</span>
    {:else if error}
      <span class="status-msg error">Error: {error}</span>
    {:else}
      <span class="status-msg">Select a position from Global Scatter or Score Clouds to trace its match</span>
    {/if}

    <div class="spacer"></div>

    <label class="ctrl">
      POV
      <select bind:value={pov}>
        <option value="p1">P1</option>
        <option value="p2">P2</option>
      </select>
    </label>

    <label class="ctrl">
      <input type="checkbox" bind:checked={showTrajectory} /> Trajectory
    </label>
    <label class="ctrl">
      <input type="checkbox" bind:checked={showMwcChart} /> MWC chart
    </label>
  </div>

  <!-- Main split panel -->
  <div class="main-area">
    {#if showTrajectory}
      <div class="panel trajectory-panel">
        <TrajectoryCanvas
          {match}
          {pov}
          {hoveredMoveIndex}
          {backgroundPoints}
          {focusGameNumber}
          onHover={i => hoveredMoveIndex = i}
          onClickPosition={id => onClickPosition?.(id)}
        />
      </div>
    {/if}

    {#if showMwcChart}
      <div class="panel chart-panel">
        <MwcChart
          {match}
          {pov}
          {hoveredMoveIndex}
          onHover={i => hoveredMoveIndex = i}
        />
      </div>
    {/if}

    {#if !showTrajectory && !showMwcChart}
      <div class="panel empty-panel">
        <span>Enable Trajectory or MWC chart above.</span>
      </div>
    {/if}
  </div>

  <!-- Move detail footer -->
  <div class="move-detail">
    {#if hoveredPos}
      {@const mwc = pov === 'p1' ? (hoveredPos.mwc_p1 ?? 0.5) : 1 - (hoveredPos.mwc_p1 ?? 0.5)}
      {@const err = hoveredPos.move_played_error ?? 0}
      {@const badge = variantBadge(hoveredPos)}
      <span>
        #{hoveredPos.move_number} · game {hoveredPos.game_number}
        · on-roll P{hoveredPos.player_on_roll ?? '?'}
        · {hoveredPos.score_away_p1}a–{hoveredPos.score_away_p2}a
        {#if badge}<span class="badge">{badge}</span>{/if}
        · cube {hoveredPos.cube_value ?? 1}
        · mwc {mwc.toFixed(3)}
        {#if hoveredPos.cube_gap_p1 != null}· gap {hoveredPos.cube_gap_p1.toFixed(3)}{/if}
        {#if hoveredPos.decision_type}· dec {hoveredPos.decision_type}{/if}
        {#if err > 0.001}· err {err.toFixed(3)}{/if}
      </span>
    {:else if positions.length}
      <span class="hint">Hover a node to inspect · arrow keys to step</span>
    {/if}
  </div>

  <!-- Games timeline strip -->
  {#if games().length > 0}
    <div class="games-strip">
      {#each games() as g (g.game_number)}
        {@const active = focusGameNumber == null || focusGameNumber === g.game_number}
        <button
          class="game-block"
          class:dimmed={!active}
          class:crawford={g.crawford}
          class:post-crawford={g.post_crawford}
          style="flex: {g.count}"
          title="Game {g.game_number} ({g.count} moves)"
          onclick={() => focusGameNumber = focusGameNumber === g.game_number ? null : g.game_number}
        >
          G{g.game_number}
        </button>
      {/each}
    </div>
  {/if}

</div>

<style>
  .trajectory-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #1a1b26;
    color: #c0caf5;
    font-size: 12px;
    outline: none;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 6px 12px;
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
  }
  .match-title { font-size: 13px; font-weight: 600; color: #c0caf5; }
  .status-msg  { color: #9aa5ce; }
  .status-msg.error { color: #f7768e; }
  .spacer      { flex: 1; }

  .ctrl {
    display: flex; align-items: center; gap: 3px;
    font-size: 12px; color: #9aa5ce; white-space: nowrap;
  }
  .ctrl select {
    background: #1a1b26; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 1px 4px; font-size: 11px;
  }
  .ctrl input[type="checkbox"] { cursor: pointer; }

  /* ── Main split ── */
  .main-area {
    flex: 1;
    display: flex;
    min-height: 0;
    gap: 0;
  }
  .panel {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .trajectory-panel { border-right: 1px solid #2a2d3e; }
  .empty-panel {
    display: flex; align-items: center; justify-content: center;
    color: #565f89;
  }

  /* ── Move detail ── */
  .move-detail {
    padding: 4px 12px;
    background: #24283b;
    border-top: 1px solid #3b4261;
    font-size: 11px;
    color: #9aa5ce;
    flex-shrink: 0;
    min-height: 22px;
  }
  .move-detail .badge {
    background: #3d59a1; color: #7aa2f7;
    border-radius: 2px; padding: 0 3px; font-size: 10px;
  }
  .hint { color: #565f89; font-style: italic; }

  /* ── Games strip ── */
  .games-strip {
    display: flex;
    flex-shrink: 0;
    height: 20px;
    background: #1e2030;
    border-top: 1px solid #2a2d3e;
    gap: 1px;
    padding: 0 2px;
  }
  .game-block {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    color: #9aa5ce;
    background: #2a2d3e;
    border: none;
    cursor: pointer;
    border-radius: 2px;
    padding: 0;
    min-width: 0;
    overflow: hidden;
    transition: background 0.1s;
  }
  .game-block:hover    { background: #3b4261; }
  .game-block.dimmed   { opacity: 0.3; }
  .game-block.crawford { background: #3d3a1a; color: #e0af68; }
  .game-block.post-crawford { background: #3a2a1a; color: #ff9e64; }
</style>
