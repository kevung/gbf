<script>
  /**
   * BE.5 — Global Scatter View
   *
   * Canvas-based interactive scatter of all barycentric positions in score
   * space.  Supports pan/zoom, rectangle selection (Shift-drag) and optional
   * per-cell σ ellipses from the bootstrap aggregates.
   */
  import { onMount } from 'svelte';
  import { fetchScatter, fetchCells, postSelect } from '../lib/bary-api.js';
  import { SUPPORTED_COLOR_FIELDS }               from '../lib/color-scales.js';
  import { drawScatter, drawSigmaEllipses,
           xyToScreen, screenToXy }               from '../lib/canvas-bary.js';

  // ── Props ──────────────────────────────────────────────────────────────────

  let { onSelectionChange = null } = $props();

  // ── Reactive state ─────────────────────────────────────────────────────────

  let points  = $state([]);
  let cells   = $state([]);
  let loading = $state(true);
  let error   = $state(null);

  let colorBy   = $state('mwc_p1');
  let showSigma = $state(false);
  let sigmaK    = $state(2);

  let filters = $state({
    variant:       'all',
    cubeMin:       1,
    cubeMax:       64,
    decisionTypes: [],
  });

  // Viewport in data space: x = bary_p1_b, y = bary_p1_a, both ∈ [-0.5, 16]
  let viewport = $state({ x: -0.5, y: -0.5, w: 16.5, h: 16.5 });

  let hovered   = $state(null);
  let selection = $state(null); // { rect, total, positions }
  let selecting = $state(false);

  // ── Non-reactive interaction state ─────────────────────────────────────────

  let canvas;
  let animFrame = null;
  let dragState = null;      // { type:'pan'|'select', startX, startY, startVP }
  let selRectScreen = null;  // { x0, y0, x1, y1 } in CSS pixels — set during selection

  // Hover grid: 256×256 bucketed index over data space
  let hoverGrid      = null;
  let hoverGridBasis = null; // tracks which points/viewport the grid was built for
  const GRID_N = 256;

  // ── Derived ────────────────────────────────────────────────────────────────

  let filteredPoints = $derived(
    filters.variant === 'all'
      ? points
      : points.filter(p => p.crawford_variant === filters.variant)
  );

  // Tooltip string for the hovered point
  let tooltip = $derived(
    hovered
      ? `${hovered.score_away_p1}a-${hovered.score_away_p2}a` +
        `  MWC ${(hovered.mwc_p1 ?? 0).toFixed(3)}` +
        `  Δcube ${(hovered.cube_gap_p1 ?? 0).toFixed(3)}`
      : null
  );

  // ── Mount ──────────────────────────────────────────────────────────────────

  onMount(() => {
    const ro = new ResizeObserver(() => scheduleRedraw());
    ro.observe(canvas);

    (async () => {
      try {
        const [scatter, cellAgg] = await Promise.all([
          fetchScatter({ mode: 'global', per_cell: 500 }),
          fetchCells({ sampling: 'bootstrap' }),
        ]);
        points = scatter.points ?? [];
        cells  = cellAgg.cells  ?? [];
      } catch (e) {
        error = e.message;
      } finally {
        loading = false;
        scheduleRedraw();
      }
    })();

    return () => {
      ro.disconnect();
      if (animFrame) cancelAnimationFrame(animFrame);
    };
  });

  // ── Reactive redraws ───────────────────────────────────────────────────────

  $effect(() => {
    // Access reactive deps to track them
    void filteredPoints;
    void showSigma;
    void sigmaK;
    void viewport;
    void colorBy;
    void cells;
    void hovered;
    if (canvas) scheduleRedraw();
  });

  // Invalidate hover grid when points change
  $effect(() => {
    void filteredPoints;
    hoverGrid = null;
  });

  // ── Drawing ────────────────────────────────────────────────────────────────

  function scheduleRedraw() {
    if (animFrame) cancelAnimationFrame(animFrame);
    animFrame = requestAnimationFrame(redraw);
  }

  function redraw() {
    animFrame = null;
    if (!canvas) return;

    const dpr  = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w    = rect.width;
    const h    = rect.height;
    if (w === 0 || h === 0) return;

    canvas.width  = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = '#1a1b26';
    ctx.fillRect(0, 0, w, h);

    // Integer score grid
    drawGrid(ctx, w, h);

    // Scatter points
    if (filteredPoints.length) {
      drawScatter(ctx, filteredPoints, viewport, colorBy, w, h);
    }

    // σ ellipses overlay
    if (showSigma && cells.length) {
      drawSigmaEllipses(ctx, cells, viewport, sigmaK, w, h);
    }

    // Selection rectangle preview
    if (selRectScreen) {
      const { x0, y0, x1, y1 } = selRectScreen;
      ctx.save();
      ctx.strokeStyle = 'rgba(255,210,50,0.9)';
      ctx.fillStyle   = 'rgba(255,210,50,0.07)';
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.rect(x0, y0, x1 - x0, y1 - y0);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }

    // Highlighted hovered point
    if (hovered) {
      const [sx, sy] = xyToScreen(hovered.bary_p1_b, hovered.bary_p1_a, viewport, w, h);
      ctx.save();
      ctx.beginPath();
      ctx.arc(sx, sy, 5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.fill();
      ctx.restore();
    }
  }

  function drawGrid(ctx, w, h) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth   = 0.5;
    for (let i = 0; i <= 15; i++) {
      const [sx] = xyToScreen(i, 0, viewport, w, h);
      ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke();
      const [, sy] = xyToScreen(0, i, viewport, w, h);
      ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke();
    }
    // Axis labels
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font      = '10px monospace';
    for (let i = 1; i <= 15; i++) {
      const [sx] = xyToScreen(i, 0, viewport, w, h);
      if (sx > 12 && sx < w - 6) ctx.fillText(String(i), sx - 4, h - 5);
      const [, sy] = xyToScreen(0, i, viewport, w, h);
      if (sy > 12 && sy < h - 6) ctx.fillText(String(i), 4, sy + 4);
    }
    ctx.restore();
  }

  // ── Hover grid ─────────────────────────────────────────────────────────────

  function buildHoverGrid() {
    hoverGrid = Array.from({ length: GRID_N * GRID_N }, () => []);
    for (let i = 0; i < filteredPoints.length; i++) {
      const p  = filteredPoints[i];
      const gx = Math.max(0, Math.min(GRID_N - 1, Math.floor((p.bary_p1_b / 16) * GRID_N)));
      const gy = Math.max(0, Math.min(GRID_N - 1, Math.floor((p.bary_p1_a / 16) * GRID_N)));
      hoverGrid[gy * GRID_N + gx].push(i);
    }
  }

  function findNearest(dataX, dataY) {
    if (!hoverGrid) buildHoverGrid();
    const gx = Math.floor((dataX / 16) * GRID_N);
    const gy = Math.floor((dataY / 16) * GRID_N);
    let best = null, bestDist = Infinity;
    const R = 3;
    for (let dy = -R; dy <= R; dy++) {
      for (let dx = -R; dx <= R; dx++) {
        const nx = Math.max(0, Math.min(GRID_N - 1, gx + dx));
        const ny = Math.max(0, Math.min(GRID_N - 1, gy + dy));
        for (const idx of hoverGrid[ny * GRID_N + nx]) {
          const p = filteredPoints[idx];
          const d = (p.bary_p1_b - dataX) ** 2 + (p.bary_p1_a - dataY) ** 2;
          if (d < bestDist) { bestDist = d; best = p; }
        }
      }
    }
    // 0.5² = 0.25 → ~0.5 data units radius for hover snap
    return bestDist < 0.3 ? best : null;
  }

  // ── Pointer event handlers ─────────────────────────────────────────────────

  function canvasRect() { return canvas.getBoundingClientRect(); }

  function onPointerDown(e) {
    canvas.setPointerCapture(e.pointerId);
    const rect = canvasRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    dragState = {
      type: e.shiftKey ? 'select' : 'pan',
      startX: e.clientX,
      startY: e.clientY,
      startVP: { ...viewport },
      startSX: sx,
      startSY: sy,
    };
    if (e.shiftKey) {
      selRectScreen = { x0: sx, y0: sy, x1: sx, y1: sy };
      selecting = true;
    }
  }

  function onPointerMove(e) {
    if (!dragState) {
      // Hover detection
      const rect = canvasRect();
      const sx   = e.clientX - rect.left;
      const sy   = e.clientY - rect.top;
      const [dx, dy] = screenToXy(sx, sy, viewport, rect.width, rect.height);
      const nearest  = findNearest(dx, dy);
      if (nearest !== hovered) hovered = nearest;
      return;
    }

    const rect  = canvasRect();
    const sx    = e.clientX - rect.left;
    const sy    = e.clientY - rect.top;

    if (dragState.type === 'pan') {
      const scaleX = dragState.startVP.w / rect.width;
      const scaleY = dragState.startVP.h / rect.height;
      viewport = {
        ...dragState.startVP,
        x: dragState.startVP.x - (e.clientX - dragState.startX) * scaleX,
        y: dragState.startVP.y - (e.clientY - dragState.startY) * scaleY,
      };
    } else {
      // Rect select: keep top-left / bottom-right ordering
      selRectScreen = {
        x0: Math.min(dragState.startSX, sx),
        y0: Math.min(dragState.startSY, sy),
        x1: Math.max(dragState.startSX, sx),
        y1: Math.max(dragState.startSY, sy),
      };
      scheduleRedraw(); // non-reactive, must trigger manually
    }
  }

  async function onPointerUp(e) {
    if (!dragState) return;
    const { type } = dragState;
    dragState = null;

    if (type === 'select' && selRectScreen) {
      const rect = canvasRect();
      const w = rect.width, h = rect.height;
      const [x0, y0] = screenToXy(selRectScreen.x0, selRectScreen.y0, viewport, w, h);
      const [x1, y1] = screenToXy(selRectScreen.x1, selRectScreen.y1, viewport, w, h);
      selRectScreen = null;
      selecting = false;
      scheduleRedraw();

      // Ignore clicks (degenerate rectangles)
      if (Math.abs(x1 - x0) > 0.05 && Math.abs(y1 - y0) > 0.05) {
        await doSelect({ x0, y0, x1, y1 });
      }
    }
  }

  async function doSelect(dataRect) {
    const body = {
      mode: 'global',
      rect: dataRect,
      filters: {
        crawford_variant: filters.variant !== 'all' ? filters.variant : undefined,
        cube_min: filters.cubeMin,
        cube_max: filters.cubeMax,
        decision_type: filters.decisionTypes?.length ? filters.decisionTypes : undefined,
      },
      sort:   { field: 'move_played_error', order: 'desc' },
      limit:  500,
      offset: 0,
    };
    try {
      const resp = await postSelect(body);
      selection  = { rect: dataRect, total: resp.total, positions: resp.positions };
      onSelectionChange?.(selection);
    } catch (err) {
      console.error('[BaryGlobalScatter] select error:', err);
    }
  }

  function onWheel(e) {
    e.preventDefault();
    const rect   = canvasRect();
    const sx     = e.clientX - rect.left;
    const sy     = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;

    // Zoom centred on cursor position in data space
    const pivotX = viewport.x + (sx / rect.width)  * viewport.w;
    const pivotY = viewport.y + (sy / rect.height) * viewport.h;
    const newW   = viewport.w * factor;
    const newH   = viewport.h * factor;
    viewport = {
      x: pivotX - (sx / rect.width)  * newW,
      y: pivotY - (sy / rect.height) * newH,
      w: newW,
      h: newH,
    };
  }

  function resetView() {
    viewport = { x: -0.5, y: -0.5, w: 16.5, h: 16.5 };
    selection = null;
  }
