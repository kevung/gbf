<!-- Position Catalogue — browse by cluster -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Cluster, type Position } from '$lib/api';

  let clusters    = $state<Cluster[]>([]);
  let selected    = $state<Cluster | null>(null);
  let positions   = $state<Position[]>([]);
  let heuristics  = $state<unknown[]>([]);
  let trapsOnly   = $state(false);
  let loading     = $state(false);
  let err         = $state('');

  const phaseLabel = ['Contact', 'Race', 'Bearoff'];
  const phaseIcon  = ['⚔️', '🏃', '🏠'];
  const errColor   = (e: number) => e >= 0.08 ? '#ff6060' : e >= 0.01 ? '#f0c060' : '#60c060';

  async function loadClusters() {
    try { clusters = (await api.clusters.list()).clusters; }
    catch(e) { err = String(e); }
  }

  async function selectCluster(c: Cluster) {
    selected = c; loading = true;
    try {
      const [p, h] = await Promise.all([
        api.clusters.positions(c.cluster_id, { traps_only: trapsOnly, limit: 20 }),
        api.clusters.heuristics(c.cluster_id),
      ]);
      positions  = p.positions;
      heuristics = h.heuristics;
    } catch(e) { err = String(e); }
    finally { loading = false; }
  }

  async function toggleTraps() {
    if (selected) await selectCluster(selected);
  }

  onMount(loadClusters);
</script>

<svelte:head><title>Position Catalogue — GBF</title></svelte:head>

<h1>Position Catalogue</h1>
{#if err}<p class="err">{err}</p>{/if}

<div class="layout">
  <!-- Cluster list -->
  <aside>
    <div class="aside-head">
      <h2>Clusters</h2>
      <label class="check"><input type="checkbox" bind:checked={trapsOnly} onchange={toggleTraps} /> Traps only</label>
    </div>
    {#each clusters as c}
      <button class="cluster-btn" class:active={selected?.cluster_id === c.cluster_id}
              onclick={() => selectCluster(c)}>
        <span class="phase-icon">{phaseIcon[c.dominant_phase] ?? '◆'}</span>
        <span class="name">{c.archetype_label || `Cluster ${c.cluster_id}`}</span>
        <span class="meta">{c.position_count?.toLocaleString()} pos · {c.avg_error?.toFixed(3)}</span>
      </button>
    {/each}
  </aside>

  <!-- Detail -->
  <section>
    {#if !selected}
      <p class="empty">← Select a cluster to browse positions</p>
    {:else}
      <h2>
        {selected.archetype_label || `Cluster ${selected.cluster_id}`}
        <span class="badge">{phaseLabel[selected.dominant_phase]}</span>
      </h2>
      <p class="meta-row">
        {selected.position_count?.toLocaleString()} positions ·
        avg error {selected.avg_error?.toFixed(4)}
      </p>

      {#if heuristics.length}
        <div class="heuristics">
          <h3>Practical rules</h3>
          {#each heuristics as h: any}
            <div class="rule">
              <span class="rule-text">{h.rule_natural_language || h.rule}</span>
              {#if h.blunder_precision}
                <span class="risk">risk {(h.blunder_precision*100).toFixed(0)}%</span>
              {/if}
            </div>
          {/each}
        </div>
      {/if}

      {#if loading}<p class="loading">Loading…</p>{/if}

      <table>
        <thead>
          <tr><th>Player</th><th>Score</th><th>Phase</th><th>Type</th><th>Error</th></tr>
        </thead>
        <tbody>
          {#each positions as pos}
            <tr>
              <td><a href="/player/{encodeURIComponent(pos.player_name)}">{pos.player_name}</a></td>
              <td>{pos.away_p1}×{pos.away_p2}</td>
              <td>{phaseLabel[pos.match_phase]}</td>
              <td>{pos.decision_type}</td>
              <td style="color:{errColor(pos.move_played_error)}">{pos.move_played_error.toFixed(4)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>
</div>

<style>
  h1 { color: #f0c060; margin-bottom: 1.5rem; }
  .layout { display: grid; grid-template-columns: 260px 1fr; gap: 1.5rem; align-items: start; }
  aside { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 0.8rem; }
  .aside-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  aside h2 { color: #d4a835; font-size: 0.95rem; margin: 0; }
  .check { font-size: 0.75rem; color: #907060; display: flex; align-items: center; gap: 0.3rem; }
  .cluster-btn { display: flex; flex-direction: column; gap: 0.1rem; width: 100%; text-align: left;
                 background: none; border: none; border-radius: 6px; padding: 0.5rem 0.6rem;
                 cursor: pointer; color: #c0a070; transition: background 0.1s; }
  .cluster-btn:hover { background: #2a1508; }
  .cluster-btn.active { background: #2a1508; border-left: 2px solid #d4a835; }
  .phase-icon { font-size: 0.9rem; }
  .name { font-size: 0.85rem; font-weight: 500; }
  .meta { font-size: 0.7rem; color: #605040; }
  h2 { color: #d4a835; display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.3rem; }
  .badge { font-size: 0.7rem; background: #3a2010; color: #d4a835; padding: 0.1rem 0.4rem; border-radius: 10px; font-weight: normal; }
  .meta-row { color: #907060; font-size: 0.85rem; margin-bottom: 1rem; }
  .heuristics { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 0.8rem; margin-bottom: 1rem; }
  .heuristics h3 { color: #907060; font-size: 0.8rem; margin: 0 0 0.5rem; }
  .rule { display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 0.3rem; gap: 0.5rem; }
  .rule-text { color: #c0b090; }
  .risk { color: #ff8040; font-size: 0.75rem; white-space: nowrap; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { color: #907060; text-align: left; border-bottom: 1px solid #3a2010; padding: 0.3rem 0.6rem; }
  td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #1e1208; }
  td a { color: #d4a835; text-decoration: none; }
  .empty { color: #605040; font-style: italic; }
  .err { color: #ff6060; } .loading { color: #907060; font-style: italic; }
</style>
