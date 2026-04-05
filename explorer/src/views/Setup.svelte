<script>
  import { onMount } from 'svelte';
  import {
    fetchConfig, setDB, setBMAB, browseDir, formatNumber,
    startImport, fetchImportStatus, cancelImport, subscribeImportProgress,
    startProjectionCompute, fetchProjectionStatus, subscribeProjectionProgress,
  } from '../lib/api.js';
  import { invalidateCache } from '../lib/cache.js';

  // ── Config ────────────────────────────────────────────────────────────────
  let config = $state(null);
  let error = $state(null);
  let saving = $state(false);
  let dbInput = $state('');
  let bmabInput = $state('');
  let bmabFiles = $state(null);

  // ── File browser ──────────────────────────────────────────────────────────
  let browsing = $state(null); // 'db' | 'bmab' | null
  let browserPath = $state('');
  let browserEntries = $state([]);
  let browserLoading = $state(false);
  let browserTruncated = $state(false);
  let dbFilename = $state('bmab.db');

  // ── Import ────────────────────────────────────────────────────────────────
  let proportion = $state(1);
  let batchSize = $state(100);
  let importing = $state(false);
  let importEvents = $state([]);
  let importError = $state(null);
  let importResult = $state(null);
  let importJournalPath = $state('');
  let importUnsub = null;

  // ── Projections ───────────────────────────────────────────────────────────
  let projMethod = $state('pca_2d');
  let projClusterMethod = $state('kmeans');
  let projK = $state(8);
  let projSample = $state(0);
  let projPerplexity = $state(30);
  let projTSNEIter = $state(1000);
  let projHDBSCANMinSize = $state(100);
  let projHDBSCANMinSample = $state(50);
  let projNNeighbors = $state(15);
  let projUMAPMinDist = $state(0.1);
  let projComputing = $state(false);
  let projEvents = $state([]);
  let projError = $state(null);
  let projUnsub = null;

  // Feature selection: all 44 features, user can toggle.
  const ALL_FEATURES = [
    // Raw (0-23): points
    ...Array.from({length: 24}, (_, i) => ({ idx: i, name: `point${String(i+1).padStart(2,'0')}`, group: 'Board Points' })),
    // Raw (24-33)
    { idx: 24, name: 'bar_x', group: 'Bar & Off' },
    { idx: 25, name: 'bar_o', group: 'Bar & Off' },
    { idx: 26, name: 'borne_off_x', group: 'Bar & Off' },
    { idx: 27, name: 'borne_off_o', group: 'Bar & Off' },
    { idx: 28, name: 'pip_x', group: 'Pip' },
    { idx: 29, name: 'pip_o', group: 'Pip' },
    { idx: 30, name: 'cube_log2', group: 'Cube & Score' },
    { idx: 31, name: 'cube_owner', group: 'Cube & Score' },
    { idx: 32, name: 'away_x', group: 'Cube & Score' },
    { idx: 33, name: 'away_o', group: 'Cube & Score' },
    // Derived (34-43)
    { idx: 34, name: 'blot_x', group: 'Derived' },
    { idx: 35, name: 'blot_o', group: 'Derived' },
    { idx: 36, name: 'made_x', group: 'Derived' },
    { idx: 37, name: 'made_o', group: 'Derived' },
    { idx: 38, name: 'prime_x', group: 'Derived' },
    { idx: 39, name: 'prime_o', group: 'Derived' },
    { idx: 40, name: 'anchor_x', group: 'Derived' },
    { idx: 41, name: 'anchor_o', group: 'Derived' },
    { idx: 42, name: 'pip_diff', group: 'Derived' },
    { idx: 43, name: 'pos_class', group: 'Derived' },
  ];
  let selectedFeatures = $state(new Set(ALL_FEATURES.map(f => f.idx)));
  let showFeatureSelection = $state(false);

  onMount(async () => {
    await loadConfig();
    await restoreImportState();
    await restoreProjectionState();
  });

  async function loadConfig() {
    try {
      config = await fetchConfig();
      dbInput = config.db_path || '';
      bmabInput = config.bmab_dir || '';
    } catch (e) {
      error = e.message;
    }
  }

  // Reconnect to running/completed import after a tab switch.
  async function restoreImportState() {
    try {
      const status = await fetchImportStatus();
      if (status.journal_path) importJournalPath = status.journal_path;
      if (!status.running && !status.done) return;
      // Replay all events from the server (SSE sends from cursor=0).
      importEvents = [];
      importing = status.running;
      if (status.last_event) importResult = { proportion: 0, files: status.last_event.files_total, limit: status.last_event.files_total };
      if (status.running) {
        // Re-subscribe: SSE replays history then continues live.
        importUnsub?.();
        importUnsub = subscribeImportProgress(
          (evt) => { importEvents = [...importEvents, evt]; },
          (final) => { importing = false; if (final.error) importError = final.error; }
        );
      } else if (status.done && status.last_event) {
        // Already finished — show final event directly without SSE.
        importEvents = [status.last_event];
        if (status.last_event.error) importError = status.last_event.error;
      }
    } catch (_) {
      // Status endpoint may 503 if no DB open yet — ignore silently.
    }
  }

  // Reconnect to running/completed projection after a tab switch.
  async function restoreProjectionState() {
    try {
      const status = await fetchProjectionStatus();
      if (!status.running && !status.done) return;
      projEvents = [];
      projComputing = status.running;
      if (status.running) {
        projUnsub?.();
        projUnsub = subscribeProjectionProgress(
          (evt) => { projEvents = [...projEvents, evt]; },
          (final) => { projComputing = false; if (final.error) projError = final.error; }
        );
      } else if (status.done && status.last_event) {
        projEvents = [status.last_event];
        if (status.last_event.error) projError = status.last_event.error;
      }
    } catch (_) {}
  }

  async function handleSetDB() {
    if (!dbInput.trim()) return;
    saving = true; error = null;
    try { await setDB(dbInput.trim()); await loadConfig(); }
    catch (e) { error = e.message; }
    saving = false;
  }

  async function handleSetBMAB() {
    if (!bmabInput.trim()) return;
    saving = true; error = null;
    try {
      const res = await setBMAB(bmabInput.trim());
      bmabFiles = res.files;
      await loadConfig();
    } catch (e) { error = e.message; }
    saving = false;
  }

  async function openBrowser(mode) {
    browsing = mode;
    browserEntries = [];
    browserTruncated = false;
    if (mode === 'db' && dbInput) {
      dbFilename = dbInput.split('/').pop() || 'bmab.db';
    }
    const startPath = mode === 'db' ? dbInput : bmabInput;
    await loadBrowserDir(startPath || '', mode);
  }

  async function loadBrowserDir(path, mode) {
    browserLoading = true;
    try {
      let dir = path;
      // If path looks like a file (has extension), navigate to its parent dir
      if (dir && !dir.endsWith('/')) {
        const last = dir.split('/').pop() || '';
        if (last.includes('.')) dir = dir.split('/').slice(0, -1).join('/') || '/';
      }
      const res = await browseDir(dir, mode || browsing);
      browserPath = res.path;
      browserEntries = res.entries || [];
      browserTruncated = res.truncated || false;
    } catch (e) { error = e.message; }
    browserLoading = false;
  }

  function navigateBrowser(entry) {
    if (!entry.is_dir) {
      // DB mode: clicking a file fills the filename field
      if (browsing === 'db') dbFilename = entry.name;
      return;
    }
    const next = entry.name === '..'
      ? (browserPath.split('/').slice(0, -1).join('/') || '/')
      : browserPath + '/' + entry.name;
    loadBrowserDir(next, browsing);
  }

  function confirmBrowser() {
    if (browsing === 'db') {
      const fn = (dbFilename || 'bmab.db').trim();
      dbInput = fn.startsWith('/') ? fn : browserPath + '/' + fn;
    } else {
      bmabInput = browserPath;
    }
    browsing = null;
  }

  // ── Import handlers ───────────────────────────────────────────────────────
  function handleImportStart() {
    importError = null; importResult = null; importEvents = [];
    importing = true;
    startImport(proportion / 100, batchSize)
      .then((resp) => {
        importResult = resp;
        importJournalPath = resp.journal_path || '';
        importUnsub?.();
        importUnsub = subscribeImportProgress(
          (evt) => { importEvents = [...importEvents, evt]; },
          (final) => { importing = false; if (final.error) importError = final.error; }
        );
      })
      .catch((e) => { importError = e.message; importing = false; });
  }

  async function handleImportCancel() {
    importUnsub?.(); importUnsub = null;
    try { await cancelImport(); } catch (_) {}
    importing = false;
  }

  // ── Projection handlers ───────────────────────────────────────────────────
  function handleComputeProj() {
    projError = null; projEvents = []; projComputing = true;
    const featureIndices = selectedFeatures.size < ALL_FEATURES.length
      ? [...selectedFeatures].sort((a, b) => a - b)
      : null;
    startProjectionCompute({
      method: projMethod,
      k: projClusterMethod === 'kmeans' ? projK : 0,
      sampleSize: projSample,
      clusterMethod: projClusterMethod,
      perplexity: projPerplexity,
      tsneIter: projTSNEIter,
      hdbscanMinSize: projHDBSCANMinSize,
      hdbscanMinSample: projHDBSCANMinSample,
      nNeighbors: projNNeighbors,
      umapMinDist: projUMAPMinDist,
      featureIndices: featureIndices,
    })
      .then(() => {
        projUnsub?.();
        projUnsub = subscribeProjectionProgress(
          (evt) => { projEvents = [...projEvents, evt]; },
          (final) => {
            projComputing = false;
            if (final.error) { projError = final.error; return; }
            // Invalidate dashboard stats cache so projection runs appear there too.
            invalidateCache('dashboard:stats');
          }
        );
      })
      .catch((e) => { projError = e.message; projComputing = false; });
  }

  // ── Derived ───────────────────────────────────────────────────────────────
  let lastImport = $derived(importEvents.at(-1) ?? null);
  let importPct = $derived(
    lastImport?.files_total > 0
      ? Math.round((lastImport.files_done / lastImport.files_total) * 100)
      : 0
  );
  let lastProj = $derived(projEvents.at(-1) ?? null);
  let showJournal = $derived(importJournalPath !== '' && (lastImport !== null || importing));
