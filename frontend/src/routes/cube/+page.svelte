<!-- Cube Helper — threshold table + equity calculator -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Threshold } from '$lib/api';

  let thresholds  = $state<Threshold[]>([]);
  let gammonVals  = $state<unknown[]>([]);
  let loadingT    = $state(false);

  // Calculator
  let s_p1     = $state(3);
  let s_p2     = $state(3);
  let s_cube   = $state(1);
  let s_equity = $state(0.0);
  let s_gammon = $state(0.0);
  let rec      = $state<{ action: string; distance: number; gammon_adj_action: string; heuristics: unknown[] } | null>(null);
  let recErr   = $state('');

  async function loadThresholds() {
    loadingT = true;
    try { thresholds = (await api.cube.thresholds()).thresholds; }
    catch {}
    finally { loadingT = false; }
  }

  async function getRecommendation() {
    recErr = '';
    try {
      rec = await api.cube.recommendation({
        away_p1: s_p1, away_p2: s_p2, cube_value: s_cube,
        equity: s_equity, gammon_threat: s_gammon,
      });
    } catch(e) { recErr = String(e); rec = null; }
  }

  // Build mini threshold grid (up to 7×7 for readability)
  const DISPLAY_MAX = 9;
  let grid = $derived(() => {
    const map = new Map(thresholds.map(t => [`${t.away_p1}_${t.away_p2}`, t]));
    const rows: Array<Array<Threshold | null>> = [];
    for (let p2 = 1; p2 <= DISPLAY_MAX; p2++) {
      const row: Array<Threshold | null> = [];
      for (let p1 = 1; p1 <= DISPLAY_MAX; p1++) {
        row.push(map.get(`${p1}_${p2}`) ?? null);
      }
      rows.push(row);
    }
    return rows;
  });

  const actionColor = (a: string) =>
    a === 'no_double' ? '#60c060' : a === 'double_take' ? '#f0c060' : '#ff6060';
  const actionLabel = (a: string) =>
    ({ no_double: 'No Double', double_take: '×2 / Take', double_pass: '×2 / Pass' }[a] ?? a);

  onMount(() => { loadThresholds(); api.cube.gammonValues().then(r => gammonVals = r.gammon_values).catch(() => {}); });
</script>

<svelte:head><title>Cube Helper — GBF</title></svelte:head>

<h1>Cube Helper</h1>

<div class="layout">
  <!-- Left: calculator -->
  <div class="calc">
    <h2>Equity calculator</h2>
    <label>Away P1 <input type="number" bind:value={s_p1} min="1" max="25" /></label>
    <label>Away P2 <input type="number" bind:value={s_p2} min="1" max="25" /></label>
    <label>Cube value
      <select bind:value={s_cube}>
        {#each [1,2,4,8,16] as v}<option value={v}>{v}</option>{/each}
      </select>
    </label>
    <label>Equity (−1 → +1)
      <div class="slider-row">
        <input type="range" bind:value={s_equity} min="-1" max="1" step="0.01" />
        <span>{s_equity.toFixed(2)}</span>
      </div>
    </label>
    <label>Gammon threat (0 → 1)
      <div class="slider-row">
        <input type="range" bind:value={s_gammon} min="0" max="1" step="0.01" />
        <span>{s_gammon.toFixed(2)}</span>
      </div>
    </label>
    <button onclick={getRecommendation}>Get recommendation</button>

    {#if recErr}<p class="err">{recErr}</p>{/if}

    {#if rec}
      <div class="rec" style="border-color:{actionColor(rec.action)}">
        <div class="action" style="color:{actionColor(rec.action)}">{actionLabel(rec.action)}</div>
        <div class="dist">Distance to threshold: {rec.distance.toFixed(4)}</div>
        {#if rec.gammon_adj_action !== rec.action}
          <div class="gammon-adj">Gammon-adjusted: <strong>{actionLabel(rec.gammon_adj_action)}</strong></div>
        {/if}
        {#if rec.heuristics.length}
          <div class="hints">
            <strong>Rules:</strong>
            {#each rec.heuristics as h: any}
              <p>{h.rule_natural_language || h.rule}</p>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Right: threshold grid -->
  <div class="grid-wrap">
    <h2>Thresholds (double / pass) — away P1 × P2 (1–{DISPLAY_MAX})</h2>
    {#if loadingT}<p class="loading">Loading…</p>{:else}
      <div class="tgrid">
        <div class="corner"></div>
        {#each Array.from({length: DISPLAY_MAX}, (_, i) => i + 1) as p1}
          <div class="hdr">{p1}</div>
        {/each}
        {#each grid(), (row, p2i)}
          <div class="hdr">{p2i + 1}</div>
          {#each row as cell}
            <div class="tcell" class:sel={cell && Number(cell.away_p1) === s_p1 && Number(cell.away_p2) === s_p2}>
              {#if cell}
                <span class="dt">{parseFloat(cell.double_threshold).toFixed(2)}</span>
                <span class="pt">{parseFloat(cell.pass_threshold).toFixed(2)}</span>
              {:else}
                <span class="na">—</span>
              {/if}
            </div>
          {/each}
        {/each}
      </div>
      <p class="legend"><span class="dt">0.00</span> double threshold &nbsp; <span class="pt">0.00</span> pass threshold</p>
    {/if}
  </div>
</div>

<style>
  h1 { color: #f0c060; margin-bottom: 1.5rem; }
  h2 { color: #d4a835; font-size: 1rem; margin-bottom: 0.8rem; }
  .layout { display: grid; grid-template-columns: 260px 1fr; gap: 2rem; align-items: start; }
  .calc { background: #1a0f07; border: 1px solid #3a2010; border-radius: 8px; padding: 1rem; }
  label { display: flex; flex-direction: column; font-size: 0.8rem; color: #907060; gap: 0.2rem; margin-bottom: 0.6rem; }
  input[type=number], select { background: #0f0a05; border: 1px solid #3a2010; border-radius: 4px; color: #e0d0c0; padding: 0.3rem 0.5rem; width: 80px; }
  .slider-row { display: flex; align-items: center; gap: 0.5rem; }
  .slider-row input { width: 140px; }
  .slider-row span { color: #e0d0c0; font-size: 0.9rem; min-width: 35px; }
  button { width: 100%; padding: 0.5rem; background: #c47a20; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
  .rec { margin-top: 1rem; border: 1px solid; border-radius: 8px; padding: 0.8rem; }
  .action { font-size: 1.3rem; font-weight: bold; margin-bottom: 0.3rem; }
  .dist { font-size: 0.8rem; color: #907060; }
  .gammon-adj { font-size: 0.85rem; color: #f0c060; margin-top: 0.3rem; }
  .hints { margin-top: 0.5rem; font-size: 0.8rem; color: #b09070; }
  .hints p { margin: 0.2rem 0; }
  .tgrid { display: grid; grid-template-columns: 20px repeat(9, 52px); gap: 2px; font-size: 0.72rem; }
  .hdr { color: #907060; text-align: center; padding: 2px; }
  .corner {}
  .tcell { background: #1a0f07; border: 1px solid #2a1808; border-radius: 3px; padding: 3px 4px; display: flex; flex-direction: column; min-height: 32px; justify-content: center; }
  .tcell.sel { border-color: #f0c060; }
  .dt { color: #60a0ff; }
  .pt { color: #ff8060; }
  .na { color: #3a2010; text-align: center; }
  .legend { font-size: 0.75rem; color: #907060; margin-top: 0.4rem; }
  .err { color: #ff6060; font-size: 0.85rem; } .loading { color: #907060; font-style: italic; }
</style>
