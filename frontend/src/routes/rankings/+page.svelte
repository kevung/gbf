<!-- Rankings page -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Ranking } from '$lib/api';

  const METRICS = [
    ['pr',          'Overall PR'],
    ['checker',     'Checker'],
    ['cube',        'Cube'],
    ['contact',     'Contact'],
    ['race',        'Race'],
    ['bearoff',     'Bearoff'],
    ['gammon',      'Gammon'],
    ['consistency', 'Consistency'],
  ] as const;

  let metric    = $state('pr');
  let search    = $state('');
  let offset    = $state(0);
  let rankings  = $state<Ranking[]>([]);
  let overunder = $state<unknown[]>([]);
  let loading   = $state(false);
  let err       = $state('');

  const LIMIT = 50;

  async function load(reset = true) {
    if (reset) offset = 0;
    loading = true; err = '';
    try {
      const res = await api.stats.rankings({ metric, search: search || undefined, limit: LIMIT, offset });
      rankings = res.rankings;
    } catch(e) { err = String(e); }
    finally { loading = false; }
  }

  async function loadOverUnder() {
    try { overunder = (await api.stats.overUnder()).performers; }
    catch {}
  }

  onMount(() => { load(); loadOverUnder(); });

  const errColor = (e: number) => e >= 0.08 ? '#ff6060' : e >= 0.01 ? '#f0c060' : '#60c060';
</script>

<svelte:head><title>Rankings — GBF</title></svelte:head>

<h1>Player Rankings</h1>

<div class="controls">
  <div class="tabs">
    {#each METRICS as [val, lbl]}
      <button class:active={metric === val} onclick={() => { metric = val; load(); }}>{lbl}</button>
    {/each}
  </div>
  <div class="search-row">
    <input bind:value={search} placeholder="Search player…" oninput={() => load()} />
  </div>
</div>

{#if err}<p class="err">{err}</p>{/if}
{#if loading}<p class="loading">Loading…</p>{/if}

<table>
  <thead>
    <tr>
      <th>#</th><th>Player</th><th>Rating</th><th>PR</th><th>Games</th><th>Blunder%</th>
    </tr>
  </thead>
  <tbody>
    {#each rankings as r, i}
      <tr>
        <td class="rank">{offset + i + 1}</td>
        <td><a href="/player/{encodeURIComponent(r.player_name)}">{r.player_name}</a></td>
        <td>{r.rating?.toFixed(3) ?? '–'}</td>
        <td>{r.pr_rating?.toFixed(3) ?? '–'}</td>
        <td>{r.total_games}</td>
        <td style="color:{errColor(r.blunder_rate)}">{(r.blunder_rate*100)?.toFixed(1)}%</td>
      </tr>
    {/each}
  </tbody>
</table>

<div class="pagination">
  <button disabled={offset === 0} onclick={() => { offset -= LIMIT; load(false); }}>← Prev</button>
  <span>{offset + 1}–{offset + rankings.length}</span>
  <button disabled={rankings.length < LIMIT} onclick={() => { offset += LIMIT; load(false); }}>Next →</button>
</div>

{#if overunder.length}
<h2>Over / Under-performers</h2>
<table>
  <thead><tr><th>Player</th><th>Predicted PR</th><th>Actual PR</th><th>Δ</th><th></th></tr></thead>
  <tbody>
    {#each overunder as p: any}
      <tr>
        <td><a href="/player/{encodeURIComponent(p.player_name)}">{p.player_name}</a></td>
        <td>{parseFloat(p.predicted_pr)?.toFixed(3)}</td>
        <td>{parseFloat(p.actual_pr)?.toFixed(3)}</td>
        <td style="color:{parseFloat(p.delta) < 0 ? '#60c060' : '#ff6060'}">{parseFloat(p.delta)?.toFixed(3)}</td>
        <td>{parseFloat(p.delta) < 0 ? '↑ Over' : '↓ Under'}</td>
      </tr>
    {/each}
  </tbody>
</table>
{/if}

<style>
  h1 { color: #f0c060; margin-bottom: 1rem; }
  h2 { color: #d4a835; margin: 2rem 0 0.8rem; }
  .controls { display: flex; flex-direction: column; gap: 0.8rem; margin-bottom: 1.5rem; }
  .tabs { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .tabs button { padding: 0.3rem 0.7rem; background: #1a0f07; border: 1px solid #3a2010; border-radius: 4px;
                 color: #907060; cursor: pointer; font-size: 0.82rem; }
  .tabs button.active { background: #3a2010; color: #f0c060; border-color: #d4a835; }
  .search-row input { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.6rem; width: 240px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom: 1rem; }
  th { color: #907060; text-align: left; border-bottom: 1px solid #3a2010; padding: 0.4rem 0.6rem; }
  td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #1e1208; }
  td a { color: #d4a835; text-decoration: none; }
  .rank { color: #605040; }
  .pagination { display: flex; align-items: center; gap: 1rem; }
  .pagination button { padding: 0.3rem 0.8rem; background: #1a0f07; border: 1px solid #3a2010; border-radius: 4px; color: #907060; cursor: pointer; }
  .pagination button:disabled { opacity: 0.4; cursor: default; }
  .pagination span { color: #605040; font-size: 0.85rem; }
  .err { color: #ff6060; } .loading { color: #907060; font-style: italic; }
</style>
