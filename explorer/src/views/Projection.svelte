<script>
  import { onMount } from 'svelte';
  import { fetchRuns, fetchPosition } from '../lib/api.js';
  import TileMap from '../components/TileMap.svelte';
  import PositionDetail from '../components/PositionDetail.svelte';

  let { refreshTrigger = 0 } = $props();

  let runs = $state([]);
  let error = $state(null);
  let selectedPosition = $state(null);
  let loadingPosition = $state(false);

  // Controls
  let method = $state('umap_2d');
  let colorBy = $state('cluster_id');
  let lod = $state(0);

  // Re-fetch runs whenever the parent increments refreshTrigger (tab navigation)
  // or on first mount.
  $effect(() => {
    refreshTrigger; // subscribe
    fetchRuns()
      .then(r => {
        runs = r ?? [];
        if (runs.length > 0) {
          method = runs[0].Method || runs[0].method || 'umap_2d';
        }
      })
      .catch(e => { error = e.message; });
  });

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
    Method
    <select bind:value={method}>
      {#each runs as r}
        <option value={r.Method || r.method}>{(r.Method || r.method || '').toUpperCase()}</option>
      {/each}
      {#if runs.length === 0}
        <option value="umap_2d">UMAP_2D</option>
        <option value="pca_2d">PCA_2D</option>
      {/if}
    </select>
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

  <label>
    Detail
    <select bind:value={lod}>
      <option value={0}>LoD 0 — Overview</option>
      <option value={1}>LoD 1 — Medium</option>
      <option value={2}>LoD 2 — Full</option>
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
    <TileMap {method} {lod} {colorBy} height="100%" onPointClick={handlePointClick} />
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
</style>