</script>

<div class="bary-global">
  <!-- Toolbar -->
  <div class="toolbar">
    <label>
      Color
      <select bind:value={colorBy}>
        {#each SUPPORTED_COLOR_FIELDS as f}
          <option value={f}>{f}</option>
        {/each}
      </select>
    </label>

    <label>
      Variant
      <select bind:value={filters.variant}>
        <option value="all">all</option>
        <option value="normal">normal</option>
        <option value="crawford">crawford</option>
        <option value="post_crawford">post-crawford</option>
      </select>
    </label>

    <label>
      Cube min
      <input type="number" min="1" max="64" bind:value={filters.cubeMin} />
    </label>
    <label>
      max
      <input type="number" min="1" max="64" bind:value={filters.cubeMax} />
    </label>

    <label class="sigma-toggle">
      <input type="checkbox" bind:checked={showSigma} />
      σ overlay
    </label>

    {#if showSigma}
      <label>
        k
        <input type="number" min="0.5" max="5" step="0.5" bind:value={sigmaK} />
      </label>
    {/if}

    <button class="reset-btn" onclick={resetView}>Reset view</button>

    {#if selection}
      <button class="clear-btn" onclick={() => { selection = null; onSelectionChange?.(null); }}>
        Clear selection
      </button>
    {/if}
  </div>

  <!-- Canvas -->
  <div class="canvas-wrap">
    {#if loading}
      <div class="overlay-msg">Loading scatter…</div>
    {:else if error}
      <div class="overlay-msg error">Error: {error}</div>
    {/if}

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <canvas
      bind:this={canvas}
      class:selecting
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onwheel={onWheel}
    ></canvas>

    <!-- Axis labels (static, outside canvas) -->
    <div class="axis-label x-label">bary_p1_b (opponent away) →</div>
    <div class="axis-label y-label">↓ bary_p1_a (P1 away)</div>

    <!-- Hover tooltip -->
    {#if tooltip}
      <div class="tooltip">{tooltip}</div>
    {/if}
  </div>

  <!-- Status bar -->
  <div class="status-bar">
    {filteredPoints.length.toLocaleString()} pts
    {#if filters.variant !== 'all'}
      · variant: <strong>{filters.variant}</strong>
    {/if}
    {#if selection}
      · selection: <strong>{selection.total.toLocaleString()}</strong> positions
      · showing {selection.positions.length}
    {/if}
    {#if selecting}
      · shift-drag to select a region
    {/if}
  </div>
</div>

<style>
  .bary-global {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #1a1b26;
    color: #c0caf5;
    font-size: 13px;
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
  }

  .toolbar label {
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }

  .toolbar select,
  .toolbar input[type="number"] {
    background: #1a1b26;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 3px;
    padding: 2px 5px;
    font-size: 12px;
    width: 5em;
  }

  .toolbar input[type="number"] { width: 4em; }

  .sigma-toggle { gap: 5px; }
  .sigma-toggle input { cursor: pointer; }

  .reset-btn, .clear-btn {
    background: #3b4261;
    color: #c0caf5;
    border: 1px solid #565f89;
    border-radius: 3px;
    padding: 3px 10px;
    cursor: pointer;
    font-size: 12px;
  }
  .reset-btn:hover, .clear-btn:hover { background: #414868; }

  .canvas-wrap {
    position: relative;
    flex: 1;
    overflow: hidden;
  }

  canvas {
    width: 100%;
    height: 100%;
    display: block;
    cursor: crosshair;
    touch-action: none;
  }
  canvas.selecting { cursor: cell; }

  .overlay-msg {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #9aa5ce;
    font-size: 14px;
    pointer-events: none;
  }
  .overlay-msg.error { color: #f7768e; }

  .axis-label {
    position: absolute;
    color: rgba(160,170,200,0.5);
    font-size: 11px;
    pointer-events: none;
  }
  .x-label { bottom: 6px; left: 50%; transform: translateX(-50%); }
  .y-label {
    top: 50%;
    left: 4px;
    transform: translateY(-50%) rotate(-90deg);
    transform-origin: center center;
  }

  .tooltip {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(36,40,59,0.92);
    border: 1px solid #565f89;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    color: #c0caf5;
    pointer-events: none;
    white-space: nowrap;
  }

  .status-bar {
    padding: 5px 12px;
    background: #24283b;
    border-top: 1px solid #3b4261;
    font-size: 12px;
    color: #9aa5ce;
    flex-shrink: 0;
  }
  .status-bar strong { color: #c0caf5; }
</style>
