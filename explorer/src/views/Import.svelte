<script>
  import { startImport, subscribeImportProgress, formatNumber } from '../lib/api.js';

  let proportion = $state(1);
  let batchSize = $state(100);
  let importing = $state(false);
  let events = $state([]);
  let error = $state(null);
  let result = $state(null);
  let unsubscribe = null;

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

  let lastEvent = $derived(events.length > 0 ? events[events.length - 1] : null);
  let progressPct = $derived(
    lastEvent && lastEvent.files_total > 0
      ? Math.round((lastEvent.files_done / lastEvent.files_total) * 100)
      : 0
  );
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
