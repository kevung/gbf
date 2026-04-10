<!-- S4.7 — Position Map & Trajectory Explorer (full implementation) -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import TrajectoryMap from '$lib/../../components/TrajectoryMap.svelte';
  import Board from '$lib/../../components/Board.svelte';

  // ── Filter / mode state ────────────────────────────────────────────────────
  let filterPlayer  = $state('');
  let filterPhase   = $state('');
  let errorMin      = $state(0);
  let colorBy       = $state<'density' | 'avg_error' | 'cluster'>('density');
  let showTrajs     = $state(true);
  let compareMode   = $state(false);
  let compareP1     = $state('');
  let compareP2     = $state('');
  let trajColorMode = $state<'error' | 'match' | 'result'>('error');

  // ── Crossroad detail state ─────────────────────────────────────────────────
  let selectedHash  = $state('');
  let detail        = $state<{
    stats: Record<string, unknown>;
    continuations: Record<string, unknown>[];
    players: string[];
  } | null>(null);
  let trajs         = $state<{ trajectories: unknown[] } | null>(null);
  let detailLoading = $state(false);

  async function onCrossroadSelect(hash: string) {
    if (!hash || hash === selectedHash) return;
    selectedHash  = hash;
    detailLoading = true;
    detail        = null;
    trajs         = null;
    try {
      const [d, t] = await Promise.all([
        api.map.trajectoryDetail(hash),
        api.map.trajectories(hash, { limit: 100,
          ...(filterPlayer && { player: filterPlayer }) }),
      ]);
      detail = d as typeof detail;
      trajs  = t as { trajectories: unknown[] };
    } catch(e) {
      console.error(e);
    } finally {
      detailLoading = false;
    }
  }

  // ── Continuation bar chart (inline SVG) ───────────────────────────────────
  function continuationBar(freq: number, maxFreq: number) {
    const w = maxFreq > 0 ? (freq / maxFreq) * 100 : 0;
    return `width:${w.toFixed(1)}%;background:#d4a83580;height:10px;border-radius:3px;`;
  }

  let maxContFreq = $derived(
    detail ? Math.max(...detail.continuations.map(c => (c as Record<string,unknown>).frequency as number ?? 0)) : 1
  );
</script>

<svelte:head><title>Position Map — GBF</title></svelte:head>

<h1>Position Map <span class="sub">UMAP Trajectory Explorer</span></h1>

