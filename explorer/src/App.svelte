<script>
  import { onMount } from 'svelte';
  import { fetchConfig } from './lib/api.js';
  import Setup from './views/Setup.svelte';
  import Dashboard from './views/Dashboard.svelte';
  import Projection from './views/Projection.svelte';
  import Explorer from './views/Explorer.svelte';
  import Import from './views/Import.svelte';
  import Help from './views/Help.svelte';

  const views = [
    { id: 'setup', label: 'Setup', icon: '⚙️' },
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'projection', label: 'Projections', icon: '🗺️' },
    { id: 'explorer', label: 'Explorer', icon: '📈' },
    { id: 'import', label: 'Import', icon: '📥' },
    { id: 'help', label: 'Help', icon: '❓' },
  ];

  let currentView = $state('setup');
  let hasDB = $state(false);

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
          onclick={() => (currentView = v.id)}
        >
          <span class="icon">{v.icon}</span>
          {v.label}
        </button>
      {/each}
    </nav>
  </aside>

  <main class="main">
    {#if currentView === 'setup'}
      <Setup />
    {:else if currentView === 'dashboard'}
      <Dashboard />
    {:else if currentView === 'projection'}
      <Projection />
    {:else if currentView === 'explorer'}
      <Explorer />
    {:else if currentView === 'import'}
      <Import />
    {:else if currentView === 'help'}
      <Help />
    {/if}
  </main>
</div>
