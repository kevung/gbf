<script lang="ts">
  import { page } from '$app/stores';
  let { children } = $props();

  const nav = [
    { href: '/',           label: 'Home' },
    { href: '/explorer',   label: 'Explorer' },
    { href: '/heatmap',    label: 'Heatmap' },
    { href: '/rankings',   label: 'Rankings' },
    { href: '/catalogue',  label: 'Catalogue' },
    { href: '/cube',       label: 'Cube Helper' },
    { href: '/map',        label: 'Map' },
  ];
</script>

<div class="app">
  <nav>
    <a href="/" class="brand">♟ GBF</a>
    {#each nav as { href, label }}
      <a {href} class:active={$page.url.pathname === href}>{label}</a>
    {/each}
  </nav>

  <main>
    {@render children()}
  </main>
</div>

<style>
  .app { display: flex; flex-direction: column; min-height: 100vh; background: #0f0f0f; color: #e0d0c0; font-family: sans-serif; }
  nav { display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 1.2rem; background: #1a0f07; border-bottom: 1px solid #3a2010; flex-wrap: wrap; }
  .brand { font-weight: bold; font-size: 1.1rem; color: #d4a835; text-decoration: none; margin-right: 1rem; }
  nav a { color: #b09070; text-decoration: none; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.9rem; }
  nav a:hover, nav a.active { background: #3a2010; color: #f0c060; }
  main { flex: 1; padding: 1.5rem; max-width: 1400px; width: 100%; margin: 0 auto; }
</style>
