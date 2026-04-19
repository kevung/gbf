<script>
  /**
   * BE.9 — Barycentric coordinator view.
   * Three sub-tabs: Global Scatter, Score Clouds, Match Trajectory.
   * Hosts the shared SelectionPanel overlay and wires the stores.
   */
  import { onMount }                         from 'svelte';
  import { selectionStore, matchInFocus }    from '../lib/selection-store.js';
  import { fetchScatter }                    from '../lib/bary-api.js';
  import BaryGlobalScatter   from './BaryGlobalScatter.svelte';
  import BaryScoreClouds     from './BaryScoreClouds.svelte';
  import BaryMatchTrajectory from './BaryMatchTrajectory.svelte';
  import SelectionPanel      from '../components/SelectionPanel.svelte';

  // ── State ──────────────────────────────────────────────────────────────────

  let subTab = $state('global');   // 'global' | 'clouds' | 'trajectory'

  // Background scatter shared with TrajectoryCanvas (fetched once)
  let bgPoints = $state([]);

  onMount(() => {
    fetchScatter({ mode: 'global', limit: 2000 })
      .then(d => { bgPoints = d.points ?? []; })
      .catch(() => {});
  });

  // Show/hide selection panel
  let showPanel = $state(false);

  // Mirror store into local reactive so panel reacts
  let selection = $state(null);
  selectionStore.subscribe(s => {
    selection = s;
    if (s && s.positions?.length > 0) showPanel = true;
  });

  // When "Trace match" fires in BE.8, auto-switch to trajectory
  matchInFocus.subscribe(id => {
    if (id) subTab = 'trajectory';
  });

  // ── Handlers ───────────────────────────────────────────────────────────────

  function onSelectionChange(sel) {
    selectionStore.set({ ...sel, loading: false });
  }
</script>

<div class="bary-coordinator">

  <!-- Sub-tab nav -->
  <nav class="sub-tabs">
    <button class:active={subTab === 'global'}
            onclick={() => subTab = 'global'}>
      Global scatter
    </button>
    <button class:active={subTab === 'clouds'}
            onclick={() => subTab = 'clouds'}>
      Score clouds
    </button>
    <button class:active={subTab === 'trajectory'}
            onclick={() => subTab = 'trajectory'}>
      Match trajectory
    </button>
  </nav>

  <!-- Main area: sub-view + optional side panel -->
  <div class="body" class:with-panel={showPanel}>

    <!-- Sub-views (kept mounted to preserve state) -->
    <div class="sub-view" class:hidden={subTab !== 'global'}>
      <BaryGlobalScatter {onSelectionChange} />
    </div>
    <div class="sub-view" class:hidden={subTab !== 'clouds'}>
      <BaryScoreClouds {onSelectionChange} />
    </div>
    <div class="sub-view" class:hidden={subTab !== 'trajectory'}>
      <BaryMatchTrajectory
        positionId={$matchInFocus}
        backgroundPoints={bgPoints}
      />
    </div>

    <!-- Selection panel (right column) -->
    {#if showPanel}
      <div class="panel-col">
        <SelectionPanel
          {selection}
          onClose={() => showPanel = false}
        />
      </div>
    {/if}
  </div>

</div>

<style>
  .bary-coordinator {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #1a1b26;
    color: #c0caf5;
  }

  /* ── Sub-tabs ── */
  .sub-tabs {
    display: flex;
    gap: 0;
    background: #1e2030;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
  }
  .sub-tabs button {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #565f89;
    padding: 7px 16px;
    cursor: pointer;
    font-size: 12px;
    white-space: nowrap;
    transition: color 0.12s, border-color 0.12s;
  }
  .sub-tabs button:hover  { color: #c0caf5; }
  .sub-tabs button.active { color: #7aa2f7; border-bottom-color: #7aa2f7; }

  /* ── Body layout ── */
  .body {
    flex: 1;
    display: flex;
    min-height: 0;
    overflow: hidden;
  }
  .body.with-panel .sub-view { flex: 1; }
  .sub-view {
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .sub-view.hidden { display: none; }

  .panel-col {
    width: 320px;
    flex-shrink: 0;
    min-height: 0;
    overflow: hidden;
  }
</style>
