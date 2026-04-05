<script>
  import { fetchRuns, fetchPosition } from '../lib/api.js';
  import TileMap from '../components/TileMap.svelte';
  import PositionDetail from '../components/PositionDetail.svelte';

  let { refreshTrigger = 0 } = $props();

  let runs = $state([]);
  let runsLoaded = $state(false);
  let error = $state(null);
  let selectedPosition = $state(null);
  let loadingPosition = $state(false);

  // Controls — driven by the available runs.
  let selectedRunIdx = $state(0);
  let colorBy = $state('cluster_id');

  // Re-fetch runs whenever the parent increments refreshTrigger (tab navigation)
  // or on first mount.
  $effect(() => {
    refreshTrigger; // subscribe
    runsLoaded = false;
    fetchRuns()
      .then(r => {
        runs = r ?? [];
        selectedRunIdx = 0;
        runsLoaded = true;
      })
      .catch(e => { error = e.message; runsLoaded = true; });
  });

  // Derived: active (method, lod) pair from the selected run.
  let activeRun = $derived(runs[selectedRunIdx] ?? null);
  let method = $derived(activeRun ? (activeRun.Method || activeRun.method || 'umap_2d') : 'umap_2d');
  let lod = $derived(activeRun ? (activeRun.lod ?? 0) : 0);

  function runLabel(r) {
    const m = (r.Method || r.method || '').toUpperCase();
    const l = r.lod ?? 0;
    const n = r.NPoints ?? r.n_points ?? 0;
    return `${m}  ·  LoD ${l}  ·  ${n.toLocaleString()} pts`;
  }

  async function handlePointClick({ position_id }) {
    if (!position_id) return;
    loadingPosition = true;
    try {
      selectedPosition = await fetchPosition(position_id);
    } catch (e) {
      console.error('Failed to load position:', e);
    }
    loadingPosition = false;
  }
</script>

<div class="controls">
  <label>
    Projection run
    {#if runs.length > 0}
      <select bind:value={selectedRunIdx}>
        {#each runs as r, i}
          <option value={i}>{runLabel(r)}</option>
        {/each}
      </select>
    {:else if runsLoaded}
      <span class="no-runs">No projections computed yet — go to Setup</span>
    {:else}
      <span class="no-runs">Loading…</span>
    {/if}
  </label>

  <label>
    Color by
    <select bind:value={colorBy}>
      <option value="cluster_id">Cluster</option>
      <option value="pos_class">Position class</option>
      <option value="away_x">Away X</option>
      <option value="away_o">Away O</option>
    </select>
  </label>
</div>

{#if error}
  <div class="card" style="border-color:var(--red)">
    <p style="color:var(--red)">{error}</p>
  </div>
{/if}

<div class="split-layout">
  <div class="chart-panel">
    {#if runsLoaded && activeRun}
      <TileMap {method} {lod} {colorBy} height="100%" onPointClick={handlePointClick} />
    {:else if runsLoaded}
      <div class="no-proj-msg">
        No projections available.<br>
        Go to <strong>Setup → Projections</strong> to compute one.
      </div>
    {:else}
      <div class="no-proj-msg">Loading…</div>
    {/if}
  </div>

  <div class="detail-panel">
    {#if loadingPosition}
      <div class="loading">Loading position...</div>
    {:else}
      <PositionDetail position={selectedPosition} />
    {/if}
  </div>
</div>

<style>
  .split-layout {
    display: flex;
    gap: 12px;
    height: calc(100vh - 180px);
    min-height: 500px;
  }
  .chart-panel {
    flex: 1;
    min-width: 0;
  }
  .detail-panel {
    width: 380px;
    flex-shrink: 0;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px;
    overflow: hidden;
  }
  .no-proj-msg {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    font-size: 14px;
    text-align: center;
    line-height: 1.8;
  }
  .no-runs {
    color: var(--text-muted);
    font-size: 12px;
    margin-left: 8px;
  }
  .controls label {
    display: flex;
    align-items: center;
    gap: 8px;
  }
</style>
