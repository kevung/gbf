<script>
  import { onMount } from 'svelte';
  import { fetchConfig } from './lib/api.js';
  import Setup from './views/Setup.svelte';
  import Dashboard from './views/Dashboard.svelte';
  import Projection from './views/Projection.svelte';
  import Explorer from './views/Explorer.svelte';
  import Themes from './views/Themes.svelte';
  import Help from './views/Help.svelte';

  const views = [
    { id: 'setup', label: 'Setup', icon: '⚙️' },
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'projection', label: 'Projections', icon: '🗺️' },
    { id: 'explorer', label: 'Explorer', icon: '📈' },
    { id: 'themes', label: 'Themes', icon: '🎯' },
    { id: 'help', label: 'Help', icon: '❓' },
  ];

  let currentView = $state('setup');
  let hasDB = $state(false);
  let projRefresh = $state(0);

  onMount(async () => {
    try {
      const config = await fetchConfig();
      hasDB = config.has_db;
      // If DB is already configured, go to dashboard.
      if (hasDB) currentView = 'dashboard';
    } catch (e) {
      // Stay on setup.
    }
  });
</script>

<div class="app-layout">
  <aside class="sidebar">
    <h1>GBF Explorer</h1>
    <nav>
      {#each views as v}
        <button
          class:active={currentView === v.id}
          onclick={() => {
            if (v.id === 'projection') projRefresh++;
            currentView = v.id;
          }}
        >
          <span class="icon">{v.icon}</span>
          {v.label}
        </button>
      {/each}
    </nav>
  </aside>

  <main class="main">
    <div class="view-pane" class:hidden={currentView !== 'setup'}>
      <Setup />
    </div>
    <div class="view-pane" class:hidden={currentView !== 'dashboard'}>
      {#if hasDB || currentView === 'dashboard'}
        <Dashboard />
      {/if}
    </div>
    <div class="view-pane" class:hidden={currentView !== 'projection'}>
      {#if hasDB || currentView === 'projection'}
        <Projection refreshTrigger={projRefresh} />
      {/if}
    </div>
    <div class="view-pane" class:hidden={currentView !== 'explorer'}>
      {#if hasDB || currentView === 'explorer'}
        <Explorer />
      {/if}
    </div>
    <div class="view-pane" class:hidden={currentView !== 'themes'}>
      <Themes active={currentView === 'themes'} />
    </div>
    <div class="view-pane" class:hidden={currentView !== 'help'}>
      <Help />
    </div>
  </main>
</div>
