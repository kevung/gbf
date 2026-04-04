<script>
  import { startImport, subscribeImportProgress, startProjectionCompute, subscribeProjectionProgress, formatNumber } from '../lib/api.js';

  let proportion = $state(1);
  let batchSize = $state(100);
  let importing = $state(false);
  let events = $state([]);
  let error = $state(null);
  let result = $state(null);
  let unsubscribe = null;

  // Projection compute state
  let projK = $state(8);
  let projSample = $state(0);
  let projComputing = $state(false);
  let projEvents = $state([]);
  let projError = $state(null);
  let projUnsubscribe = null;

  function handleStart() {
    error = null;
    result = null;
    events = [];
    importing = true;

    startImport(proportion / 100, batchSize)
      .then((resp) => {
        result = resp;
        // Start listening for progress
        unsubscribe = subscribeImportProgress(
          (evt) => {
            events = [...events, evt];
          },
          (final) => {
            importing = false;
            if (final.error) error = final.error;
          }
        );
      })
      .catch((e) => {
        error = e.message;
        importing = false;
      });
  }

  function handleStop() {
    if (unsubscribe) {
      unsubscribe();
      unsubscribe = null;
    }
    importing = false;
  }

  function handleComputeProjections() {
    projError = null;
    projEvents = [];
    projComputing = true;

    startProjectionCompute('pca_2d', projK, projSample)
      .then(() => {
        projUnsubscribe = subscribeProjectionProgress(
          (evt) => {
            projEvents = [...projEvents, evt];
          },
          (final) => {
            projComputing = false;
            if (final.error) projError = final.error;
          }
        );
      })
      .catch((e) => {
        projError = e.message;
        projComputing = false;
      });
  }

  let lastEvent = $derived(events.length > 0 ? events[events.length - 1] : null);
  let progressPct = $derived(
    lastEvent && lastEvent.files_total > 0
      ? Math.round((lastEvent.files_done / lastEvent.files_total) * 100)
      : 0
  );
  let lastProjEvent = $derived(projEvents.length > 0 ? projEvents[projEvents.length - 1] : null);
</script>

