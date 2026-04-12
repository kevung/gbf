<script>
  /**
   * Themes view — browse positions by thematic classification (S1.9).
   * Shows theme frequency chart, lets user select a theme, and displays
   * a grid of sample board positions for that theme.
   */
  import { fetchThemeStats, fetchThemePositions } from '../lib/api.js';
  import Chart from '../components/Chart.svelte';
  import Board from '../components/Board.svelte';

  let { active = false } = $props();

  let stats = $state([]);         // [{theme, count, proportion}]
  let statsLoading = $state(false);
  let statsError = $state(null);

  let selectedTheme = $state('');
  let positions = $state([]);     // [{board, bar_x, bar_o, ...}]
  let posLoading = $state(false);
  let posError = $state(null);
  let posLoadingMsg = $state('');

  // Detail overlay
  let detail = $state(null);

  // Theme display names (snake_case → Title Case)
  function themeLabel(t) {
    return t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  // Theme group colours (for bar chart + cards)
  const THEME_COLORS = {
    opening:              '#9ece6a',
    flexibility:          '#73daca',
    middle_game:          '#7aa2f7',
    '5_point':            '#7aa2f7',
    blitz:                '#f7768e',
    one_man_back:         '#bb9af7',
    holding:              '#7dcfff',
    priming:              '#7aa2f7',
    connectivity:         '#7dcfff',
    hit_or_not:           '#e0af68',
    crunch:               '#f7768e',
    late_blitz:           '#f7768e',
    containment:          '#bb9af7',
    playing_gammon:       '#9ece6a',
    saving_gammon:        '#73daca',
    action_doubles:       '#e0af68',
    too_good:             '#e0af68',
    ace_point:            '#bb9af7',
    back_game:            '#bb9af7',
    breaking_anchor:      '#ff9e64',
    post_blitz_turnaround:'#ff9e64',
    post_ace_point:       '#ff9e64',
    bearoff_vs_contact:   '#9ece6a',
    various_endgames:     '#73daca',
    race:                 '#7aa2f7',
    bearoff:              '#9ece6a',
  };

  function themeColor(t) {
    return THEME_COLORS[t] || '#7aa2f7';
  }

  // ECharts option for the frequency bar chart
  let chartOption = $derived.by(() => {
    if (!stats.length) return null;
    const sorted = [...stats].sort((a, b) => b.count - a.count);
    return {
      backgroundColor: 'transparent',
      title: {
        text: 'Theme Distribution',
        left: 'center',
        textStyle: { color: '#c0caf5', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const d = params[0];
          const row = sorted[d.dataIndex];
          return `${themeLabel(row.theme)}<br/>
            Count: ${row.count.toLocaleString()}<br/>
            ${(row.proportion * 100).toFixed(1)}% of positions`;
        },
      },
      xAxis: {
        type: 'category',
        data: sorted.map(r => themeLabel(r.theme)),
        axisLabel: {
          color: '#565f89',
          fontSize: 10,
          rotate: 45,
          interval: 0,
        },
        axisLine: { lineStyle: { color: '#3b4261' } },
      },
      yAxis: {
        type: 'value',
        name: 'Positions',
        nameTextStyle: { color: '#c0caf5', fontSize: 10 },
        axisLabel: {
          color: '#565f89',
          formatter: v => v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? (v / 1e3).toFixed(0) + 'K' : v,
        },
        splitLine: { lineStyle: { color: '#3b4261' } },
      },
      series: [{
        type: 'bar',
        data: sorted.map(r => ({
          value: r.count,
          itemStyle: { color: themeColor(r.theme) },
        })),
      }],
      grid: { left: 60, right: 20, bottom: 120, top: 50 },
    };
  });

  // Reload stats whenever the tab becomes active (handles the case where the
  // data directory is configured after this component was first mounted).
  $effect(() => {
    if (active && stats.length === 0 && !statsLoading) {
      loadStats();
    }
  });

  async function loadStats() {
    statsLoading = true;
    statsError = null;
    try {
      stats = await fetchThemeStats();
      if (stats.length > 0 && !selectedTheme) {
        selectedTheme = stats[0].theme;
      }
    } catch (e) {
      statsError = e.message;
    }
    statsLoading = false;
  }

  async function loadPositions() {
    if (!selectedTheme) return;
    posLoading = true;
    posError = null;
    posLoadingMsg = 'Sampling positions from Parquet dataset…';
    positions = [];
    detail = null;
    try {
      positions = await fetchThemePositions(selectedTheme, 24);
      if (!Array.isArray(positions)) {
        posError = positions.error || 'Unexpected response';
        positions = [];
      }
    } catch (e) {
      posError = e.message;
    }
    posLoading = false;
    posLoadingMsg = '';
  }

  // Load positions whenever theme changes
  $effect(() => {
    if (selectedTheme) loadPositions();
  });

  function errorClass(err) {
    if (err >= 0.08) return 'blunder';
    if (err >= 0.02) return 'error';
    return 'ok';
  }

  function winPct(win) {
    return (win * 100).toFixed(0) + '%';
  }
</script>

<div class="themes-layout">

  <!-- Left panel: controls + chart -->
  <div class="left-panel">

    {#if statsLoading}
      <div class="loading">Loading theme statistics…</div>
    {:else if statsError}
      <div class="card" style="border-color:var(--red)">
        <p style="color:var(--red)">{statsError}</p>
        <p style="color:var(--text-muted);font-size:11px">Configure the data directory in Setup first, then retry.</p>
        <button class="btn primary" onclick={loadStats} style="margin-top:6px">Retry</button>
      </div>
    {:else if stats.length === 0}
      <div class="card">
        <p style="color:var(--text-muted)">No theme data. Configure the data directory in Setup.</p>
      </div>
    {:else}
      <div class="chart-wrap">
        <Chart option={chartOption} height="260px" />
      </div>

      <div class="theme-selector">
        <label>
          Theme
          <select bind:value={selectedTheme} onchange={loadPositions}>
            {#each stats as s}
              <option value={s.theme}>
                {themeLabel(s.theme)} — {(s.proportion * 100).toFixed(1)}%
              </option>
            {/each}
          </select>
        </label>
        <button class="btn primary" onclick={loadPositions} disabled={posLoading}>
          {posLoading ? 'Loading…' : 'Refresh sample'}
        </button>
      </div>

      {#if selectedTheme}
        {@const row = stats.find(s => s.theme === selectedTheme)}
        {#if row}
          <div class="theme-info">
            <span class="theme-badge" style="background:{themeColor(selectedTheme)}22;color:{themeColor(selectedTheme)}">
              {themeLabel(selectedTheme)}
            </span>
            <span class="info-item">{row.count.toLocaleString()} positions</span>
            <span class="info-item">{(row.proportion * 100).toFixed(1)}% of dataset</span>
          </div>
        {/if}
      {/if}
    {/if}

    <!-- Position detail panel -->
    {#if detail}
      <div class="detail-card card">
        <h4>{themeLabel(detail.primary_theme || selectedTheme)}</h4>
        <div class="detail-board">
          <Board
            board={detail.board}
            barX={detail.bar_x}
            barO={detail.bar_o}
            borneOffX={detail.borne_off_x}
            borneOffO={detail.borne_off_o}
            cubeLog2={detail.cube_log2}
            cubeOwner={detail.cube_owner}
            awayX={detail.away_x}
            awayO={detail.away_o}
            sideToMove={0}
          />
        </div>
        <div class="detail-meta">
          <span class="info-item">Pip X: {detail.pip_x}</span>
          <span class="info-item">Pip O: {detail.pip_o}</span>
          <span class="info-item">Away: {detail.away_x}–{detail.away_o}</span>
          <span class="info-item">Win: {winPct(detail.eval_win)}</span>
          <span class="info-item {errorClass(detail.error)}">
            Error: {(detail.error * 1000).toFixed(1)} mE
          </span>
          <span class="info-item">{detail.theme_count} theme{detail.theme_count > 1 ? 's' : ''}</span>
        </div>
        <button class="btn" onclick={() => detail = null} style="margin-top:6px;font-size:11px">Close</button>
      </div>
    {/if}

  </div>

  <!-- Right panel: position grid -->
  <div class="right-panel">
    {#if posLoading}
      <div class="loading">{posLoadingMsg || 'Loading positions…'}</div>
    {:else if posError}
      <div class="card" style="border-color:var(--red)">
        <p style="color:var(--red)">Error: {posError}</p>
      </div>
    {:else if positions.length === 0 && selectedTheme}
      <div class="card">
        <p style="color:var(--text-muted)">No positions found for "{themeLabel(selectedTheme)}".</p>
      </div>
    {:else}
      <div class="position-grid">
        {#each positions as pos}
            <div
            class="pos-card"
            class:selected={detail?.position_id === pos.position_id}
            role="button"
            tabindex="0"
            onclick={() => detail = detail?.position_id === pos.position_id ? null : pos}
            onkeydown={(e) => e.key === 'Enter' && (detail = detail?.position_id === pos.position_id ? null : pos)}
          >
            <div class="pos-board">
              <Board
                board={pos.board}
                barX={pos.bar_x}
                barO={pos.bar_o}
                borneOffX={pos.borne_off_x}
                borneOffO={pos.borne_off_o}
                cubeLog2={pos.cube_log2}
                cubeOwner={pos.cube_owner}
                awayX={pos.away_x}
                awayO={pos.away_o}
                sideToMove={0}
              />
            </div>
            <div class="pos-meta">
              {#if pos.primary_theme && pos.primary_theme !== selectedTheme}
                <span class="theme-tag" style="color:{themeColor(pos.primary_theme)}">
                  {themeLabel(pos.primary_theme)}
                </span>
              {/if}
              <span class="meta-item">W: {winPct(pos.eval_win)}</span>
              <span class="meta-item {errorClass(pos.error)}">
                Err: {(pos.error * 1000).toFixed(1)}
              </span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

</div>

<style>
  .themes-layout {
    display: flex;
    gap: 16px;
    height: calc(100vh - 80px);
    min-height: 500px;
    overflow: hidden;
  }

  .left-panel {
    width: 340px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    overflow-y: auto;
  }

  .right-panel {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
  }

  .chart-wrap {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px;
  }

  .theme-selector {
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }

  .theme-selector label {
    flex: 1;
    font-size: 12px;
    color: var(--text-muted);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .theme-selector select {
    width: 100%;
  }

  .theme-info {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    font-size: 11px;
  }

  .theme-badge {
    padding: 2px 10px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 11px;
  }

  .info-item {
    padding: 1px 6px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 11px;
    color: var(--text-muted);
  }

  .detail-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detail-card h4 {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    margin: 0;
  }

  .detail-board {
    max-width: 300px;
  }

  .detail-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  /* Position grid */
  .position-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    padding: 4px;
  }

  .pos-card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px;
    cursor: pointer;
    transition: border-color 0.15s, box-shadow 0.15s;
  }

  .pos-card:hover {
    border-color: var(--blue);
    box-shadow: 0 0 0 1px var(--blue);
  }

  .pos-card.selected {
    border-color: var(--blue);
    box-shadow: 0 0 0 2px var(--blue);
  }

  .pos-board {
    width: 100%;
  }

  .pos-meta {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-top: 4px;
    font-size: 10px;
    color: var(--text-muted);
  }

  .meta-item, .theme-tag {
    padding: 0 4px;
    border-radius: 2px;
    background: var(--bg);
    border: 1px solid var(--border);
  }

  .theme-tag {
    font-weight: 600;
  }

  /* Error coloring */
  .ok    { color: var(--green, #9ece6a); border-color: var(--green, #9ece6a); }
  .error { color: var(--yellow, #e0af68); border-color: var(--yellow, #e0af68); }
  .blunder { color: var(--red, #f7768e); border-color: var(--red, #f7768e); }

  .loading {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
    font-style: italic;
  }
</style>
