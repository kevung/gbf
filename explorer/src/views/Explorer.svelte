<script>
  import { onMount } from 'svelte';
  import { fetchFeatureSample, fetchFeatureNames, fetchPosition } from '../lib/api.js';
  import { cachedFetch } from '../lib/cache.js';
  import Chart from '../components/Chart.svelte';
  import PositionDetail from '../components/PositionDetail.svelte';

  let featureNames = $state([]);
  let sampleData = $state(null);
  let loading = $state(false);
  let error = $state(null);
  let selectedPosition = $state(null);
  let loadingPosition = $state(false);

  // Controls
  let featureX = $state('pip_x');
  let featureY = $state('pip_o');
  let colorFeature = $state('pos_class');
  let chartType = $state('scatter');
  let histFeature = $state('pip_diff');
  let sampleSize = $state(5000);

  onMount(async () => {
    try {
      featureNames = await cachedFetch('explorer:featureNames', fetchFeatureNames);
      await loadSample();
    } catch (e) {
      error = e.message;
    }
  });

  async function loadSample() {
    loading = true;
    error = null;
    try {
      sampleData = await cachedFetch(`explorer:sample:${sampleSize}`, () => fetchFeatureSample(sampleSize));
    } catch (e) {
      error = e.message;
    }
    loading = false;
  }

  function idx(name) {
    return sampleData?.names?.indexOf(name) ?? -1;
  }

  let scatterOption = $derived.by(() => {
    if (!sampleData || chartType !== 'scatter') return null;
    const xi = idx(featureX);
    const yi = idx(featureY);
    const ci = idx(colorFeature);
    if (xi < 0 || yi < 0) return null;

    const data = sampleData.data;
    const vals = ci >= 0 ? data.map(r => r[ci]) : data.map(() => 0);
    const minV = Math.min(...vals);
    const maxV = Math.max(...vals);

    return {
      backgroundColor: 'transparent',
      title: {
        text: `${featureX} vs ${featureY} (n=${data.length})`,
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p) => `${featureX}: ${p.data[0].toFixed(2)}<br/>${featureY}: ${p.data[1].toFixed(2)}<br/>${colorFeature}: ${p.data[2].toFixed(2)}`,
      },
      visualMap: {
        min: minV,
        max: maxV,
        calculable: true,
        orient: 'vertical',
        right: 10,
        top: 'center',
        inRange: { color: ['#7aa2f7', '#9ece6a', '#e0af68', '#f7768e'] },
        textStyle: { color: '#565f89' },
        text: [colorFeature, ''],
      },
      xAxis: {
        type: 'value',
        name: featureX,
        nameLocation: 'middle',
        nameGap: 30,
        nameTextStyle: { color: '#c0caf5' },
        axisLabel: { color: '#565f89' },
        splitLine: { lineStyle: { color: '#3b4261' } },
      },
      yAxis: {
        type: 'value',
        name: featureY,
        nameLocation: 'middle',
        nameGap: 40,
        nameTextStyle: { color: '#c0caf5' },
        axisLabel: { color: '#565f89' },
        splitLine: { lineStyle: { color: '#3b4261' } },
      },
      series: [{
        type: 'scatter',
        data: data.map((r, i) => [r[xi], r[yi], vals[i], sampleData.ids?.[i]]),
        symbolSize: 6,
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 }, scale: 2.5 },
        large: data.length > 20000,
        largeThreshold: 20000,
      }],
      grid: { left: 60, right: 80, bottom: 50, top: 40 },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0 },
        { type: 'inside', yAxisIndex: 0 },
      ],
    };
  });

  let histOption = $derived.by(() => {
    if (!sampleData || chartType !== 'histogram') return null;
    const fi = idx(histFeature);
    if (fi < 0) return null;

    const values = sampleData.data.map(r => r[fi]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const bins = 50;
    const step = (max - min) / bins || 1;
    const counts = new Array(bins).fill(0);
    for (const v of values) {
      const b = Math.min(Math.floor((v - min) / step), bins - 1);
      counts[b]++;
    }
    const total = values.length;
    const pcts = counts.map(c => +(c / total * 100).toFixed(2));

    return {
      backgroundColor: 'transparent',
      title: {
        text: `Distribution of ${histFeature} (n=${values.length})`,
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const d = params[0];
          return `${d.name}<br/>${d.value}%<br/>Count: ${counts[d.dataIndex]}`;
        },
      },
      xAxis: {
        type: 'category',
        data: counts.map((_, i) => (min + i * step).toFixed(1)),
        axisLabel: { color: '#565f89', fontSize: 10, rotate: 45, interval: Math.floor(bins / 10) },
        axisLine: { lineStyle: { color: '#3b4261' } },
        name: histFeature,
        nameLocation: 'middle',
        nameGap: 40,
        nameTextStyle: { color: '#c0caf5' },
      },
      yAxis: {
        type: 'value',
        name: '%',
        nameTextStyle: { color: '#c0caf5' },
        axisLabel: { color: '#565f89' },
        splitLine: { lineStyle: { color: '#3b4261' } },
      },
      series: [{
        type: 'bar',
        data: pcts,
        itemStyle: { color: '#7aa2f7' },
      }],
      grid: { left: 60, right: 20, bottom: 60, top: 40 },
    };
  });

  let boxOption = $derived.by(() => {
    if (!sampleData || chartType !== 'boxplot') return null;

    // Show boxplot for a selection of derived features
    const derived = ['blot_x', 'blot_o', 'made_x', 'made_o', 'prime_x', 'prime_o', 'anchor_x', 'anchor_o', 'pip_diff'];
    const available = derived.filter(d => idx(d) >= 0);

    const boxData = available.map(name => {
      const fi = idx(name);
      const vals = sampleData.data.map(r => r[fi]).sort((a, b) => a - b);
      const q = (p) => {
        const pos = p * (vals.length - 1);
        const lo = Math.floor(pos);
        const hi = Math.ceil(pos);
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo);
      };
      return [q(0), q(0.25), q(0.5), q(0.75), q(1)];
    });

    return {
      backgroundColor: 'transparent',
      title: {
        text: `Feature Box Plots (n=${sampleData.data.length})`,
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: { trigger: 'item' },
      xAxis: {
        type: 'category',
        data: available,
        axisLabel: { color: '#565f89', fontSize: 11, rotate: 30 },
        axisLine: { lineStyle: { color: '#3b4261' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#565f89' },
        splitLine: { lineStyle: { color: '#3b4261' } },
      },
      series: [{
        type: 'boxplot',
        data: boxData,
        itemStyle: { color: '#7aa2f7', borderColor: '#7aa2f7' },
      }],
      grid: { left: 60, right: 20, bottom: 60, top: 40 },
    };
  });

  let corrOption = $derived.by(() => {
    if (!sampleData || chartType !== 'correlation') return null;

    const selected = ['pip_x', 'pip_o', 'pip_diff', 'blot_x', 'made_x', 'prime_x', 'anchor_x', 'away_x', 'pos_class'];
    const available = selected.filter(d => idx(d) >= 0);

    // Compute correlation matrix
    const n = sampleData.data.length;
    const means = available.map(name => {
      const fi = idx(name);
      return sampleData.data.reduce((s, r) => s + r[fi], 0) / n;
    });

    const corrData = [];
    for (let i = 0; i < available.length; i++) {
      for (let j = 0; j < available.length; j++) {
        const fi = idx(available[i]);
        const fj = idx(available[j]);
        let sumXY = 0, sumX2 = 0, sumY2 = 0;
        for (const r of sampleData.data) {
          const dx = r[fi] - means[i];
          const dy = r[fj] - means[j];
          sumXY += dx * dy;
          sumX2 += dx * dx;
          sumY2 += dy * dy;
        }
        const corr = sumX2 > 0 && sumY2 > 0 ? sumXY / Math.sqrt(sumX2 * sumY2) : 0;
        corrData.push([j, i, parseFloat(corr.toFixed(3))]);
      }
    }

    return {
      backgroundColor: 'transparent',
      title: {
        text: 'Feature Correlations',
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: {
        formatter: (p) => `${available[p.data[0]]} × ${available[p.data[1]]}<br/>r = ${p.data[2]}`,
      },
      xAxis: {
        type: 'category',
        data: available,
        axisLabel: { color: '#565f89', fontSize: 10, rotate: 45 },
        axisLine: { lineStyle: { color: '#3b4261' } },
      },
      yAxis: {
        type: 'category',
        data: available,
        axisLabel: { color: '#565f89', fontSize: 10 },
        axisLine: { lineStyle: { color: '#3b4261' } },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: 'vertical',
        right: 10,
        top: 'center',
        inRange: { color: ['#f7768e', '#1a1b26', '#7aa2f7'] },
        textStyle: { color: '#565f89' },
      },
      series: [{
        type: 'heatmap',
        data: corrData,
        label: { show: available.length <= 10, color: '#c0caf5', fontSize: 10 },
        itemStyle: { borderColor: '#1a1b26', borderWidth: 1 },
      }],
      grid: { left: 80, right: 80, bottom: 60, top: 40 },
    };
  });

  let activeOption = $derived(
    chartType === 'scatter' ? scatterOption :
    chartType === 'histogram' ? histOption :
    chartType === 'boxplot' ? boxOption :
    chartType === 'correlation' ? corrOption : null
  );

  // Only the scatter chart supports point clicks (it carries posID in data[3])
  let chartClickable = $derived(chartType === 'scatter');

  async function handlePointClick(params) {
    const posId = params.data?.[3];
    if (!posId) return;
    loadingPosition = true;
    try {
      selectedPosition = await fetchPosition(posId);
    } catch (e) {
      console.error('Failed to load position:', e);
    }
    loadingPosition = false;
  }
</script>

<div class="controls">
  <label>
    Chart type
    <select bind:value={chartType}>
      <option value="scatter">Scatter (X vs Y)</option>
      <option value="histogram">Histogram</option>
      <option value="boxplot">Box Plot</option>
      <option value="correlation">Correlation Matrix</option>
    </select>
  </label>

  {#if chartType === 'scatter'}
    <label>
      X axis
      <select bind:value={featureX}>
        {#each featureNames as f}
          <option value={f}>{f}</option>
        {/each}
      </select>
    </label>

    <label>
      Y axis
      <select bind:value={featureY}>
        {#each featureNames as f}
          <option value={f}>{f}</option>
        {/each}
      </select>
    </label>

    <label>
      Color by
      <select bind:value={colorFeature}>
        {#each featureNames as f}
          <option value={f}>{f}</option>
        {/each}
      </select>
    </label>
  {/if}

  {#if chartType === 'histogram'}
    <label>
      Feature
      <select bind:value={histFeature}>
        {#each featureNames as f}
          <option value={f}>{f}</option>
        {/each}
      </select>
    </label>
  {/if}

  <label>
    Sample size
    <select bind:value={sampleSize} onchange={loadSample}>
      <option value={1000}>1K</option>
      <option value={5000}>5K</option>
      <option value={10000}>10K</option>
      <option value={25000}>25K</option>
      <option value={50000}>50K</option>
    </select>
  </label>

  <button class="btn primary" onclick={loadSample} disabled={loading}>
    {loading ? 'Loading…' : 'Sample'}
  </button>
</div>

{#if error}
  <div class="card" style="border-color:var(--red)">
    <p style="color:var(--red)">{error}</p>
  </div>
{/if}

<div class="split-layout" class:has-detail={chartClickable}>
  <div class="chart-panel">
    {#if loading}
      <div class="loading">Loading feature data...</div>
    {:else if activeOption}
      <Chart option={activeOption} height="100%" onPointClick={chartClickable ? handlePointClick : null} />
    {:else}
      <div class="card">
        <p style="color:var(--text-muted)">No data to display. Import positions first or adjust chart settings.</p>
      </div>
    {/if}
  </div>

  {#if chartClickable}
    <div class="detail-panel">
      {#if loadingPosition}
        <div class="loading">Loading position...</div>
      {:else}
        <PositionDetail position={selectedPosition} />
      {/if}
    </div>
  {/if}
</div>

<style>
  .split-layout {
    height: calc(100vh - 180px);
    min-height: 500px;
  }
  .split-layout.has-detail {
    display: flex;
    gap: 12px;
  }
  .split-layout:not(.has-detail) .chart-panel {
    height: 100%;
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