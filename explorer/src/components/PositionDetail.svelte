<script>
  /**
   * Composite position detail panel: board + info + analysis + metadata.
   * Props: position (full position detail response from API)
   */
  import Board from './Board.svelte';
  import AnalysisTable from './AnalysisTable.svelte';

  let { position = null } = $props();

  const classLabels = { 0: 'Contact', 1: 'Race', 2: 'Bearoff' };
  const cubeOwnerLabels = { 0: 'Center', 1: 'X', 2: 'O' };
</script>

{#if position}
  <div class="position-detail">
    <!-- Board -->
    <div class="board-area">
      <Board
        board={position.board}
        barX={position.bar_x}
        barO={position.bar_o}
        borneOffX={position.borne_off_x}
        borneOffO={position.borne_off_o}
        cubeLog2={position.cube_log2}
        cubeOwner={position.cube_owner}
        awayX={position.away_x}
        awayO={position.away_o}
        sideToMove={position.side_to_move}
      />
    </div>

    <!-- Info bar -->
    <div class="info-bar">
      <span class="tag class-{position.pos_class}">{classLabels[position.pos_class] || '?'}</span>
      <span class="info-item" title="Pip count">Pip: {position.pip_x}/{position.pip_o}</span>
      <span class="info-item" title="Score (away)">Score: {position.away_x}-{position.away_o}</span>
      <span class="info-item" title="Cube">Cube: {1 << position.cube_log2} ({cubeOwnerLabels[position.cube_owner]})</span>
      {#if position.bar_x > 0 || position.bar_o > 0}
        <span class="info-item">Bar: {position.bar_x}/{position.bar_o}</span>
      {/if}
      {#if position.borne_off_x > 0 || position.borne_off_o > 0}
        <span class="info-item">Off: {position.borne_off_x}/{position.borne_off_o}</span>
      {/if}
    </div>

    <!-- Occurrence counts -->
    <div class="occurrences">
      <span title="Times this exact position (board+cube+score) appeared">
        Exact: <strong>{position.exact_count}</strong>
      </span>
      <span title="Times this board appeared with any cube/score">
        Board: <strong>{position.board_count}</strong>
      </span>
      <span class="pos-id">#{position.id}</span>
    </div>

    <!-- Analysis -->
    <div class="analysis-area">
      <AnalysisTable
        checkerAnalysis={position.checker_analysis}
        cubeAnalysis={position.cube_analysis}
      />
    </div>

    <!-- Match metadata -->
    {#if position.matches?.length > 0}
      <details class="matches-section">
        <summary>Matches ({position.matches.length})</summary>
        <div class="matches-scroll">
          <table class="matches-table">
            <thead>
              <tr><th>Players</th><th>Len</th><th>Event</th><th>Date</th></tr>
            </thead>
            <tbody>
              {#each position.matches as m}
                <tr>
                  <td>{m.player1} vs {m.player2}</td>
                  <td>{m.match_length || '—'}</td>
                  <td>{m.event || '—'}</td>
                  <td>{m.date || '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </details>
    {/if}
  </div>
{:else}
  <div class="empty-panel">
    <p>Click a point on the chart to view position details</p>
  </div>
{/if}

<style>
  .position-detail {
    display: flex;
    flex-direction: column;
    gap: 8px;
    height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .board-area {
    flex-shrink: 0;
  }
  .info-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    font-size: 11px;
    color: var(--text-muted);
  }
  .info-item {
    padding: 1px 6px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 3px;
  }
  .tag {
    padding: 1px 8px;
    border-radius: 3px;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
  }
  .tag.class-0 { background: rgba(247, 118, 142, 0.15); color: #f7768e; }
  .tag.class-1 { background: rgba(122, 162, 247, 0.15); color: #7aa2f7; }
  .tag.class-2 { background: rgba(158, 206, 106, 0.15); color: #9ece6a; }
  .occurrences {
    display: flex;
    gap: 12px;
    font-size: 11px;
    color: var(--text-muted);
  }
  .occurrences strong {
    color: var(--text);
  }
  .pos-id {
    margin-left: auto;
    color: var(--text-muted);
    font-family: var(--mono);
    font-size: 10px;
  }
  .analysis-area {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
  .matches-section {
    font-size: 11px;
    border-top: 1px solid var(--border);
    padding-top: 6px;
  }
  .matches-section summary {
    cursor: pointer;
    color: var(--text-muted);
    margin-bottom: 4px;
  }
  .matches-scroll {
    max-height: 120px;
    overflow-y: auto;
  }
  .matches-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 10px;
    font-family: var(--mono);
  }
  .matches-table th, .matches-table td {
    padding: 2px 4px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  .matches-table th {
    color: var(--text-muted);
    font-weight: normal;
  }
  .empty-panel {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    color: var(--text-muted);
    font-size: 13px;
    font-style: italic;
  }
</style>