<!-- ── Controls bar ──────────────────────────────────────────────────────── -->
<div class="controls">
  <div class="ctrl-group">
    <label>Player <input bind:value={filterPlayer} placeholder="filter…" /></label>
    <label>Phase
      <select bind:value={filterPhase}>
        <option value="">All</option>
        <option value="contact">Contact</option>
        <option value="race">Race</option>
        <option value="bearoff">Bearoff</option>
      </select>
    </label>
    <label>Min error
      <input type="number" bind:value={errorMin} min="0" max="2" step="0.01" />
    </label>
  </div>

  <div class="ctrl-group">
    <label>Color by
      <select bind:value={colorBy}>
        <option value="density">Density</option>
        <option value="avg_error">Avg error</option>
        <option value="cluster">Cluster</option>
      </select>
    </label>
    <label>Trajectories
      <select bind:value={trajColorMode}>
        <option value="error">Error gradient</option>
        <option value="match">Per match</option>
        <option value="result">Win / Loss</option>
      </select>
    </label>
    <label class="check"><input type="checkbox" bind:checked={showTrajs} /> Show trajectories</label>
  </div>

  <div class="ctrl-group">
    <label class="check compare-toggle">
      <input type="checkbox" bind:checked={compareMode} />
      Compare mode
    </label>
    {#if compareMode}
      <label>P1 <input bind:value={compareP1} placeholder="player 1…" style="width:110px" /></label>
      <label>P2 <input bind:value={compareP2} placeholder="player 2…" style="width:110px" /></label>
    {/if}
  </div>
</div>

<!-- ── Main layout ────────────────────────────────────────────────────────── -->
<div class="layout">
  <!-- Map -->
  <div class="map-wrap">
    <TrajectoryMap
      {onCrossroadSelect}
      {filterPlayer}
      {filterPhase}
      {errorMin}
      {colorBy}
      showTrajectories={showTrajs}
      {compareMode}
      comparePlayer1={compareP1}
      comparePlayer2={compareP2}
    />
  </div>

  <!-- Crossroad detail panel -->
  <aside>
    {#if !selectedHash}
      <div class="hint">
        <p>Click any point or hexbin on the map to explore trajectories.</p>
        <ul>
          <li><strong>Zoom out</strong>: density view (hexbins)</li>
          <li><strong>Zoom in</strong>: individual positions</li>
          <li><strong>Click</strong>: load trajectories + detail</li>
        </ul>
      </div>

    {:else if detailLoading}
      <p class="loading">Loading crossroad…</p>

    {:else if detail}
      <!-- Stats -->
      <h3>Crossroad</h3>
      <div class="hash">{selectedHash.slice(0, 16)}…</div>
      <div class="stat-row">
        <div class="stat"><div class="val">{detail.stats.match_count ?? '–'}</div><div class="lbl">matches</div></div>
        <div class="stat"><div class="val">{detail.stats.player_count ?? '–'}</div><div class="lbl">players</div></div>
        <div class="stat"><div class="val">{(detail.stats.avg_error as number)?.toFixed(3) ?? '–'}</div><div class="lbl">avg error</div></div>
      </div>

      <!-- Board placeholder -->
      <div class="board-wrap">
        <Board board={Array(26).fill(0)} />
        <p class="note">Full board requires position record enrichment (position_hash → board state).</p>
      </div>

      <!-- Continuations -->
      {#if detail.continuations.length}
        <h4>Top continuations</h4>
        <div class="cont-list">
          {#each detail.continuations as c: any}
            <div class="cont-item">
              <span class="chash">{(c.next_position_hash ?? '').slice(0, 8)}…</span>
              <div class="cont-bar-wrap">
                <div style={continuationBar(c.frequency, maxContFreq)}></div>
              </div>
              <span class="cfreq">×{c.frequency}</span>
              <span class="cerr">{c.avg_error?.toFixed(3)}</span>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Players -->
      {#if detail.players.length}
        <h4>Players ({detail.players.length})</h4>
        <div class="players">
          {#each detail.players.slice(0, 10) as name}
            <a href="/player/{encodeURIComponent(name)}" class="player-chip">{name}</a>
          {/each}
          {#if detail.players.length > 10}
            <span class="more">+{detail.players.length - 10} more</span>
          {/if}
        </div>
      {/if}

      <!-- Trajectory summary -->
      {#if trajs}
        <h4>Trajectories ({(trajs.trajectories as unknown[]).length})</h4>
        {#if compareMode}
          <div class="compare-legend">
            <span class="dot blue"></span> {compareP1 || 'Player 1'}
            <span class="dot red"></span>  {compareP2 || 'Player 2'}
          </div>
        {/if}
        <p class="note">Trajectories rendered on map as coloured polylines.</p>
      {/if}
    {/if}
  </aside>
</div>

<style>
  h1 { color: #f0c060; margin-bottom: 0.3rem; }
  .sub { font-size: 0.75rem; color: #907060; font-weight: normal; }
  .controls { display: flex; flex-wrap: wrap; gap: 1.2rem; background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 1rem; }
  .ctrl-group { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: flex-end; }
  .ctrl-group::after { content: ''; width: 1px; background: #3a2010; align-self: stretch; margin: 0 0.3rem; }
  .ctrl-group:last-child::after { display: none; }
  label { display: flex; flex-direction: column; font-size: 0.78rem; color: #907060; gap: 0.2rem; }
  label.check { flex-direction: row; align-items: center; gap: 0.4rem; }
  input, select { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.25rem 0.4rem; font-size: 0.82rem; }
  .layout { display: grid; grid-template-columns: 1fr 290px; gap: 1.2rem; align-items: start; }
  .map-wrap { }
  aside { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  h3 { color: #d4a835; margin: 0 0 0.4rem; font-size: 1rem; }
  h4 { color: #907060; font-size: 0.78rem; margin: 0.9rem 0 0.3rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .hash { font-family: monospace; font-size: 0.72rem; color: #605040; margin-bottom: 0.8rem; word-break: break-all; }
  .stat-row { display: flex; gap: 0.6rem; margin-bottom: 0.8rem; }
  .stat { flex: 1; background: #0f0a05; border: 1px solid #2a1508; border-radius: 6px; padding: 0.4rem; text-align: center; }
  .stat .val { font-size: 1.1rem; font-weight: bold; color: #f0c060; }
  .stat .lbl { font-size: 0.68rem; color: #605040; }
  .board-wrap { margin: 0.6rem 0; }
  .note { font-size: 0.7rem; color: #605040; font-style: italic; margin: 0.2rem 0; }
  .cont-list { display: flex; flex-direction: column; gap: 0.25rem; }
  .cont-item { display: grid; grid-template-columns: 70px 1fr 30px 46px; align-items: center; gap: 0.3rem; font-size: 0.72rem; }
  .chash { font-family: monospace; color: #807060; }
  .cont-bar-wrap { background: #0f0a05; border-radius: 3px; overflow: hidden; }
  .cfreq { color: #d4a835; text-align: right; }
  .cerr  { color: #ff8060; }
  .players { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.2rem; }
  .player-chip { font-size: 0.72rem; background: #2a1508; border: 1px solid #3a2010; border-radius: 10px; padding: 0.15rem 0.5rem; color: #d4a835; text-decoration: none; }
  .player-chip:hover { background: #3a2010; }
  .more { font-size: 0.72rem; color: #605040; }
  .compare-legend { display: flex; gap: 0.8rem; font-size: 0.78rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 3px; }
  .dot.blue { background: #4060ff; } .dot.red { background: #ff6040; }
  .hint { color: #605040; font-size: 0.85rem; }
  .hint ul { margin: 0.5rem 0 0 1rem; line-height: 1.8; }
  .loading { color: #907060; font-style: italic; font-size: 0.85rem; }
  .compare-toggle { font-weight: 500; color: #d4a835; }
</style>
