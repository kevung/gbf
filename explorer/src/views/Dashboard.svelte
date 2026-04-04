<script>
  import { onMount } from 'svelte';
  import { fetchStats, formatNumber } from '../lib/api.js';
  import { cachedFetch } from '../lib/cache.js';
  import Chart from '../components/Chart.svelte';

  let stats = $state(null);
  let error = $state(null);

  onMount(async () => {
    try {
      stats = await cachedFetch('dashboard:stats', fetchStats);
    } catch (e) {
      error = e.message;
    }
  });

  let classChartOption = $derived(stats ? {
    backgroundColor: 'transparent',
    title: { text: 'Position Classes', left: 'center', textStyle: { color: '#c0caf5', fontSize: 14 } },
    tooltip: { trigger: 'item', formatter: '{b}: {d}%<br/>Count: {c}' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: Object.entries(stats.class_distribution).map(([k, v]) => ({
        name: k, value: v,
      })),
      label: { formatter: '{b}: {d}%', color: '#c0caf5' },
      itemStyle: {
        borderColor: '#1a1b26',
        borderWidth: 2,
      },
    }],
    color: ['#f7768e', '#7aa2f7', '#9ece6a'],
  } : null);

  let scoreChartOption = null; // replaced by heatmap table

  function buildHeatmap(stats) {
    const dist = stats?.score_distribution;
    if (!dist?.length) return null;
    const total = dist.reduce((s, d) => s + d.count, 0);
    if (total === 0) return null;
    const xVals = [...new Set(dist.map(d => d.away_x))].sort((a, b) => a - b);
    const oVals = [...new Set(dist.map(d => d.away_o))].sort((a, b) => a - b);
    const lookup = new Map(dist.map(d => [`${d.away_x}:${d.away_o}`, d]));
    const maxCount = Math.max(...dist.map(d => d.count));
    return { xVals, oVals, lookup, total, maxCount };
  }

  function cellStyle(entry, maxCount) {
    if (!entry) return '';
    const t = entry.count / maxCount;
    return `background:rgba(122,162,247,${(0.08 + t * 0.72).toFixed(3)})`;
  }

  let heatmap = $derived(buildHeatmap(stats));

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
    {#if heatmap}
      <div class="card heatmap-card">
        <h2>Score Distribution</h2>
        <p class="hm-subtitle">% of positions (count) — rows: away X ↓, columns: away O →</p>
        <div class="heatmap-wrap">
          <table class="heatmap">
            <thead>
              <tr>
                <th class="corner">X \ O</th>
                {#each heatmap.oVals as o}
                  <th class="col-hdr">{o}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each heatmap.xVals as x}
                <tr>
                  <th class="row-hdr">{x}</th>
                  {#each heatmap.oVals as o}
                    {@const entry = heatmap.lookup.get(`${x}:${o}`)}
                    <td style={cellStyle(entry, heatmap.maxCount)}
                        title="away X={x}, away O={o}: {entry?.count ?? 0} positions">
                      {#if entry}
                        <span class="pct">{(entry.count / heatmap.total * 100).toFixed(1)}%</span>
                        <span class="cnt">({formatNumber(entry.count)})</span>
                      {/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
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

<style>
  .heatmap-card {
    overflow: hidden;
  }

  .hm-subtitle {
    font-size: 12px;
    color: var(--text-muted);
    margin: 0 0 10px;
  }

  .heatmap-wrap {
    overflow-x: auto;
  }

  .heatmap {
    border-collapse: collapse;
    font-size: 11px;
    font-family: var(--mono);
    white-space: nowrap;
  }

  .heatmap .corner {
    background: var(--bg);
    color: var(--text-muted);
    font-weight: 600;
    font-size: 10px;
    padding: 4px 8px;
    text-align: center;
    border: 1px solid var(--border);
    min-width: 44px;
  }

  .heatmap .col-hdr,
  .heatmap .row-hdr {
    background: var(--bg);
    color: var(--accent);
    font-weight: 700;
    padding: 4px 6px;
    text-align: center;
    border: 1px solid var(--border);
    min-width: 44px;
  }

  .heatmap td {
    padding: 3px 6px;
    border: 1px solid var(--border);
    text-align: center;
    min-width: 72px;
    vertical-align: top;
    cursor: default;
  }

  .heatmap td .pct {
    display: block;
    font-weight: 700;
    color: var(--text);
    font-size: 11px;
  }

  .heatmap td .cnt {
    display: block;
    color: var(--text-muted);
    font-size: 10px;
  }
</style>
