<!-- Position Map / Trajectory Explorer page -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import TrajectoryMap from '$lib/../../components/TrajectoryMap.svelte';
  import Board from '$lib/../../components/Board.svelte';

  let selectedHash = $state('');
  let trajDetail   = $state<{ stats: unknown; continuations: unknown[] } | null>(null);
  let filterPlayer = $state('');
  let filterPhase  = $state('');
  let loading      = $state(false);

  async function onPositionClick(hash: string) {
    selectedHash = hash;
    loading = true;
    try {
      trajDetail = await api.map.trajectoryDetail(hash);
    } catch {}
    finally { loading = false; }
  }
</script>

<svelte:head><title>Position Map — GBF</title></svelte:head>

<h1>Position Map</h1>

<div class="controls">
  <label>Player filter <input bind:value={filterPlayer} placeholder="name…" /></label>
  <label>Phase
    <select bind:value={filterPhase}>
      <option value="">All</option>
      <option value="contact">Contact</option>
      <option value="race">Race</option>
      <option value="bearoff">Bearoff</option>
    </select>
  </label>
</div>

<div class="layout">
  <div class="map-wrap">
    <TrajectoryMap {onPositionClick} {filterPlayer} {filterPhase} />
  </div>

  <aside>
    {#if !selectedHash}
      <p class="hint">Click a point on the map to see trajectory details.</p>
    {:else if loading}
      <p class="loading">Loading…</p>
    {:else if trajDetail}
      {@const s = trajDetail.stats as Record<string, unknown>}
      <h3>Crossroad detail</h3>
      <table class="dt">
        <tr><th>Hash</th><td class="mono">{selectedHash.slice(0, 12)}…</td></tr>
        <tr><th>Matches</th><td>{s.match_count}</td></tr>
        <tr><th>Players</th><td>{s.player_count}</td></tr>
        <tr><th>Avg error</th><td>{(s.avg_error as number)?.toFixed(4)}</td></tr>
      </table>

      <h4>Top continuations</h4>
      {#each trajDetail.continuations as c: any}
        <div class="continuation">
          <span class="chash">{c.next_position_hash?.slice(0, 8)}…</span>
          <span>×{c.frequency}</span>
          <span class="err">{c.avg_error?.toFixed(4)}</span>
        </div>
      {/each}

      <div class="board-stub">
        <Board board={Array(26).fill(0)} />
        <p class="note">Full board requires position record (S4.7)</p>
      </div>
    {/if}
  </aside>
</div>

<style>
  h1 { color: #f0c060; margin-bottom: 1rem; }
  .controls { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
  label { display: flex; flex-direction: column; font-size: 0.8rem; color: #907060; gap: 0.2rem; }
  input, select { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.5rem; }
  .layout { display: grid; grid-template-columns: 1fr 280px; gap: 1.5rem; align-items: start; }
  .map-wrap { min-height: 500px; }
  aside { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  aside h3 { color: #d4a835; margin: 0 0 0.8rem; }
  h4 { color: #907060; font-size: 0.8rem; margin: 1rem 0 0.4rem; }
  .dt { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
  .dt th { color: #907060; text-align: left; padding: 0.2rem 0.5rem 0.2rem 0; width: 45%; }
  .dt td { color: #e0d0c0; }
  .mono { font-family: monospace; font-size: 0.75rem; }
  .continuation { display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 0.2rem; }
  .chash { font-family: monospace; color: #907060; }
  .err { color: #ff8060; }
  .board-stub { margin-top: 1rem; }
  .note { font-size: 0.72rem; color: #605040; font-style: italic; margin-top: 0.3rem; }
  .hint { color: #605040; font-style: italic; font-size: 0.85rem; }
  .loading { color: #907060; font-style: italic; }
</style>
