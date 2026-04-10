<!-- Explorer — filter positions, inspect on board -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Position } from '$lib/api';
  import Board from '$lib/../../components/Board.svelte';

  // Filters
  let player        = $state('');
  let tournament    = $state('');
  let away_p1       = $state('');
  let away_p2       = $state('');
  let phase         = $state('');
  let decision_type = $state('');
  let error_min     = $state(0);
  let error_max     = $state(2);
  let blunders_only = $state(false);
  let page_num      = $state(0);

  let positions  = $state<Position[]>([]);
  let selected   = $state<Position | null>(null);
  let detail     = $state<{ position: Position; cluster: unknown } | null>(null);
  let loading    = $state(false);
  let err        = $state('');

  const LIMIT = 50;

  async function search(reset = true) {
    if (reset) page_num = 0;
    loading = true; err = '';
    try {
      const p: Record<string, unknown> = {
        limit: LIMIT, offset: page_num * LIMIT,
        error_min, error_max,
      };
      if (player)        p.player        = player;
      if (tournament)    p.tournament    = tournament;
      if (away_p1)       p.away_p1       = Number(away_p1);
      if (away_p2)       p.away_p2       = Number(away_p2);
      if (phase)         p.phase         = phase;
      if (decision_type) p.decision_type = decision_type;
      if (blunders_only) p.blunders_only = true;
      const res = await api.positions.search(p);
      positions = res.positions;
    } catch(e) { err = String(e); }
    finally { loading = false; }
  }

  async function openDetail(pos: Position) {
    selected = pos;
    detail   = null;
    try {
      detail = await api.positions.detail(`${pos.match_id}_${pos.move_number}`);
    } catch {}
  }

  const phaseLabel = (p: number) => ['Contact', 'Race', 'Bearoff'][p] ?? p;
  const errColor   = (e: number) => e >= 0.08 ? '#ff6060' : e >= 0.01 ? '#f0c060' : '#60c060';

  onMount(() => search());
</script>

<svelte:head><title>Explorer — GBF</title></svelte:head>

<div class="layout">
  <!-- Filters -->
  <aside>
    <h2>Filters</h2>
    <label>Player <input bind:value={player} placeholder="name…" /></label>
    <label>Tournament <input bind:value={tournament} placeholder="name…" /></label>
    <label>Away P1 <input bind:value={away_p1} type="number" min="1" max="25" placeholder="1–25" /></label>
    <label>Away P2 <input bind:value={away_p2} type="number" min="1" max="25" placeholder="1–25" /></label>
    <label>Phase
      <select bind:value={phase}>
        <option value="">All</option>
        <option value="contact">Contact</option>
        <option value="race">Race</option>
        <option value="bearoff">Bearoff</option>
      </select>
    </label>
    <label>Decision
      <select bind:value={decision_type}>
        <option value="">All</option>
        <option value="checker">Checker</option>
        <option value="cube">Cube</option>
      </select>
    </label>
    <label>Error min <input bind:value={error_min} type="number" step="0.01" min="0" max="2" /></label>
    <label>Error max <input bind:value={error_max} type="number" step="0.01" min="0" max="2" /></label>
    <label class="check"><input type="checkbox" bind:checked={blunders_only} /> Blunders only (≥ 0.08)</label>
    <button onclick={() => search()}>Search</button>
    <button class="sec" onclick={() => { player=''; tournament=''; away_p1=''; away_p2=''; phase=''; decision_type=''; error_min=0; error_max=2; blunders_only=false; search(); }}>Reset</button>
  </aside>

  <!-- Results -->
  <section>
    {#if err}<p class="err">{err}</p>{/if}
    {#if loading}<p class="loading">Loading…</p>{/if}

    <table>
      <thead>
        <tr><th>Player</th><th>Score</th><th>Phase</th><th>Type</th><th>Error</th><th>Equity</th></tr>
      </thead>
      <tbody>
        {#each positions as pos}
          <tr onclick={() => openDetail(pos)} class:active={selected === pos}>
            <td>{pos.player_name}</td>
            <td>{pos.away_p1}×{pos.away_p2}</td>
            <td>{phaseLabel(pos.match_phase)}</td>
            <td>{pos.decision_type}</td>
            <td style="color:{errColor(pos.move_played_error)}">{pos.move_played_error.toFixed(4)}</td>
            <td>{pos.eval_equity?.toFixed(3) ?? '–'}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    <div class="pagination">
      <button disabled={page_num === 0} onclick={() => { page_num--; search(false); }}>← Prev</button>
      <span>Page {page_num + 1}</span>
      <button disabled={positions.length < LIMIT} onclick={() => { page_num++; search(false); }}>Next →</button>
    </div>
  </section>

  <!-- Detail panel -->
  {#if selected}
  <aside class="detail">
    <h3>Position detail</h3>
    <p><strong>{selected.player_name}</strong> — {selected.away_p1}×{selected.away_p2} ({phaseLabel(selected.match_phase)})</p>
    <p>Error: <span style="color:{errColor(selected.move_played_error)}">{selected.move_played_error.toFixed(4)}</span>
       &nbsp;|&nbsp; Equity: {selected.eval_equity?.toFixed(3) ?? '–'}</p>
    {#if detail?.cluster}
      <p>Cluster: <strong>{(detail.cluster as Record<string,unknown>)?.archetype_label ?? detail.cluster}</strong></p>
    {/if}
    <div class="board-wrap">
      <Board board={Array(26).fill(0)} away_p1={selected.away_p1} away_p2={selected.away_p2} />
    </div>
    <p class="note">Board data not available in this view (requires full position record).</p>
    <a href={`/player/${encodeURIComponent(selected.player_name)}`}>→ Player profile</a>
  </aside>
  {/if}
</div>

<style>
  .layout { display: grid; grid-template-columns: 220px 1fr 280px; gap: 1.5rem; }
  aside { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  aside h2 { margin: 0 0 1rem; color: #d4a835; font-size: 1rem; }
  label { display: flex; flex-direction: column; font-size: 0.8rem; color: #907060; margin-bottom: 0.6rem; gap: 0.2rem; }
  label.check { flex-direction: row; align-items: center; gap: 0.4rem; }
  input, select { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.5rem; font-size: 0.85rem; }
  button { width: 100%; padding: 0.5rem; border: none; border-radius: 4px; background: #c47a20; color: #fff; cursor: pointer; margin-top: 0.4rem; }
  button.sec { background: #2a1a08; border: 1px solid #3a2010; color: #907060; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { text-align: left; border-bottom: 1px solid #3a2010; color: #907060; padding: 0.4rem 0.6rem; }
  td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #1e1208; }
  tr:hover td, tr.active td { background: #1e1208; cursor: pointer; }
  .pagination { display: flex; align-items: center; gap: 1rem; margin-top: 1rem; }
  .pagination button { width: auto; padding: 0.3rem 0.8rem; }
  .pagination span { color: #907060; font-size: 0.85rem; }
  .err { color: #ff6060; } .loading { color: #907060; font-style: italic; }
  .detail h3 { color: #d4a835; margin: 0 0 0.8rem; }
  .detail p { font-size: 0.85rem; margin: 0.3rem 0; }
  .board-wrap { margin: 1rem 0; }
  .note { font-size: 0.75rem; color: #605040; font-style: italic; }
  .detail a { color: #d4a835; font-size: 0.85rem; }
</style>
