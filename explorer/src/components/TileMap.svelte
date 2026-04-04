<script>
  /**
   * TileMap — deck.gl ScatterplotLayer renderer backed by the GBF tile API.
   *
   * The tile API returns pre-computed gzipped JSON tiles whose points have
   * coordinates normalised to [0,1]². We maintain a simple pan/zoom viewport
   * (scale + translate) so tiles are selected and rendered at appropriate
   * detail levels as the user navigates.
   *
   * LoD → zoom mapping (mirrors tiles.go LoDZoomRange):
   *   LoD 0 → z 0–2   (overview,  ≤16 tiles)
   *   LoD 1 → z 3–5   (medium,  ≤1024 tiles)
   *   LoD 2 → z 6–8   (full,  ≤65536 tiles)
   *
   * The deck.gl ScatterplotLayer handles WebGL rendering, which scales to
   * millions of points without main-thread overhead.
   */
  import { onMount, onDestroy } from 'svelte';
  import { Deck, OrthographicView } from '@deck.gl/core';
  import { ScatterplotLayer } from '@deck.gl/layers';
  import { fetchTile, fetchTileMeta } from '../lib/api.js';

  // ── Props ─────────────────────────────────────────────────────────────────

  let {
    method = 'umap_2d',
    lod = 0,
    colorBy = 'cluster_id',  // 'cluster_id' | 'pos_class' | 'away_x' | 'away_o'
    height = '100%',
    onPointClick = null,
  } = $props();

  // ── State ─────────────────────────────────────────────────────────────────

  let canvas;
  let deck;
  let tileMeta = $state(null);
  let loading = $state(false);
  let error = $state(null);
  let pointCount = $state(0);

  // Viewport: zoom level (integer, controls which tile zoom to request) and
  // pan offset in normalised [0,1]² space.
  let zoom = $state(0);           // deck.gl zoom (continuous)
  let tileZoom = $state(0);       // integer tile zoom to request
  let points = $state([]);        // accumulated tile points for current view

  // Cache: Map<tileKey, TilePoint[]>
  const tileCache = new Map();

  // ── Color palettes ────────────────────────────────────────────────────────

  const CLUSTER_COLORS = [
    [122, 162, 247], [158, 206, 106], [247, 118, 142], [255, 158, 100],
    [187, 154, 247], [125, 207, 255], [224, 175, 104], [115, 218, 202],
    [192, 202, 245], [154, 165, 206],
  ];
  const CLASS_COLORS = [
    [247, 118, 142],  // contact — red
    [122, 162, 247],  // race — blue
    [158, 206, 106],  // bearoff — green
  ];

  function pointColor(pt) {
    if (colorBy === 'pos_class') {
      return CLASS_COLORS[pt.pc ?? 0] ?? [150, 150, 150];
    }
    if (colorBy === 'cluster_id') {
      const c = pt.c ?? -1;
      if (c < 0) return [86, 95, 137]; // noise — muted
      return CLUSTER_COLORS[c % CLUSTER_COLORS.length];
    }
    // away_x / away_o: heatmap blue→red by value 0–?
    const val = colorBy === 'away_x' ? (pt.away_x ?? 0) : (pt.away_o ?? 0);
    const t = Math.min(1, val / 15);
    return [
      Math.round(122 + t * (247 - 122)),
      Math.round(162 - t * 162),
      Math.round(247 - t * 247),
    ];
  }

  // ── Tile loading ──────────────────────────────────────────────────────────

  /**
   * Map a deck.gl continuous zoom to the integer tile zoom within the LoD range.
   */
  function lodZoomRange(l) {
    if (l === 0) return { min: 0, max: 2 };
    if (l === 1) return { min: 3, max: 5 };
    return { min: 6, max: 8 };
  }

  function deckZoomToTileZoom(deckZ, l) {
    const { min, max } = lodZoomRange(l);
    // deckZ 0 → tile min; grows with viewport zoom
    const tz = min + Math.round(Math.max(0, deckZ));
    return Math.min(max, tz);
  }

  /**
   * Load all tiles at tileZoom z for the given LoD.
   * Returns flattened array of TilePoint[].
   */
  async function loadTiles(meth, l, z) {
    const count = 1 << z; // 2^z tiles per axis
    const jobs = [];
    for (let tx = 0; tx < count; tx++) {
      for (let ty = 0; ty < count; ty++) {
        const key = `${meth}:${l}:${z}:${tx}:${ty}`;
        if (!tileCache.has(key)) {
          jobs.push({ tx, ty, key });
        }
      }
    }
    if (jobs.length === 0) return buildPoints(meth, l, z);

    await Promise.all(
      jobs.map(async ({ tx, ty, key }) => {
        try {
          const pts = await fetchTile(meth, l, z, tx, ty);
          tileCache.set(key, pts);
        } catch {
          tileCache.set(key, []);
        }
      })
    );

    return buildPoints(meth, l, z);
  }

  function buildPoints(meth, l, z) {
    const count = 1 << z;
    const all = [];
    for (let tx = 0; tx < count; tx++) {
      for (let ty = 0; ty < count; ty++) {
        const key = `${meth}:${l}:${z}:${tx}:${ty}`;
        const pts = tileCache.get(key) || [];
        for (const pt of pts) all.push(pt);
      }
    }
    return all;
  }

  async function reload() {
    if (!tileMeta) return;
    loading = true;
    error = null;
    try {
      const tz = deckZoomToTileZoom(zoom, lod);
      tileZoom = tz;
      const pts = await loadTiles(method, lod, tz);
      points = pts;
      pointCount = pts.length;
    } catch (e) {
      error = e.message;
    }
    loading = false;
    updateLayer();
  }

  // ── deck.gl setup ─────────────────────────────────────────────────────────

  /**
   * Map normalised [0,1]² coordinates to deck.gl world coordinates.
   * OrthographicView uses pixel coordinates; we scale [0,1] to a fixed canvas size.
   */
  const WORLD = 512; // world size in deck.gl coords

  function worldCoords(pt) {
    return [pt.x * WORLD, pt.y * WORLD];
  }

  function makeLayer(pts) {
    return new ScatterplotLayer({
      id: 'tilemap-scatter',
      data: pts,
      getPosition: (pt) => worldCoords(pt),
      getRadius: 2.5,
      getFillColor: (pt) => pointColor(pt),
      opacity: 0.7,
      pickable: true,
      radiusUnits: 'pixels',
      updateTriggers: {
        getFillColor: [colorBy],
      },
    });
  }

  function updateLayer() {
    if (!deck) return;
    deck.setProps({ layers: [makeLayer(points)] });
  }

  onMount(async () => {
    // Load tile meta to confirm tiles exist.
    try {
      tileMeta = await fetchTileMeta(method, lod);
    } catch {
      // No tiles yet — show placeholder.
    }

    deck = new Deck({
      canvas,
      views: new OrthographicView({ id: 'ortho', controller: true }),
      initialViewState: {
        target: [WORLD / 2, WORLD / 2, 0],
        zoom: -1,
      },
      layers: [],
      onViewStateChange: ({ viewState }) => {
        const newTZ = deckZoomToTileZoom(viewState.zoom + 1, lod);
        if (newTZ !== tileZoom) {
          zoom = viewState.zoom + 1;
          reload();
        }
      },
      onClick: ({ object }) => {
        if (object && onPointClick) {
          onPointClick({ position_id: object.id });
        }
      },
    });

    if (tileMeta) {
      await reload();
    }
  });

  onDestroy(() => {
    deck?.finalize();
    deck = null;
  });

  // Reload when method / lod / colorBy changes.
  $effect(() => {
    tileCache.clear();
    tileMeta = null;
    points = [];
    pointCount = 0;
    zoom = 0;
    tileZoom = 0;

    fetchTileMeta(method, lod)
      .then((m) => {
        tileMeta = m;
        if (m) reload();
        else updateLayer();
      })
      .catch(() => {
        tileMeta = null;
        updateLayer();
      });
  });

  // Redraw when colorBy changes without reloading tiles.
  $effect(() => {
    void colorBy;
    updateLayer();
  });
</script>

<div class="tilemap-wrap" style="height:{height};position:relative;">
  <canvas bind:this={canvas} style="width:100%;height:100%;display:block;"></canvas>

  {#if loading}
    <div class="tilemap-overlay">Loading tiles…</div>
  {:else if error}
    <div class="tilemap-overlay error">{error}</div>
  {:else if !tileMeta}
    <div class="tilemap-overlay muted">No tiles available. Compute a projection first.</div>
  {/if}

  <div class="tilemap-info">
    {#if pointCount > 0}
      <span>{pointCount.toLocaleString()} pts · z{tileZoom}</span>
    {/if}
  </div>
</div>

<style>
  .tilemap-wrap {
    min-height: 300px;
    background: #1a1b26;
    border-radius: var(--radius);
    overflow: hidden;
  }
  .tilemap-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 13px;
    pointer-events: none;
  }
  .tilemap-overlay.error { color: var(--red); }
  .tilemap-overlay.muted { color: var(--text-muted); }
  .tilemap-info {
    position: absolute;
    bottom: 8px;
    left: 10px;
    font-size: 11px;
    color: var(--text-muted);
    pointer-events: none;
  }
</style>
