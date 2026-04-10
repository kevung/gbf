<!--
  TrajectoryMap.svelte — S4.7 deck.gl WebGL position map.

  Rendering modes (OrthographicView, UMAP coordinate space):
    zoom < 3  → hexbins coarse  (resolution 8)   — ScatterplotLayer large circles
    zoom 3–7  → hexbins fine    (resolution 30)   — ScatterplotLayer medium circles
    zoom ≥ 8  → individual points (max 5 000)     — ScatterplotLayer small dots
  Trajectories: PathLayer, fetched on point/hexbin click.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';

  // ── Props ──────────────────────────────────────────────────────────────────
  let {
    onCrossroadSelect = (_hash: string) => {},
    filterPlayer  = '' as string,
    filterPhase   = '' as string,
    errorMin      = 0  as number,
    colorBy       = 'density' as 'density' | 'avg_error' | 'cluster',
    showTrajectories = true  as boolean,
    compareMode   = false    as boolean,
    comparePlayer1 = '' as string,
    comparePlayer2 = '' as string,
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────
  let container  = $state<HTMLDivElement | undefined>(undefined);
  let status     = $state('Initialising…');
  let zoom       = $state(2);
  let deckInst: { setProps: (p: object) => void; finalize?: () => void } | null = null;

  let hexbins   = $state<Record<string, unknown>[]>([]);
  let points    = $state<Record<string, unknown>[]>([]);
  let trajs     = $state<{ path: [number, number][]; color: [number, number, number] }[]>([]);
  let fetchTimer: ReturnType<typeof setTimeout> | null = null;

  // Viewport bounds (UMAP units), updated on every viewState change
  let bounds = { x_min: -15, x_max: 15, y_min: -15, y_max: 15 };

  // ── Render mode ────────────────────────────────────────────────────────────
  function renderMode(z: number) {
    return z < 3 ? 'coarse' : z < 8 ? 'fine' : 'points';
  }

  // ── Colour helpers ─────────────────────────────────────────────────────────
  const CLUSTER_PAL: [number, number, number][] = [
    [215, 168, 53], [80, 200, 120], [100, 160, 255],
    [255, 140, 60], [200, 80, 200], [60, 200, 200], [255, 90, 90],
  ];

  function dotColor(d: Record<string, unknown>): [number, number, number, number] {
    if (colorBy === 'cluster') {
      const cid = ((d.dominant_cluster ?? d.cluster_id ?? 0) as number) % CLUSTER_PAL.length;
      const [r, g, b] = CLUSTER_PAL[cid];
      return [r, g, b, 210];
    }
    const e = ((d.avg_error ?? d.move_played_error ?? 0) as number);
    const t = Math.min(e / 0.12, 1);
    return [Math.round(230 * t), Math.round(180 * (1 - t)), 60, 200];
  }

  function dotRadius(d: Record<string, unknown>, mode: string): number {
    if (mode === 'points') return 0.10;
    const n = (d.count as number) ?? 1;
    const base = mode === 'coarse' ? 2.0 : 0.8;
    return base + Math.sqrt(n) * (mode === 'coarse' ? 0.5 : 0.2);
  }

  // ── Bounds from viewState ──────────────────────────────────────────────────
  function updateBounds(vs: { target: number[]; zoom: number }) {
    zoom = vs.zoom;
    const scale = Math.pow(2, vs.zoom);
    const W = container?.clientWidth  ?? 900;
    const H = container?.clientHeight ?? 500;
    const hw = W / scale / 2;
    const hh = H / scale / 2;
    bounds = {
      x_min: vs.target[0] - hw, x_max: vs.target[0] + hw,
      y_min: vs.target[1] - hh, y_max: vs.target[1] + hh,
    };
  }

  // ── Data fetching ──────────────────────────────────────────────────────────
  function scheduleFetch() {
    if (fetchTimer) clearTimeout(fetchTimer);
    fetchTimer = setTimeout(doFetch, 200);
  }

  async function doFetch() {
    const mode = renderMode(zoom);
    try {
      if (mode === 'points') {
        const res = await api.map.points({
          ...bounds, limit: 5000,
          ...(filterPlayer && { player: filterPlayer }),
        });
        points  = res.points as Record<string, unknown>[];
        hexbins = [];
        status  = `${points.length} points`;
      } else {
        const resolution = mode === 'coarse' ? 8 : 30;
        const res = await api.map.hexbins({
          ...bounds, resolution, color_by: colorBy,
        });
        hexbins = res.hexbins as Record<string, unknown>[];
        points  = [];
        status  = `${hexbins.length} bins`;
      }
    } catch (e) {
      status = `Error: ${e}`;
    }
    pushLayers();
  }

  // ── Trajectory fetch on click ──────────────────────────────────────────────
  async function onPointClick(hash: string) {
    if (!hash) return;
    onCrossroadSelect(hash);
    if (!showTrajectories) return;
    try {
      let raw: { trajectories: unknown[] };
      if (compareMode && comparePlayer1 && comparePlayer2) {
        const res = await api.map.trajectoryCompare(hash, comparePlayer1, comparePlayer2);
        const p1t = (res.player1 as { trajectories: unknown[] }).trajectories;
        const p2t = (res.player2 as { trajectories: unknown[] }).trajectories;
        trajs = [
          ...buildLines(p1t, [64, 120, 255]),
          ...buildLines(p2t, [255, 100, 64]),
        ];
      } else {
        raw = await api.map.trajectories(hash, { limit: 60 });
        trajs = buildLines(raw.trajectories, [220, 200, 40]);
      }
    } catch {}
    pushLayers();
  }

  function buildLines(
    trajData: unknown[],
    baseColor: [number, number, number],
  ): { path: [number, number][]; color: [number, number, number] }[] {
    return (trajData as Array<{ waypoints: Array<{ umap_x: number; umap_y: number }> }>)
      .map(t => ({
        path:  t.waypoints.map(w => [w.umap_x, w.umap_y] as [number, number]),
        color: baseColor,
      }))
      .filter(t => t.path.length >= 2);
  }

  // ── deck.gl layer construction ─────────────────────────────────────────────
  function pushLayers() {
    if (!deckInst) return;
    const mode = renderMode(zoom);
    // Import lazily — already resolved after onMount
    import('@deck.gl/layers').then(({ ScatterplotLayer, PathLayer }) => {
      const data = mode === 'points' ? points : hexbins;
      const scatter = new ScatterplotLayer({
        id:            'scatter',
        data,
        getPosition:   (d: Record<string, unknown>) => [
          (d.umap_x ?? d.hex_x ?? 0) as number,
          (d.umap_y ?? d.hex_y ?? 0) as number,
        ],
        getRadius:     (d: Record<string, unknown>) => dotRadius(d, mode),
        getFillColor:  (d: Record<string, unknown>) => dotColor(d),
        radiusUnits:   'common',
        pickable:      true,
        onClick:       ({ object }: { object: Record<string, unknown> }) => {
          const hash = (object?.position_hash ?? object?.hex_id ?? '') as string;
          onPointClick(hash);
        },
        updateTriggers: { getFillColor: [colorBy], getRadius: [zoom] },
      });

      const paths = showTrajectories && trajs.length
        ? new PathLayer({
            id:            'trajectories',
            data:          trajs,
            getPath:       (d: { path: [number, number][] }) => d.path,
            getColor:      (d: { color: [number, number, number] }) => [...d.color, 180],
            getWidth:      0.12,
            widthUnits:    'common',
            capRounded:    true,
            jointRounded:  true,
            pickable:      false,
          })
        : null;

      deckInst!.setProps({ layers: paths ? [scatter, paths] : [scatter] });
    });
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  onMount(async () => {
    const { Deck, OrthographicView } = await import('@deck.gl/core');

    deckInst = new Deck({
      parent: container,
      views:  new OrthographicView({ id: 'main', controller: true }),
      initialViewState: {
        target:  [0, 0, 0] as [number, number, number],
        zoom:    2,
        minZoom: -2,
        maxZoom: 14,
      },
      onViewStateChange: ({ viewState }: { viewState: { target: number[]; zoom: number } }) => {
        updateBounds(viewState);
        scheduleFetch();
      },
      getTooltip: ({ object }: { object: Record<string, unknown> | null }) => {
        if (!object) return null;
        const e = (object.avg_error ?? object.move_played_error) as number | undefined;
        const n = object.count as number | undefined;
        return {
          html: [
            n    ? `<b>${n.toLocaleString()} positions</b>` : '',
            e    ? `avg error: ${e.toFixed(4)}` : '',
          ].filter(Boolean).join('<br>'),
          style: { background: '#1a0f07', color: '#e0d0c0', fontSize: '12px', padding: '6px 10px', borderRadius: '4px' },
        };
      },
      layers: [],
      width:  '100%',
      height: '100%',
      style:  { position: 'absolute', inset: '0' },
    }) as typeof deckInst;

    // Initial fetch
    updateBounds({ target: [0, 0, 0], zoom: 2 });
    await doFetch();
  });

  onDestroy(() => {
    if (deckInst?.finalize) deckInst.finalize();
  });

  // Re-fetch when filters change
  $effect(() => {
    filterPlayer; filterPhase; errorMin; colorBy; showTrajectories;
    if (deckInst) scheduleFetch();
  });
</script>

<!-- ── DOM ──────────────────────────────────────────────────────────────── -->
<div class="map-outer">
  <div bind:this={container} class="map-canvas"></div>

  <!-- Zoom mode badge -->
  <div class="badge">
    {#if zoom < 3}🌍 Global (hexbins)
    {:else if zoom < 8}🔍 Regional (hexbins)
    {:else}📍 Detail (points){/if}
    &nbsp;·&nbsp; {status}
  </div>

  <!-- Zoom controls -->
  <div class="zoom-ctrl">
    <button onclick={() => { zoom += 1; deckInst?.setProps({initialViewState: {zoom: zoom + 1}}); scheduleFetch(); }}>＋</button>
    <button onclick={() => { zoom -= 1; deckInst?.setProps({initialViewState: {zoom: zoom - 1}}); scheduleFetch(); }}>－</button>
  </div>

  <!-- Colour legend -->
  {#if colorBy !== 'cluster'}
    <div class="legend">
      <span class="lo">low error</span>
      <div class="grad"></div>
      <span class="hi">high error</span>
    </div>
  {:else}
    <div class="legend cluster">
      {#each ['Contact', 'Race', 'Bearoff', 'Other'] as lbl, i}
        <span><span class="dot" style="background:rgb({CLUSTER_PAL[i%CLUSTER_PAL.length].join(',')})"></span>{lbl}</span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .map-outer  { position: relative; width: 100%; height: 520px; background: #06040a; border: 1px solid #3a2010; border-radius: 8px; overflow: hidden; }
  .map-canvas { position: absolute; inset: 0; }
  .badge      { position: absolute; top: 10px; left: 12px; background: rgba(10,5,5,.8); color: #a08060; font-size: 0.75rem; padding: 4px 10px; border-radius: 12px; pointer-events: none; }
  .zoom-ctrl  { position: absolute; top: 10px; right: 12px; display: flex; flex-direction: column; gap: 4px; }
  .zoom-ctrl button { width: 32px; height: 32px; background: rgba(26,15,7,.9); border: 1px solid #3a2010; border-radius: 4px; color: #d4a835; font-size: 1.1rem; cursor: pointer; line-height: 1; }
  .zoom-ctrl button:hover { background: #3a2010; }
  .legend     { position: absolute; bottom: 12px; left: 12px; display: flex; align-items: center; gap: 6px; font-size: 0.72rem; color: #907060; background: rgba(10,5,5,.75); padding: 4px 8px; border-radius: 8px; pointer-events: none; }
  .grad       { width: 80px; height: 10px; border-radius: 3px; background: linear-gradient(to right, #3cc878, #e6b43c, #e63c3c); }
  .legend.cluster { gap: 10px; flex-wrap: wrap; }
  .legend.cluster span { display: flex; align-items: center; gap: 4px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
</style>
