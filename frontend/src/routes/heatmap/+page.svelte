<!-- Cube Error Heatmap page -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type HeatmapCell } from '$lib/api';
  import CubeHeatmap from '$lib/../../components/CubeHeatmap.svelte';

  let cells        = $state<HeatmapCell[]>([]);
  let matchLength  = $state('');
  let playerFilter = $state('');
  let metric       = $state<keyof HeatmapCell>('avg_error');
  let loading      = $state(false);
  let err          = $state('');
  let selected     = $state<{ cell: HeatmapCell; tops: unknown[] } | null>(null);

  async function load() {
    loading = true; err = '';
    try {
      const res = await api.heatmap.cubeError({
        match_length: matchLength ? Number(matchLength) : undefined,
        player:       playerFilter || undefined,
      });
      cells = res.cells;
    } catch(e) { err = String(e); }
    finally { loading = false; }
  }

  async function onCellClick(cell: HeatmapCell) {
    try {
      const d = await api.heatmap.cell(cell.away_p1, cell.away_p2,
                  matchLength ? Number(matchLength) : undefined);
      selected = { cell: d.cell, tops: d.top_positions };
    } catch {}
  }

  const metrics: Array<[keyof HeatmapCell, string]> = [
    ['avg_error',          'Avg error'],
    ['missed_double_rate', 'Missed double rate'],
    ['wrong_take_rate',    'Wrong take rate'],
    ['wrong_pass_rate',    'Wrong pass rate'],
  ];

  onMount(load);
</script>

<svelte:head><title>Cube Heatmap — GBF</title></svelte:head>

<h1>Cube Error Heatmap</h1>

<div class="controls">
  <label>Match length
    <select bind:value={matchLength} onchange={load}>
      <option value="">All lengths</option>
      {#each [5,7,9,11,13] as l}<option value={l}>{l}-point</option>{/each}
    </select>
  </label>
  <label>Player filter <input bind:value={playerFilter} placeholder="name…" /></label>
  <button onclick={load}>Load</button>
  <span class="sep">|</span>
  <label>Metric
    <select bind:value={metric}>
      {#each metrics as [val, lbl]}<option value={val}>{lbl}</option>{/each}
    </select>
  </label>
</div>

{#if err}<p class="err">{err}</p>{/if}
{#if loading}<p class="loading">Loading…</p>{/if}

<div class="layout">
  <div class="map-wrap">
    <p class="axis-label">← Away P2</p>
    <CubeHeatmap {cells} {metric} {onCellClick} />
  </div>

  {#if selected}
  <div class="detail">
    <h3>{selected.cell?.away_p1}×{selected.cell?.away_p2} detail</h3>
    <table class="dt">
      <tr><th>Avg error</th><td>{selected.cell?.avg_error?.toFixed(4)}</td></tr>
      <tr><th>Decisions</th><td>{selected.cell?.n_decisions}</td></tr>
      <tr><th>Missed double</th><td>{(selected.cell?.missed_double_rate*100)?.toFixed(1)}%</td></tr>
      <tr><th>Wrong take</th><td>{(selected.cell?.wrong_take_rate*100)?.toFixed(1)}%</td></tr>
      <tr><th>Wrong pass</th><td>{(selected.cell?.wrong_pass_rate*100)?.toFixed(1)}%</td></tr>
    </table>
    <h4>Top positions</h4>
    {#each selected.tops as pos: any}
      <div class="top-pos">
        <span>{pos.player_name}</span>
        <span style="color:#ff6060">{pos.move_played_error?.toFixed(4)}</span>
      </div>
    {/each}
  </div>
  {/if}
</div>

<style>
  h1 { color: #f0c060; margin-bottom: 1rem; }
  .controls { display: flex; align-items: flex-end; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
  label { display: flex; flex-direction: column; font-size: 0.8rem; color: #907060; gap: 0.2rem; }
  select, input { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.5rem; }
  button { padding: 0.4rem 1rem; background: #c47a20; color: #fff; border: none; border-radius: 4px; cursor: pointer; align-self: flex-end; }
  .sep { color: #3a2010; align-self: center; }
  .layout { display: flex; gap: 2rem; align-items: flex-start; }
  .map-wrap { flex: 1; }
  .axis-label { font-size: 0.75rem; color: #907060; margin: 0 0 0.3rem; }
  .detail { min-width: 240px; background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  .detail h3 { color: #d4a835; margin: 0 0 0.8rem; }
  .dt { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  .dt th { text-align: left; color: #907060; padding: 0.2rem 0.5rem 0.2rem 0; width: 50%; }
  .dt td { color: #e0d0c0; padding: 0.2rem 0; }
  h4 { color: #907060; font-size: 0.8rem; margin: 1rem 0 0.4rem; }
  .top-pos { display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 0.2rem; }
  .err { color: #ff6060; } .loading { color: #907060; font-style: italic; }
</style>
