<!-- Home — key statistics and navigation hub -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Overview } from '$lib/api';

  let overview = $state<Overview>({});
  let error    = $state('');

  onMount(async () => {
    try { overview = await api.stats.overview(); }
    catch (e) { error = String(e); }
  });

  const views = [
    { href: '/explorer',  icon: '🔍', title: 'Explorer',     desc: 'Browse 160M positions with filters' },
    { href: '/heatmap',   icon: '🟥', title: 'Cube Heatmap', desc: 'Error rates by score combination' },
    { href: '/rankings',  icon: '🏆', title: 'Rankings',     desc: 'Player PR ratings & dimensions' },
    { href: '/catalogue', icon: '📂', title: 'Catalogue',    desc: 'Positions by cluster & trap type' },
    { href: '/cube',      icon: '🎲', title: 'Cube Helper',  desc: 'Threshold table & equity calculator' },
    { href: '/map',       icon: '🗺️', title: 'Position Map', desc: 'UMAP trajectory explorer' },
  ];

  function fmt(n: number | undefined, dec = 4) {
    return n == null ? '–' : n.toFixed(dec);
  }
  function fmtInt(n: number | undefined) {
    return n == null ? '–' : n.toLocaleString();
  }
</script>

<svelte:head><title>GBF Dashboard</title></svelte:head>

<h1>GBF Dashboard</h1>
<p class="sub">Backgammon position mining — {fmtInt(overview.total_positions as number)} positions analysed</p>

{#if error}<p class="err">{error}</p>{/if}

<div class="cards">
  <div class="card">
    <div class="val">{fmtInt(overview.total_positions as number)}</div>
    <div class="lbl">Total positions</div>
  </div>
  <div class="card">
    <div class="val">{fmt(overview.avg_error as number)}</div>
    <div class="lbl">Avg error</div>
  </div>
  <div class="card">
    <div class="val">{fmt((overview.blunder_rate as number) * 100, 1)}%</div>
    <div class="lbl">Blunder rate</div>
  </div>
  {#if overview.total_matches}
  <div class="card">
    <div class="val">{fmtInt(overview.total_matches as number)}</div>
    <div class="lbl">Matches</div>
  </div>
  {/if}
</div>

<h2>Views</h2>
<div class="grid">
  {#each views as v}
    <a href={v.href} class="tile">
      <span class="icon">{v.icon}</span>
      <strong>{v.title}</strong>
      <span class="desc">{v.desc}</span>
    </a>
  {/each}
</div>

<style>
  h1 { margin: 0 0 0.3rem; font-size: 1.8rem; color: #f0c060; }
  .sub { color: #907060; margin-bottom: 1.5rem; }
  .err { color: #ff6060; }
  .cards { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; }
  .card { background: #1e1208; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem 1.5rem; min-width: 140px; }
  .val { font-size: 1.6rem; font-weight: bold; color: #f0c060; }
  .lbl { font-size: 0.8rem; color: #907060; margin-top: 0.2rem; }
  h2 { color: #d4a835; margin-bottom: 1rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
  .tile { display: flex; flex-direction: column; gap: 0.3rem; background: #1a0f07; border: 1px solid #3a2010;
          border-radius: 8px; padding: 1.2rem; text-decoration: none; color: inherit;
          transition: border-color 0.15s; }
  .tile:hover { border-color: #d4a835; }
  .icon { font-size: 1.4rem; }
  .tile strong { color: #e0c080; }
  .desc { font-size: 0.8rem; color: #907060; }
</style>
