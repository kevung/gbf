<!--
  TrajectoryMap.svelte — deck.gl UMAP position map.
  Full implementation deferred to S4.7.
  This component establishes the canvas + deck.gl scaffold.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';

  let {
    onPositionClick = (_hash: string) => {},
    filterPlayer    = '' as string,
    filterPhase     = '' as string,
    errorMin        = 0 as number,
  } = $props();

  let canvas  = $state<HTMLCanvasElement | undefined>(undefined);
  let deck: unknown = null;
  let status  = $state('Initialising…');

  // Viewport state
  let viewport = $state({
    x_min: -10, x_max: 10,
    y_min: -10, y_max: 10,
    zoom: 1,
  });

  async function loadPoints() {
    status = 'Loading points…';
    try {
      const res = await api.map.points({
        x_min: viewport.x_min, x_max: viewport.x_max,
        y_min: viewport.y_min, y_max: viewport.y_max,
        limit: 5000,
      });
      status = `${res.count} points loaded`;
      renderPoints(res.points as Array<Record<string, unknown>>);
    } catch(e) {
      status = `Error: ${e}`;
    }
  }

  function renderPoints(points: Array<Record<string, unknown>>) {
    if (!canvas || !deck) return;
    // Full deck.gl ScatterplotLayer integration done in S4.7.
    // Placeholder: draw dots on canvas via 2D context.
    const ctx = (canvas as HTMLCanvasElement).getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const W = canvas.width, H = canvas.height;
    const { x_min, x_max, y_min, y_max } = viewport;

    for (const p of points) {
      const x = ((p.umap_x as number) - x_min) / (x_max - x_min) * W;
      const y = H - ((p.umap_y as number) - y_min) / (y_max - y_min) * H;
      const e = p.move_played_error as number;
      const r = Math.floor(Math.min(e * 1000, 255));
      ctx.fillStyle = `rgba(${r},${200 - r},80,0.7)`;
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  onMount(() => {
    // deck.gl will be wired in S4.7 using DeckGL + ScatterplotLayer + PathLayer
    // For now, use canvas 2D as visual placeholder.
    if (canvas) {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
      deck = {};   // placeholder — replaced by new Deck({...}) in S4.7
      loadPoints();
    }
  });

  onDestroy(() => { deck = null; });
</script>

<div class="map-container">
  <canvas
    bind:this={canvas}
    style="width:100%;height:100%;"
    onclick={(e) => {
      // Click-to-position-hash mapping done in S4.7
      // Requires inverse viewport transform + nearest-neighbour lookup
    }}
  ></canvas>
  <div class="overlay">
    <span class="status">{status}</span>
    <p class="note">
      Full deck.gl WebGL implementation (multi-scale tiles, hexbins,
      trajectory polylines) is deferred to <strong>S4.7</strong>.
    </p>
  </div>
</div>

<style>
  .map-container { position: relative; width: 100%; height: 500px; background: #0a0505; border: 1px solid #3a2010; border-radius: 8px; overflow: hidden; }
  canvas { display: block; }
  .overlay { position: absolute; bottom: 0; left: 0; right: 0; padding: 0.6rem 1rem; background: rgba(10,5,5,0.7); }
  .status { font-size: 0.75rem; color: #907060; }
  .note { font-size: 0.75rem; color: #605040; margin: 0.2rem 0 0; font-style: italic; }
  .note strong { color: #d4a835; }
</style>
