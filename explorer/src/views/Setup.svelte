<script>
  import { onMount } from 'svelte';
  import { fetchConfig, setDB, setBMAB, browseDir, formatNumber } from '../lib/api.js';

  let config = $state(null);
  let error = $state(null);
  let saving = $state(false);

  // DB config
  let dbInput = $state('');

  // BMAB config
  let bmabInput = $state('');
  let bmabFiles = $state(null);

  // File browser
  let browsing = $state(null); // 'db' or 'bmab'
  let browserPath = $state('');
  let browserEntries = $state([]);
  let browserLoading = $state(false);

  onMount(async () => {
    await loadConfig();
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

  async function handleSetDB() {
    if (!dbInput.trim()) return;
    saving = true;
    error = null;
    try {
      await setDB(dbInput.trim());
      await loadConfig();
    } catch (e) {
      error = e.message;
    }
    saving = false;
  }

  async function handleSetBMAB() {
    if (!bmabInput.trim()) return;
    saving = true;
    error = null;
    try {
      const result = await setBMAB(bmabInput.trim());
      bmabFiles = result.files;
      await loadConfig();
    } catch (e) {
      error = e.message;
    }
    saving = false;
  }

  async function openBrowser(mode) {
    browsing = mode;
    browserEntries = [];
    const startPath = mode === 'db' ? dbInput : bmabInput;
    await loadBrowserDir(startPath || '');
  }

  async function loadBrowserDir(path) {
    browserLoading = true;
    try {
      const result = await browseDir(path);
      browserPath = result.path;
      browserEntries = result.entries;
    } catch (e) {
      error = e.message;
    }
    browserLoading = false;
  }

  function handleBrowserSelect(entry) {
    if (entry.is_dir) {
      if (entry.name === '..') {
        const parent = browserPath.split('/').slice(0, -1).join('/') || '/';
        loadBrowserDir(parent);
      } else {
        loadBrowserDir(browserPath + '/' + entry.name);
      }
    } else {
      // File selected (for DB).
      if (browsing === 'db') {
        dbInput = browserPath + '/' + entry.name;
        browsing = null;
      }
    }
  }

  function selectCurrentDir() {
    if (browsing === 'bmab') {
      bmabInput = browserPath;
    } else if (browsing === 'db') {
      dbInput = browserPath + '/bmab.db';
    }
    browsing = null;
  }
</script>

<div class="card">
  <h2>⚙️ Setup</h2>
  <p style="color:var(--text-muted); margin-bottom:20px">
    Configure the database and data directory. All settings take effect immediately.
  </p>
</div>

{#if error}
  <div class="card" style="border-color:var(--red); margin-bottom:16px">
    <p style="color:var(--red); margin:0">{error}</p>
  </div>
{/if}

<!-- Database Configuration -->
<div class="card">
  <h2>Database</h2>
  <p style="color:var(--text-muted); margin-bottom:12px">
    Path to the SQLite database file. A new database is created if the file doesn't exist.
  </p>

  <div class="setup-row">
    <input
      type="text"
      bind:value={dbInput}
      placeholder="/path/to/bmab.db"
      class="path-input"
    />
    <button class="btn" onclick={() => openBrowser('db')}>Browse</button>
    <button class="btn primary" onclick={handleSetDB} disabled={saving || !dbInput.trim()}>
      {config?.has_db ? 'Change' : 'Open / Create'}
    </button>
  </div>

  {#if config?.has_db}
    <div class="status-badge ok">✅ Database connected: {config.db_path}</div>
  {:else}
    <div class="status-badge warn">⚠️ No database — create or open one to start</div>
  {/if}
</div>

<!-- BMAB Directory Configuration -->
<div class="card">
  <h2>BMAB Data Directory</h2>
  <p style="color:var(--text-muted); margin-bottom:12px">
    Directory containing the BMAB .xg files for import.
  </p>

  <div class="setup-row">
    <input
      type="text"
      bind:value={bmabInput}
      placeholder="/path/to/bmab-2025-06-23"
      class="path-input"
    />
    <button class="btn" onclick={() => openBrowser('bmab')}>Browse</button>
    <button class="btn primary" onclick={handleSetBMAB} disabled={saving || !bmabInput.trim()}>
      Set Directory
    </button>
  </div>

  {#if config?.has_bmab}
    <div class="status-badge ok">
      ✅ BMAB directory: {config.bmab_dir}
      {#if bmabFiles != null} — {formatNumber(bmabFiles)} .xg files{/if}
    </div>
  {:else}
    <div class="status-badge warn">⚠️ No BMAB directory set — needed for importing data</div>
  {/if}
</div>

<!-- Quick Start Guide -->
<div class="card">
  <h2>Quick Start</h2>
  <div class="steps">
    <div class="step" class:done={config?.has_db}>
      <span class="step-num">{config?.has_db ? '✅' : '1'}</span>
      <div>
        <strong>Create or open a database</strong>
        <p>Enter a path above (e.g. <code>bmab.db</code>) and click "Open / Create"</p>
      </div>
    </div>
    <div class="step" class:done={config?.has_bmab}>
      <span class="step-num">{config?.has_bmab ? '✅' : '2'}</span>
      <div>
        <strong>Set the BMAB directory</strong>
        <p>Point to the folder containing the .xg match files</p>
      </div>
    </div>
    <div class="step">
      <span class="step-num">3</span>
      <div>
        <strong>Import data</strong>
        <p>Go to the <strong>Import</strong> tab to load match files into the database</p>
      </div>
    </div>
    <div class="step">
      <span class="step-num">4</span>
      <div>
        <strong>Compute projections</strong>
        <p>Go to the <strong>Import</strong> tab → "Compute Projections" to run PCA + k-means</p>
      </div>
    </div>
    <div class="step">
      <span class="step-num">5</span>
      <div>
        <strong>Explore!</strong>
        <p>Use the <strong>Dashboard</strong>, <strong>Projections</strong>, and <strong>Explorer</strong> tabs</p>
      </div>
    </div>
  </div>
</div>

<!-- File Browser Modal -->
{#if browsing}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop" onclick={() => (browsing = null)}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h3>{browsing === 'db' ? 'Choose Database File' : 'Choose BMAB Directory'}</h3>
        <button class="btn" onclick={() => (browsing = null)}>✕</button>
      </div>

      <div class="browser-path">{browserPath}</div>

      <div class="browser-list">
        {#if browserLoading}
          <div class="loading">Loading...</div>
        {:else}
          {#each browserEntries as entry}
            <button
              class="browser-item"
              class:is-dir={entry.is_dir}
              ondblclick={() => handleBrowserSelect(entry)}
              onclick={() => handleBrowserSelect(entry)}
            >
              <span class="browser-icon">{entry.is_dir ? '📁' : '📄'}</span>
              {entry.name}
            </button>
          {/each}
        {/if}
      </div>

      <div class="modal-footer">
        {#if browsing === 'bmab'}
          <button class="btn primary" onclick={selectCurrentDir}>
            Select this directory
          </button>
        {/if}
        <button class="btn" onclick={() => (browsing = null)}>Cancel</button>
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
  }

  .status-badge {
    padding: 8px 12px;
    border-radius: var(--radius);
    font-size: 13px;
    margin-top: 8px;
  }

  .status-badge.ok {
    background: rgba(158, 206, 106, 0.1);
    color: var(--green);
    border: 1px solid rgba(158, 206, 106, 0.2);
  }

  .status-badge.warn {
    background: rgba(224, 175, 104, 0.1);
    color: var(--orange);
    border: 1px solid rgba(224, 175, 104, 0.2);
  }

  .steps {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .step {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 12px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }

  .step.done {
    border-color: rgba(158, 206, 106, 0.3);
    background: rgba(158, 206, 106, 0.05);
  }

  .step-num {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--bg);
    border: 1px solid var(--border);
    font-weight: 700;
    font-size: 13px;
    flex-shrink: 0;
    color: var(--accent);
  }

  .step p {
    color: var(--text-muted);
    font-size: 13px;
    margin-top: 2px;
  }

  .step code {
    background: var(--bg);
    padding: 2px 6px;
    border-radius: 3px;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--cyan);
  }

  /* Modal */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    width: 600px;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    border-bottom: 1px solid var(--border);
  }

  .modal-header h3 {
    color: var(--text);
    font-size: 14px;
  }

  .browser-path {
    padding: 8px 16px;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--cyan);
    background: var(--bg);
    border-bottom: 1px solid var(--border);
  }

  .browser-list {
    overflow-y: auto;
    max-height: 400px;
    padding: 8px;
  }

  .browser-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 6px 12px;
    border: none;
    background: none;
    color: var(--text);
    font-size: 13px;
    cursor: pointer;
    border-radius: var(--radius);
    text-align: left;
  }

  .browser-item:hover {
    background: var(--bg-hover);
  }

  .browser-item.is-dir {
    color: var(--accent);
  }

  .browser-icon {
    width: 20px;
    text-align: center;
  }

  .modal-footer {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    padding: 16px;
    border-top: 1px solid var(--border);
  }
</style>