</script>

{#if error}
  <div class="card" style="border-color:var(--red)">
    <p style="color:var(--red);margin:0">{error}
      <button class="btn" style="margin-left:8px;padding:2px 8px;font-size:11px" onclick={() => error = null}>✕</button>
    </p>
  </div>
{/if}

<!-- 1 · Database -->
<div class="card">
  <h2>1 · Database</h2>
  <p style="color:var(--text-muted);margin-bottom:12px">
    Path to the SQLite file. Created automatically if it doesn't exist.
  </p>
  <div class="setup-row">
    <input type="text" bind:value={dbInput} placeholder="/path/to/bmab.db" class="path-input" />
    <button class="btn" onclick={() => openBrowser('db')}>📁 Browse</button>
    <button class="btn primary" onclick={handleSetDB} disabled={saving || !dbInput.trim()}>
      {config?.has_db ? 'Change DB' : 'Open / Create'}
    </button>
  </div>
  {#if config?.has_db}
    <div class="status-badge ok">✅ {config.db_path}</div>
  {:else}
    <div class="status-badge warn">⚠️ No database open</div>
  {/if}
</div>

<!-- 2 · BMAB directory -->
<div class="card">
  <h2>2 · BMAB Data Directory</h2>
  <p style="color:var(--text-muted);margin-bottom:12px">
    Folder containing the .xg match files to import.
  </p>
  <div class="setup-row">
    <input type="text" bind:value={bmabInput} placeholder="/path/to/bmab-2025-06-23" class="path-input" />
    <button class="btn" onclick={() => openBrowser('bmab')}>📁 Browse</button>
    <button class="btn primary" onclick={handleSetBMAB} disabled={saving || !bmabInput.trim()}>
      Set Directory
    </button>
  </div>
  {#if config?.has_bmab}
    <div class="status-badge ok">
      ✅ {config.bmab_dir}
      {#if bmabFiles != null}&nbsp;— {formatNumber(bmabFiles)} .xg files{/if}
    </div>
  {:else}
    <div class="status-badge warn">⚠️ No BMAB directory set</div>
  {/if}
</div>

<!-- 3 · Import -->
<div class="card">
  <h2>3 · Import BMAB Data</h2>
  <p style="color:var(--text-muted);margin-bottom:12px">
    Load XG files into the database. Requires steps 1 and 2.
    Previously imported files are skipped automatically (resume on restart).
  </p>
  <div class="controls">
    <label>
      Proportion (%)
      <input type="number" bind:value={proportion} min="0.1" max="100" step="0.1"
        style="width:90px" disabled={!config?.has_db || !config?.has_bmab || importing} />
    </label>
    <label>
      Batch size
      <select bind:value={batchSize} disabled={!config?.has_db || !config?.has_bmab || importing}>
        <option value={50}>50</option>
        <option value={100}>100</option>
        <option value={200}>200</option>
        <option value={500}>500</option>
      </select>
    </label>
    {#if !importing}
      <button class="btn primary" onclick={handleImportStart}
        disabled={!config?.has_db || !config?.has_bmab}>Start Import</button>
    {:else}
      <button class="btn" style="border-color:var(--red);color:var(--red)" onclick={handleImportCancel}>
        Stop
      </button>
    {/if}
  </div>

  {#if importError}
    <div class="status-badge" style="background:rgba(247,118,142,.1);color:var(--red);border-color:rgba(247,118,142,.3);margin-top:8px">
      {importError}
    </div>
  {/if}

  {#if importResult}
    <div class="stats-grid" style="margin-top:12px">
      <div class="stat-card"><div class="label">Total files</div><div class="value">{formatNumber(importResult.files)}</div></div>
      <div class="stat-card"><div class="label">To import</div><div class="value">{formatNumber(importResult.limit)}</div></div>
      <div class="stat-card"><div class="label">Proportion</div><div class="value">{(importResult.proportion * 100).toFixed(1)}%</div></div>
    </div>
  {/if}

  {#if lastImport}
    <div style="margin-top:10px">
      <div class="progress-bar"><div class="fill" style="width:{importPct}%"></div></div>
      <div class="stats-grid" style="margin-top:8px">
        <div class="stat-card"><div class="label">Files imported</div><div class="value">{formatNumber(lastImport.files_done)}</div></div>
        {#if lastImport.skipped > 0}
          <div class="stat-card"><div class="label">Skipped (journal)</div><div class="value" style="color:var(--text-muted)">{formatNumber(lastImport.skipped)}</div></div>
        {/if}
        <div class="stat-card"><div class="label">Positions</div><div class="value">{formatNumber(lastImport.positions)}</div></div>
        <div class="stat-card"><div class="label">Rate</div><div class="value">{lastImport.rate?.toFixed(0) || '—'} pos/s</div></div>
        <div class="stat-card"><div class="label">Elapsed</div><div class="value" style="font-size:14px">{lastImport.elapsed}</div></div>
        <div class="stat-card"><div class="label">Remaining</div><div class="value" style="font-size:14px">{lastImport.remaining || '—'}</div></div>
        <div class="stat-card">
          <div class="label">Status</div>
          <div class="value" style="font-size:14px;color:{lastImport.done ? (lastImport.cancelled ? 'var(--orange)' : 'var(--green)') : 'var(--orange)'}">
            {lastImport.done ? (lastImport.cancelled ? '⏸ Stopped' : '✅ Done') : '⏳ Running'}
          </div>
        </div>
      </div>
    </div>
  {/if}

  {#if showJournal}
    <div style="margin-top:10px;padding:8px 10px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:11px;font-family:var(--mono);color:var(--text-muted)">
      📋 Resume journal: <span style="color:var(--cyan)">{importJournalPath}</span>
      <span style="color:var(--text-muted)"> — delete this file to reimport everything from scratch</span>
    </div>
  {/if}
</div>

<!-- 4 · Projections -->
<div class="card">
  <h2>4 · Compute Projections</h2>
  <p style="color:var(--text-muted);margin-bottom:12px">
    Dimensionality reduction + clustering. PCA is fast. UMAP gives the best cluster separation. t-SNE is capped at 5K points. Requires step 3.
  </p>

  <!-- Method & Clustering selection -->
  <div class="controls">
    <label>
      Reduction
      <select bind:value={projMethod} disabled={!config?.has_db || projComputing}>
        <option value="umap_2d">UMAP 2D</option>
        <option value="pca_2d">PCA 2D</option>
        <option value="tsne_2d">t-SNE 2D (max 5K pts)</option>
      </select>
    </label>
    <label>
      Clustering
      <select bind:value={projClusterMethod} disabled={!config?.has_db || projComputing}>
        <option value="kmeans">K-Means</option>
        <option value="hdbscan">HDBSCAN</option>
      </select>
    </label>
    <label>
      Sample (0 = all)
      <input type="number" bind:value={projSample} min="0" step="1000" style="width:100px" disabled={!config?.has_db || projComputing} />
    </label>
  </div>

  <!-- Method-specific params -->
  <div class="controls" style="margin-top:8px">
    {#if projMethod === 'umap_2d'}
      <label>
        n_neighbors
        <input type="number" bind:value={projNNeighbors} min="2" max="200" style="width:70px" disabled={!config?.has_db || projComputing} />
      </label>
      <label>
        min_dist
        <input type="number" bind:value={projUMAPMinDist} min="0.0" max="1.0" step="0.05" style="width:70px" disabled={!config?.has_db || projComputing} />
      </label>
    {/if}
    {#if projMethod === 'tsne_2d'}
      <label>
        Perplexity
        <input type="number" bind:value={projPerplexity} min="5" max="100" style="width:70px" disabled={!config?.has_db || projComputing} />
      </label>
      <label>
        Iterations
        <input type="number" bind:value={projTSNEIter} min="100" max="5000" step="100" style="width:90px" disabled={!config?.has_db || projComputing} />
      </label>
    {/if}

    {#if projClusterMethod === 'kmeans'}
      <label>
        Clusters (k)
        <input type="number" bind:value={projK} min="2" max="50" style="width:70px" disabled={!config?.has_db || projComputing} />
      </label>
    {:else}
      <label>
        Min cluster size
        <input type="number" bind:value={projHDBSCANMinSize} min="10" max="1000" step="10" style="width:90px" disabled={!config?.has_db || projComputing} />
      </label>
      <label>
        Min samples
        <input type="number" bind:value={projHDBSCANMinSample} min="5" max="500" step="5" style="width:80px" disabled={!config?.has_db || projComputing} />
      </label>
    {/if}
  </div>

  <!-- Feature selection -->
  <div style="margin-top:10px">
    <button class="btn" onclick={() => showFeatureSelection = !showFeatureSelection} style="font-size:11px;padding:3px 10px">
      {showFeatureSelection ? '▼' : '▶'} Feature Selection ({selectedFeatures.size}/{ALL_FEATURES.length})
    </button>
    {#if showFeatureSelection}
      <div class="feature-grid" style="margin-top:8px">
        <div style="margin-bottom:6px;display:flex;gap:6px">
          <button class="btn" style="font-size:10px;padding:2px 6px"
            onclick={() => { selectedFeatures = new Set(ALL_FEATURES.map(f => f.idx)); }}>All</button>
          <button class="btn" style="font-size:10px;padding:2px 6px"
            onclick={() => { selectedFeatures = new Set(); }}>None</button>
          <button class="btn" style="font-size:10px;padding:2px 6px"
            onclick={() => { selectedFeatures = new Set(ALL_FEATURES.filter(f => f.group === 'Board Points').map(f => f.idx)); }}>Board only</button>
          <button class="btn" style="font-size:10px;padding:2px 6px"
            onclick={() => { selectedFeatures = new Set(ALL_FEATURES.filter(f => f.group === 'Derived').map(f => f.idx)); }}>Derived only</button>
          <button class="btn" style="font-size:10px;padding:2px 6px"
            onclick={() => {
              const structural = ALL_FEATURES.filter(f => f.group === 'Derived' || f.group === 'Pip' || f.group === 'Bar & Off');
              selectedFeatures = new Set(structural.map(f => f.idx));
            }}>Strategic</button>
        </div>
        {#each ['Board Points', 'Bar & Off', 'Pip', 'Cube & Score', 'Derived'] as group}
          <div class="feature-group">
            <strong style="font-size:10px;color:var(--text-muted)">{group}</strong>
            <div style="display:flex;flex-wrap:wrap;gap:2px 6px">
              {#each ALL_FEATURES.filter(f => f.group === group) as feat}
                <label class="feature-toggle" style="font-size:10px">
                  <input type="checkbox" checked={selectedFeatures.has(feat.idx)}
                    onchange={(e) => {
                      const next = new Set(selectedFeatures);
                      if (e.target.checked) next.add(feat.idx); else next.delete(feat.idx);
                      selectedFeatures = next;
                    }} />
                  {feat.name}
                </label>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Compute button -->
  <div style="margin-top:10px">
    {#if !projComputing}
      <button class="btn primary" onclick={handleComputeProj} disabled={!config?.has_db || selectedFeatures.size < 2}>
        Compute Projections
      </button>
      {#if selectedFeatures.size < 2}
        <span style="color:var(--red);font-size:11px;margin-left:8px">Select at least 2 features</span>
      {/if}
    {:else}
      <button class="btn" disabled>⏳ Computing…</button>
    {/if}
  </div>

  {#if projError}
    <div class="status-badge" style="background:rgba(247,118,142,.1);color:var(--red);border-color:rgba(247,118,142,.3);margin-top:8px">
      {projError}
    </div>
  {/if}

  {#if lastProj || projComputing}
    <div style="margin-top:10px">
      {#if projComputing && lastProj}
        <div class="progress-bar"><div class="fill" style="width:{lastProj.percent || 0}%"></div></div>
      {/if}
      <div class="stats-grid" style="margin-top:8px">
        <div class="stat-card">
          <div class="label">Stage</div>
          <div class="value" style="font-size:13px">{lastProj?.stage?.replace(/_/g, ' ') || 'starting'}</div>
        </div>
        <div class="stat-card">
          <div class="label">Progress</div>
          <div class="value">{lastProj?.percent ?? 0}%</div>
        </div>
        <div class="stat-card">
          <div class="label">Status</div>
          <div class="value" style="font-size:14px;color:{lastProj?.done && !lastProj?.error ? 'var(--green)' : lastProj?.error ? 'var(--red)' : 'var(--orange)'}">
            {lastProj?.done ? (lastProj?.error ? '❌ Error' : '✅ Done') : '⏳ Running'}
          </div>
        </div>
      </div>
    </div>
    {#if lastProj?.message}
      <div class="status-badge ok" style="margin-top:8px">{lastProj.message}</div>
    {/if}
  {/if}
</div>

<!-- File Browser Modal -->
{#if browsing}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop" onclick={() => (browsing = null)}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>

      <div class="modal-header">
        <span>{browsing === 'db' ? '📄 Select or create database file' : '📁 Select BMAB directory'}</span>
        <button class="btn" onclick={() => (browsing = null)}>✕</button>
      </div>

      <div class="browser-path">{browserPath}</div>

      <div class="browser-list">
        {#if browserLoading}
          <div class="loading">Loading…</div>
        {:else if browserEntries.length === 0}
          <div class="loading" style="color:var(--text-muted)">Empty directory</div>
        {:else}
          {#each browserEntries as entry}
            <button
              class="browser-item"
              class:is-dir={entry.is_dir}
              onclick={() => navigateBrowser(entry)}
            >
              <span class="browser-icon">{entry.is_dir ? '📁' : '🗄️'}</span>
              {entry.name}
            </button>
          {/each}
          {#if browserTruncated}
            <div style="padding:4px 12px;font-size:11px;color:var(--text-muted);font-style:italic">
              Only showing relevant entries. Navigate into a subfolder to see more.
            </div>
          {/if}
        {/if}
      </div>

      <div class="modal-footer">
        {#if browsing === 'db'}
          <div class="footer-row">
            <span style="color:var(--text-muted);font-size:12px;white-space:nowrap">File name:</span>
            <input class="path-input" type="text" bind:value={dbFilename}
              placeholder="bmab.db" style="flex:1;min-width:0" />
            <button class="btn primary" onclick={confirmBrowser} disabled={!dbFilename.trim()}>
              Confirm
            </button>
          </div>
        {:else}
          <div class="footer-row">
            <span class="selected-dir" title={browserPath}>{browserPath}</span>
            <button class="btn primary" onclick={confirmBrowser}>Select this folder</button>
          </div>
        {/if}
        <div style="display:flex;justify-content:flex-end">
          <button class="btn" onclick={() => (browsing = null)}>Cancel</button>
        </div>
      </div>

    </div>
  </div>
{/if}

<style>
  .setup-row {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
  }

  .path-input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 12px;
    border-radius: var(--radius);
    font-family: var(--mono);
    font-size: 13px;
    min-width: 0;
  }

  .status-badge {
    padding: 8px 12px;
    border-radius: var(--radius);
    font-size: 13px;
    margin-top: 8px;
    border: 1px solid transparent;
  }
  .status-badge.ok   { background: rgba(158,206,106,.1); color: var(--green);  border-color: rgba(158,206,106,.25); }
  .status-badge.warn { background: rgba(224,175,104,.1); color: var(--orange); border-color: rgba(224,175,104,.25); }

  /* Modal */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    width: 580px;
    max-width: 95vw;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }

  .browser-path {
    padding: 6px 16px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--cyan);
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    word-break: break-all;
  }

  .browser-list {
    overflow-y: auto;
    flex: 1;
    padding: 6px;
    min-height: 180px;
    max-height: 360px;
  }

  .loading {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
  }

  .browser-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 5px 10px;
    border: none;
    background: none;
    color: var(--text);
    font-size: 13px;
    cursor: pointer;
    border-radius: 4px;
    text-align: left;
    font-family: var(--mono);
  }
  .browser-item:hover { background: var(--bg-hover); }
  .browser-item.is-dir { color: var(--accent); }

  .browser-icon { width: 20px; text-align: center; }

  .modal-footer {
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .footer-row {
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
  }

  .selected-dir {
    flex: 1;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--cyan);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .feature-grid {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
    max-height: 240px;
    overflow-y: auto;
  }
  .feature-group {
    margin-bottom: 4px;
  }
  .feature-toggle {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    cursor: pointer;
    color: var(--text);
  }
  .feature-toggle input {
    accent-color: var(--accent);
  }
</style>
