<script>
  import { onMount } from 'svelte';
  import { fetchProjection, fetchRuns, fetchFeatureNames, fetchPosition } from '../lib/api.js';
  import { cachedFetch, invalidateCache } from '../lib/cache.js';
  import Chart from '../components/Chart.svelte';
  import PositionDetail from '../components/PositionDetail.svelte';

  let runs = $state([]);
  let featureNames = $state([]);
  let projectionData = $state(null);
  let loading = $state(false);
  let error = $state(null);
  let selectedPosition = $state(null);
  let loadingPosition = $state(false);

  // Controls
  let method = $state('umap_2d');
  let colorBy = $state('cluster_id');
  let limit = $state(10000);
  let filterClass = $state('');
  let filterCluster = $state('');

  onMount(async () => {
    try {
      [runs, featureNames] = await Promise.all([
        cachedFetch('proj:runs', fetchRuns),
        cachedFetch('proj:featureNames', fetchFeatureNames),
      ]);
      if (runs.length > 0) {
        method = runs[0].Method || runs[0].method || 'umap_2d';
      }
      await loadProjection();
    } catch (e) {
      error = e.message;
    }
  });

  async function loadProjection() {
    loading = true;
    error = null;
    try {
      const opts = { limit };
      if (filterClass !== '') opts.pos_class = parseInt(filterClass);
      if (filterCluster !== '') opts.cluster_id = parseInt(filterCluster);
      const cacheKey = `proj:data:${method}:${limit}:${filterClass}:${filterCluster}`;
      projectionData = await cachedFetch(cacheKey, () => fetchProjection(method, opts));
    } catch (e) {
      error = e.message;
    }
    loading = false;
  }

  function getColorValue(pt) {
    if (colorBy === 'cluster_id') return pt.cluster_id ?? -1;
    if (colorBy === 'pos_class') return pt.pos_class ?? 0;
    if (colorBy === 'away_x') return pt.away_x ?? 0;
    if (colorBy === 'away_o') return pt.away_o ?? 0;
    return 0;
  }

  const classColors = ['#f7768e', '#7aa2f7', '#9ece6a'];
  const clusterColors = ['#7aa2f7', '#9ece6a', '#f7768e', '#ff9e64', '#bb9af7', '#7dcfff', '#e0af68', '#73daca',
    '#c0caf5', '#9aa5ce', '#a9b1d6', '#cfc9c2', '#f7768e', '#ff9e64', '#e0af68', '#9ece6a', '#73daca', '#7dcfff', '#7aa2f7', '#bb9af7'];

  let availableClusters = $derived.by(() => {
    if (!projectionData?.clusters?.length) {
      const pts = projectionData?.points || [];
      return [...new Set(pts.map(p => p.cluster_id).filter(c => c != null && c >= 0))].sort((a, b) => a - b);
    }
    return projectionData.clusters.map(c => c.cluster_id).sort((a, b) => a - b);
  });

  let chartOption = $derived.by(() => {
    if (!projectionData || !projectionData.points || projectionData.points.length === 0) return null;

    const points = projectionData.points;

    if (colorBy === 'cluster_id') {
      const clusters = [...new Set(points.map(p => p.cluster_id ?? -1))].sort((a, b) => a - b);
      return {
        backgroundColor: 'transparent',
        title: {
          text: `${method.toUpperCase()} — ${points.length.toLocaleString()} points`,
          left: 'center',
          textStyle: { color: '#c0caf5', fontSize: 14 },
        },
        tooltip: {
          trigger: 'item',
          formatter: (p) => `ID: ${p.data[2]}<br/>Cluster: ${p.data[3]}<br/>x: ${p.data[0].toFixed(3)}<br/>y: ${p.data[1].toFixed(3)}`,
        },
        legend: {
          data: clusters.map(c => `Cluster ${c}`),
          bottom: 0,
          textStyle: { color: '#565f89', fontSize: 11 },
        },
        xAxis: { type: 'value', axisLabel: { color: '#565f89' }, splitLine: { lineStyle: { color: '#3b4261' } } },
        yAxis: { type: 'value', axisLabel: { color: '#565f89' }, splitLine: { lineStyle: { color: '#3b4261' } } },
        series: clusters.map((c, i) => ({
          name: `Cluster ${c}`,
          type: 'scatter',
          data: points.filter(p => (p.cluster_id ?? -1) === c).map(p => [p.x, p.y, p.position_id, c]),
          symbolSize: 6,
          itemStyle: { color: clusterColors[i % clusterColors.length], opacity: 0.6 },
          emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 }, scale: 2.5 },
          large: points.length > 20000,
          largeThreshold: 20000,
        })),
        grid: { left: 50, right: 20, bottom: 50, top: 40 },
        dataZoom: [
          { type: 'inside', xAxisIndex: 0 },
          { type: 'inside', yAxisIndex: 0 },
        ],
      };
    }

    // Continuous color
    const vals = points.map(p => getColorValue(p));
    const minVal = Math.min(...vals);
    const maxVal = Math.max(...vals);

    return {
      backgroundColor: 'transparent',
      title: {
        text: `${method.toUpperCase()} — colored by ${colorBy}`,
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p) => `ID: ${p.data[2]}<br/>${colorBy}: ${p.data[3]}<br/>x: ${p.data[0].toFixed(3)}<br/>y: ${p.data[1].toFixed(3)}`,
      },
      visualMap: {
        min: minVal,
        max: maxVal,
        calculable: true,
        orient: 'vertical',
        right: 10,
        top: 'center',
        inRange: { color: ['#7aa2f7', '#9ece6a', '#e0af68', '#f7768e'] },
        textStyle: { color: '#565f89' },
      },
      xAxis: { type: 'value', axisLabel: { color: '#565f89' }, splitLine: { lineStyle: { color: '#3b4261' } } },
      yAxis: { type: 'value', axisLabel: { color: '#565f89' }, splitLine: { lineStyle: { color: '#3b4261' } } },
      series: [{
        type: 'scatter',
        data: points.map((p, i) => [p.x, p.y, p.position_id, vals[i]]),
        symbolSize: 6,
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 }, scale: 2.5 },
        large: points.length > 20000,
        largeThreshold: 20000,
      }],
      grid: { left: 50, right: 80, bottom: 30, top: 40 },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0 },
        { type: 'inside', yAxisIndex: 0 },
      ],
    };
  });

  async function handlePointClick(params) {
    const posId = params.data?.[2];
    if (posId) {
      loadingPosition = true;
      try {
        selectedPosition = await fetchPosition(posId);
      } catch (e) {
        console.error('Failed to load position:', e);
      }
      loadingPosition = false;
    }
  }

  const classLabels = { 0: 'contact', 1: 'race', 2: 'bearoff' };