<div class="card">
  <h2>Import BMAB Data</h2>
  <p style="color:var(--text-muted); margin-bottom:16px">
    Import XG files from the BMAB dataset. Choose the proportion of files to import.
  </p>

  <div class="controls">
    <label>
      Proportion (%)
      <input type="number" bind:value={proportion} min="0.1" max="100" step="0.1" style="width:100px" />
    </label>

    <label>
      Batch size
      <select bind:value={batchSize}>
        <option value={50}>50</option>
        <option value={100}>100</option>
        <option value={200}>200</option>
        <option value={500}>500</option>
      </select>
    </label>

    {#if !importing}
      <button class="btn primary" onclick={handleStart}>Start Import</button>
    {:else}
      <button class="btn" style="border-color:var(--red); color:var(--red)" onclick={handleStop}>
        Cancel
      </button>
    {/if}
  </div>
</div>

{#if error}
  <div class="card" style="border-color:var(--red); margin-top:16px">
    <h2 style="color:var(--red)">Error</h2>
    <p style="color:var(--red)">{error}</p>
  </div>
{/if}

{#if result}
  <div class="card" style="margin-top:16px">
    <h2>Import Status</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Total files</div>
        <div class="value">{formatNumber(result.files)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Files to import</div>
        <div class="value">{formatNumber(result.limit)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Proportion</div>
        <div class="value">{(result.proportion * 100).toFixed(1)}%</div>
      </div>
    </div>
  </div>
{/if}

{#if lastEvent}
  <div class="card" style="margin-top:16px">
    <h2>Progress</h2>
    <div class="progress-bar" style="margin-bottom:12px">
      <div class="fill" style="width:{progressPct}%"></div>
    </div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Files done</div>
        <div class="value">{formatNumber(lastEvent.files_done)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Positions</div>
        <div class="value">{formatNumber(lastEvent.positions)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Rate</div>
        <div class="value">{lastEvent.rate?.toFixed(0) || '—'} pos/s</div>
      </div>
      <div class="stat-card">
        <div class="label">Elapsed</div>
        <div class="value" style="font-size:14px">{lastEvent.elapsed}</div>
      </div>
      <div class="stat-card">
        <div class="label">Remaining</div>
        <div class="value" style="font-size:14px">{lastEvent.remaining || '—'}</div>
      </div>
      <div class="stat-card">
        <div class="label">Status</div>
        <div class="value" style="font-size:14px; color:{lastEvent.done ? 'var(--green)' : 'var(--orange)'}">
          {lastEvent.done ? '✅ Done' : '⏳ Running'}
        </div>
      </div>
    </div>
  </div>

  {#if events.length > 1}
    <div class="card" style="margin-top:16px">
      <h2>Import Log (last 10)</h2>
      <table>
        <thead>
          <tr><th>Time</th><th>Files</th><th>Positions</th><th>Rate</th><th>Elapsed</th></tr>
        </thead>
        <tbody>
          {#each events.slice(-10).reverse() as evt}
            <tr>
              <td>{new Date(evt.time).toLocaleTimeString()}</td>
              <td>{evt.files_done}</td>
              <td>{formatNumber(evt.positions)}</td>
              <td>{evt.rate?.toFixed(0) || '—'}</td>
              <td>{evt.elapsed}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
{/if}

<!-- Projection Compute Section -->
<div class="card" style="margin-top:24px">
  <h2>Compute Projections (PCA + K-Means)</h2>
  <p style="color:var(--text-muted); margin-bottom:16px">
    Compute PCA 2D projections and k-means clustering directly from database positions.
    No Python required — runs entirely within the application.
  </p>

  <div class="controls">
    <label>
      Clusters (k)
      <input type="number" bind:value={projK} min="2" max="50" step="1" style="width:80px" />
    </label>

    <label>
      Sample size (0 = all)
      <input type="number" bind:value={projSample} min="0" step="1000" style="width:120px" />
    </label>

    {#if !projComputing}
      <button class="btn primary" onclick={handleComputeProjections}>
        Compute Projections
      </button>
    {:else}
      <button class="btn" disabled>⏳ Computing...</button>
    {/if}
  </div>
</div>

{#if projError}
  <div class="card" style="border-color:var(--red); margin-top:16px">
    <p style="color:var(--red); margin:0">{projError}</p>
  </div>
{/if}

{#if lastProjEvent}
  <div class="card" style="margin-top:16px">
    <h2>Projection Progress</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Stage</div>
        <div class="value" style="font-size:14px">{lastProjEvent.stage}</div>
      </div>
      <div class="stat-card">
        <div class="label">Progress</div>
        <div class="value">{lastProjEvent.percent}%</div>
      </div>
      <div class="stat-card">
        <div class="label">Status</div>
        <div class="value" style="font-size:14px; color:{lastProjEvent.done ? (lastProjEvent.error ? 'var(--red)' : 'var(--green)') : 'var(--orange)'}">
          {lastProjEvent.done ? (lastProjEvent.error ? '❌ Error' : '✅ Done') : '⏳ Running'}
        </div>
      </div>
    </div>
    {#if lastProjEvent.message}
      <p style="color:var(--green); margin-top:12px">{lastProjEvent.message}</p>
    {/if}

    {#if projEvents.length > 1}
      <table style="margin-top:12px">
        <thead>
          <tr><th>Time</th><th>Stage</th><th>Progress</th></tr>
        </thead>
        <tbody>
          {#each projEvents.slice(-10).reverse() as evt}
            <tr>
              <td>{new Date(evt.time).toLocaleTimeString()}</td>
              <td>{evt.stage}</td>
              <td>{evt.percent}%</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{/if}
