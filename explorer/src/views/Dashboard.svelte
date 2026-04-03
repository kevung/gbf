<script>
  import { onMount } from 'svelte';
  import { fetchStats, formatNumber } from '../lib/api.js';
  import Chart from '../components/Chart.svelte';

  let stats = $state(null);
  let error = $state(null);

  onMount(async () => {
    try {
      stats = await fetchStats();
    } catch (e) {
      error = e.message;
    }
  });

  let classChartOption = $derived(stats ? {
    backgroundColor: 'transparent',
    title: { text: 'Position Classes', left: 'center', textStyle: { color: '#c0caf5', fontSize: 14 } },
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: Object.entries(stats.class_distribution).map(([k, v]) => ({
        name: k, value: v,
      })),
      label: { color: '#c0caf5' },
      itemStyle: {
        borderColor: '#1a1b26',
        borderWidth: 2,
      },
    }],
    color: ['#f7768e', '#7aa2f7', '#9ece6a'],
  } : null);

  let scoreChartOption = $derived(stats && stats.score_distribution.length > 0 ? {
    backgroundColor: 'transparent',
    title: { text: 'Score Distribution (top 20)', left: 'center', textStyle: { color: '#c0caf5', fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const d = params[0];
        return `${d.name}<br/>Count: ${d.value.toLocaleString()}`;
      },
    },
    xAxis: {
      type: 'category',
      data: stats.score_distribution.map(d => `${d.away_x}-${d.away_o}`),
      axisLabel: { color: '#565f89', fontSize: 11, rotate: 45 },
      axisLine: { lineStyle: { color: '#3b4261' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#565f89', fontSize: 11 },
      splitLine: { lineStyle: { color: '#3b4261' } },
    },
    series: [{
      type: 'bar',
      data: stats.score_distribution.map(d => d.count),
      itemStyle: { color: '#7aa2f7' },
    }],
    grid: { left: 60, right: 20, bottom: 60, top: 40 },
  } : null);

  let runsData = $derived(stats ? stats.projection_runs : []);
</script>

{#if error}
  <div class="card" style="border-color:var(--red)">
    <h2 style="color:var(--red)">Error</h2>
    <p>{error}</p>
  </div>
{:else if !stats}
  <div class="loading">Loading dashboard...</div>
{:else}
  <div class="stats-grid">
    <div class="stat-card">
      <div class="label">Positions</div>
      <div class="value">{formatNumber(stats.position_count)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Matches</div>
      <div class="value">{formatNumber(stats.match_count)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Games</div>
      <div class="value">{formatNumber(stats.game_count)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Moves</div>
      <div class="value">{formatNumber(stats.move_count)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Analyses</div>
      <div class="value">{formatNumber(stats.analysis_count)}</div>
    </div>
    <div class="stat-card">
      <div class="label">BMAB Dir</div>
      <div class="value" style="font-size:14px">{stats.has_bmab ? '✅ configured' : '❌ not set'}</div>
    </div>
  </div>

  <div class="chart-grid" style="margin-top:16px">
    {#if classChartOption}
      <div class="card">
        <Chart option={classChartOption} height="300px" />
      </div>
    {/if}
    {#if scoreChartOption}
      <div class="card">
        <Chart option={scoreChartOption} height="300px" />
      </div>
    {/if}
  </div>

  {#if runsData.length > 0}
    <div class="card" style="margin-top:16px">
      <h2>Projection Runs</h2>
      <table>
        <thead>
          <tr>
            <th>Method</th>
            <th>Version</th>
            <th>Points</th>
            <th>Created</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {#each runsData as run}
            <tr>
              <td>{run.Method || run.method}</td>
              <td>{run.FeatureVersion || run.feature_version}</td>
              <td>{formatNumber(run.NPoints || run.n_points)}</td>
              <td>{run.CreatedAt || run.created_at}</td>
              <td>{(run.IsActive || run.is_active) ? '✅' : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
{/if}