</script>

<div class="controls">
  <label>
    Method
    <select bind:value={method} onchange={loadProjection}>
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
    Points
    <select bind:value={limit} onchange={loadProjection}>
      <option value={1000}>1K</option>
      <option value={5000}>5K</option>
      <option value={10000}>10K</option>
      <option value={25000}>25K</option>
      <option value={50000}>50K</option>
    </select>
  </label>

  <label>
    Class filter
    <select bind:value={filterClass} onchange={loadProjection}>
      <option value="">All</option>
      <option value="0">Contact</option>
      <option value="1">Race</option>
      <option value="2">Bearoff</option>
    </select>
  </label>

  <label>
    Cluster filter
    <select bind:value={filterCluster} onchange={loadProjection}>
      <option value="">All</option>
      {#each availableClusters as c}
        <option value={c}>{c}</option>
      {/each}
    </select>
  </label>

  <button class="btn primary" onclick={() => { invalidateCache('proj'); loadProjection(); }} disabled={loading}>
    {loading ? 'Loading…' : 'Refresh'}
  </button>
</div>

{#if error}
  <div class="card" style="border-color:var(--red)">
    <p style="color:var(--red)">{error}</p>
  </div>
{/if}

<div class="split-layout">
  <div class="chart-panel">
    {#if loading}
      <div class="loading">Loading projection data...</div>
    {:else if chartOption}
      <Chart option={chartOption} height="100%" onPointClick={handlePointClick} />
    {:else}
      <div class="card">
        <p style="color:var(--text-muted)">No projection data available. Import data and compute projections first.</p>
      </div>
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

{#if projectionData?.clusters?.length > 0}
  <div class="card" style="margin-top:12px">
    <h2>Cluster Summary</h2>
    <table>
      <thead>
        <tr><th>Cluster</th><th>Count</th><th>Centroid X</th><th>Centroid Y</th></tr>
      </thead>
      <tbody>
        {#each projectionData.clusters as c}
          <tr>
            <td>{c.cluster_id}</td>
            <td>{c.count?.toLocaleString()}</td>
            <td>{c.centroid_x?.toFixed(3)}</td>
            <td>{c.centroid_y?.toFixed(3)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

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