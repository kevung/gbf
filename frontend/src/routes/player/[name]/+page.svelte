<!-- Player Profile page -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api, type PlayerProfile } from '$lib/api';
  import RadarChart from '$lib/../../components/RadarChart.svelte';

  let name       = $derived(decodeURIComponent($page.params.name));
  let profile    = $state<PlayerProfile | null>(null);
  let compare    = $state<PlayerProfile | null>(null);
  let compareQ   = $state('');
  let strengths  = $state<unknown[]>([]);
  let loading    = $state(false);
  let err        = $state('');

  async function load(n: string) {
    loading = true; err = '';
    try {
      profile   = await api.players.profile(n);
      const sw  = await api.players.positions(n, { limit: 1 }); // just to warm cache
      void sw;
    } catch(e) { err = String(e); }
    finally { loading = false; }
  }

  async function loadCompare() {
    if (!compareQ) { compare = null; return; }
    try { compare = await api.players.profile(compareQ); }
    catch {}
  }

  $effect(() => { if (name) load(name); });

  const AXES = [
    { key: 'avg_error_checker',  label: 'Checker' },
    { key: 'avg_error_cube',     label: 'Cube' },
    { key: 'blunder_rate',       label: 'Blunders' },
    { key: 'missed_double_rate', label: 'Missed ×2' },
    { key: 'wrong_take_rate',    label: 'Wrong take' },
    { key: 'contact_error',      label: 'Contact' },
    { key: 'race_error',         label: 'Race' },
    { key: 'bearoff_error',      label: 'Bearoff' },
  ];

  let radarData = $derived(
    profile
      ? AXES.map(a => ({
          axis:    a.label,
          value:   (profile as Record<string, unknown>)[a.key] as number ?? 0,
          compare: compare ? (compare as Record<string, unknown>)[a.key] as number ?? 0 : undefined,
        }))
      : []
  );

  function bar(z: number) {
    const w = Math.min(Math.abs(z) * 40, 100);
    const c = z > 1 ? '#ff6060' : z < -1 ? '#60c060' : '#d4a835';
    return { width: `${w}%`, background: c };
  }
  function zLabel(z: number) { return z > 1 ? 'Weakness' : z < -1 ? 'Strength' : 'Average'; }
</script>

<svelte:head><title>{name} — GBF</title></svelte:head>

{#if loading}<p class="loading">Loading…</p>{/if}
{#if err}<p class="err">{err}</p>{/if}

{#if profile}
<div class="header">
  <div>
    <h1>{name}</h1>
    <p class="sub">
      {profile.total_games} games · {profile.total_positions?.toLocaleString()} positions
      {#if profile.archetype_label} · <strong>{profile.archetype_label}</strong>{/if}
    </p>
    {#if profile.pr_rank}
      <p class="rank">PR rank #{profile.pr_rank}
        {#if profile.pr_rating} · Rating {profile.pr_rating?.toFixed(3)}{/if}
      </p>
    {/if}
  </div>
  <div class="compare-ctrl">
    <label>Compare with
      <input bind:value={compareQ} placeholder="player name…" />
    </label>
    <button onclick={loadCompare}>Load</button>
    {#if compare}<button onclick={() => compare = null}>Clear</button>{/if}
  </div>
</div>

<div class="layout">
  <div class="radar-wrap">
    <h2>Profile radar</h2>
    <RadarChart data={radarData} maxVal={0.15} size={260} />
    {#if compare}
      <div class="legend">
        <span class="dot gold"></span> {name}
        <span class="dot blue"></span> {compareQ}
      </div>
    {/if}
  </div>

  <div>
    <h2>Key metrics</h2>
    <table class="mt">
      <thead><tr><th>Metric</th><th>{name}</th>{#if compare}<th>{compareQ}</th>{/if}</tr></thead>
      <tbody>
        {#each AXES as a}
          <tr>
            <td>{a.label}</td>
            <td>{((profile as Record<string,unknown>)[a.key] as number)?.toFixed(4) ?? '–'}</td>
            {#if compare}
              <td>{((compare as Record<string,unknown>)[a.key] as number)?.toFixed(4) ?? '–'}</td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
{/if}

<style>
  h1 { color: #f0c060; margin-bottom: 0.2rem; }
  .sub { color: #907060; font-size: 0.9rem; margin: 0; }
  .rank { color: #d4a835; font-size: 0.85rem; margin: 0.2rem 0 0; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
  .compare-ctrl { display: flex; flex-direction: column; gap: 0.4rem; }
  .compare-ctrl label { font-size: 0.8rem; color: #907060; }
  .compare-ctrl input { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.5rem; }
  .compare-ctrl button { padding: 0.3rem 0.8rem; background: #c47a20; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
  h2 { color: #d4a835; font-size: 1rem; margin-bottom: 0.8rem; }
  .layout { display: grid; grid-template-columns: 280px 1fr; gap: 2rem; align-items: start; }
  .radar-wrap { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  .legend { display: flex; gap: 1rem; font-size: 0.8rem; margin-top: 0.5rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 4px; }
  .dot.gold { background: #d4a835; } .dot.blue { background: #4040c0; }
  .mt { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  .mt th { color: #907060; text-align: left; padding: 0.3rem 0.6rem; border-bottom: 1px solid #3a2010; }
  .mt td { padding: 0.3rem 0.6rem; border-bottom: 1px solid #1e1208; }
  .err { color: #ff6060; } .loading { color: #907060; font-style: italic; }
</style>
