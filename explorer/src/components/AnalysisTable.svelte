<script>
  /**
   * Analysis table for checker play and cube decisions.
   * Props: checkerAnalysis, cubeAnalysis (from position detail API)
   */
  let { checkerAnalysis = null, cubeAnalysis = null } = $props();

  let defaultTab = $derived(checkerAnalysis ? 'checker' : (cubeAnalysis ? 'cube' : 'checker'));
  let userTab = $state(null);
  let tab = $derived(userTab ?? defaultTab);
  function setTab(t) { userTab = t; }

  function fmt(v, digits = 1) {
    if (v == null) return '—';
    return (v * 100).toFixed(digits);
  }
  function fmtEq(v) {
    if (v == null) return '—';
    return v >= 0 ? `+${v.toFixed(4)}` : v.toFixed(4);
  }
  function fmtDiff(v) {
    if (v == null || v === 0) return '';
    return `-${Math.abs(v).toFixed(4)}`;
  }

  const cubeActionLabels = ['No Double', 'Double / Take', 'Double / Pass'];
</script>

<div class="analysis-panel">
  {#if checkerAnalysis || cubeAnalysis}
    <div class="tabs">
      {#if checkerAnalysis}
        <button class:active={tab === 'checker'} onclick={() => setTab('checker')}>
          Checker ({checkerAnalysis.move_count})
        </button>
      {/if}
      {#if cubeAnalysis}
        <button class:active={tab === 'cube'} onclick={() => setTab('cube')}>
          Cube
        </button>
      {/if}
    </div>

    {#if tab === 'checker' && checkerAnalysis}
      <div class="table-scroll">
        <table class="analysis-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Move</th>
              <th>Equity</th>
              <th>Diff</th>
              <th>W%</th>
              <th>G%</th>
              <th>BG%</th>
              <th class="opp">W%</th>
              <th class="opp">G%</th>
              <th class="opp">BG%</th>
              <th>Ply</th>
            </tr>
          </thead>
          <tbody>
            {#each checkerAnalysis.moves as m, i}
              <tr class:best={i === 0}>
                <td class="rank">{m.rank}</td>
                <td class="move">{m.move}</td>
                <td class="eq">{fmtEq(m.equity)}</td>
                <td class="diff">{fmtDiff(m.equity_diff)}</td>
                <td>{fmt(m.win)}</td>
                <td>{fmt(m.gammon)}</td>
                <td>{fmt(m.bg)}</td>
                <td class="opp">{fmt(m.opp_win)}</td>
                <td class="opp">{fmt(m.opp_gammon)}</td>
                <td class="opp">{fmt(m.opp_bg)}</td>
                <td class="ply">{m.ply}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    {#if tab === 'cube' && cubeAnalysis}
      <div class="cube-grid">
        <div class="cube-section">
          <h4>Win Probabilities</h4>
          <table class="analysis-table compact">
            <thead><tr><th></th><th>Player</th><th>Opponent</th></tr></thead>
            <tbody>
              <tr><td>Win</td><td>{fmt(cubeAnalysis.win)}</td><td>{fmt(cubeAnalysis.opp_win)}</td></tr>
              <tr><td>Gammon</td><td>{fmt(cubeAnalysis.gammon)}</td><td>{fmt(cubeAnalysis.opp_gammon)}</td></tr>
              <tr><td>BG</td><td>{fmt(cubeAnalysis.bg)}</td><td>{fmt(cubeAnalysis.opp_bg)}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="cube-section">
          <h4>Equities</h4>
          <table class="analysis-table compact">
            <tbody>
              <tr><td>Cubeless ND</td><td>{fmtEq(cubeAnalysis.cubeless_nd)}</td></tr>
              <tr><td>Cubeless D</td><td>{fmtEq(cubeAnalysis.cubeless_d)}</td></tr>
              <tr><td>Cubeful ND</td><td>{fmtEq(cubeAnalysis.cubeful_nd)}</td></tr>
              <tr><td>Cubeful D/T</td><td>{fmtEq(cubeAnalysis.cubeful_dt)}</td></tr>
              <tr><td>Cubeful D/P</td><td>{fmtEq(cubeAnalysis.cubeful_dp)}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="cube-action">
          Best: <strong>{cubeAnalysis.best_label}</strong>
        </div>
      </div>
    {/if}
  {:else}
    <p class="no-data">No analysis data</p>
  {/if}
</div>

<style>
  .analysis-panel {
    font-size: 12px;
  }
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 6px;
  }
  .tabs button {
    padding: 3px 10px;
    border: 1px solid var(--border);
    border-radius: 4px 4px 0 0;
    background: var(--bg);
    color: var(--text-muted);
    cursor: pointer;
    font-size: 11px;
  }
  .tabs button.active {
    background: var(--card-bg);
    color: var(--text);
    border-bottom-color: transparent;
  }
  .table-scroll {
    overflow-x: auto;
    max-height: 260px;
    overflow-y: auto;
  }
  .analysis-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    font-family: var(--mono);
    white-space: nowrap;
  }
  .analysis-table th,
  .analysis-table td {
    padding: 2px 5px;
    text-align: right;
    border-bottom: 1px solid var(--border);
  }
  .analysis-table th {
    color: var(--text-muted);
    font-weight: normal;
    position: sticky;
    top: 0;
    background: var(--card-bg);
    z-index: 1;
  }
  .analysis-table td.move {
    text-align: left;
    color: var(--text);
    font-weight: 500;
  }
  .analysis-table td.rank {
    color: var(--text-muted);
    text-align: center;
  }
  .analysis-table td.eq {
    color: var(--text);
  }
  .analysis-table td.diff {
    color: var(--red, #f7768e);
  }
  .analysis-table td.ply {
    color: var(--text-muted);
    text-align: center;
  }
  .analysis-table .opp {
    color: var(--text-muted);
  }
  tr.best td {
    background: rgba(122, 162, 247, 0.08);
  }
  tr.best td.move {
    color: #7aa2f7;
  }
  .compact {
    font-size: 11px;
  }
  .compact td:first-child {
    text-align: left;
    color: var(--text-muted);
  }
  .cube-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .cube-section h4 {
    margin: 0 0 4px;
    font-size: 11px;
    color: var(--text-muted);
  }
  .cube-action {
    padding: 6px 8px;
    background: rgba(224, 175, 104, 0.1);
    border: 1px solid #e0af68;
    border-radius: 4px;
    color: #e0af68;
    font-size: 12px;
    text-align: center;
  }
  .no-data {
    color: var(--text-muted);
    font-style: italic;
    font-size: 11px;
    margin: 8px 0;
  }
</style>
