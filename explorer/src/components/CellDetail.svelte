<script>
  /**
   * BE.6 — CellDetail
   * Full-size overlay for a single score cell: zoom/pan canvas,
   * Shift-drag rectangle selection, displacement arrow and 2σ ellipse toggles.
   */
  import { onMount, untrack }                    from 'svelte';
  import { postSelect }                          from '../lib/bary-api.js';
  import { drawScatter, drawSigmaEllipses,
           xyToScreen, screenToXy }              from '../lib/canvas-bary.js';
  import { SUPPORTED_COLOR_FIELDS }              from '../lib/color-scales.js';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    cell,
    getCellPoints,
    onClose            = null,
    onSelectionChange  = null,
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let points    = $state([]);
  let loading   = $state(true);
  let colorBy   = $state('mwc_p1');
  let showArrow = $state(true);
  let showEllipse = $state(true);
  let selection = $state(null);
  let selecting = $state(false);

  // Viewport: ±3 around the cell score values (zoom/pan from here).
  // Initial values are extracted before $state so Svelte doesn't warn about
  // capturing a reactive prop reference inside a state initializer.
  const MARGIN = 3;
  // untrack: we intentionally read the initial cell values without reactive tracking
  const _initX = untrack(() => (cell.score_away_p2 ?? 7) - MARGIN);
  const _initY = untrack(() => (cell.score_away_p1 ?? 7) - MARGIN);
  let viewport = $state({ x: _initX, y: _initY, w: MARGIN * 2, h: MARGIN * 2 });

  // ── Non-reactive interaction state ─────────────────────────────────────────

  let canvas;
  let animFrame    = null;
  let dragState    = null;
  let selRectScr   = null;

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(() => {
    (async () => {
      loading = true;
      try {
        points = await getCellPoints(cell.cell_id);
      } finally {
        loading = false;
        scheduleRedraw();
      }
    })();

    // Close on Escape
    function onKey(e) { if (e.key === 'Escape') onClose?.(); }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // ── Reactive redraws ───────────────────────────────────────────────────────

  $effect(() => {
    void points; void colorBy; void showArrow; void showEllipse;
    void viewport; void selection;
    if (canvas) scheduleRedraw();
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
    const W = rect.width, H = rect.height;
    if (!W || !H) return;
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#1a1b26';
    ctx.fillRect(0, 0, W, H);

    drawGrid(ctx, W, H);
    if (points.length) drawScatter(ctx, points, viewport, colorBy, W, H);
    if (showEllipse)   drawSigmaEllipses(ctx, [cell], viewport, 2, W, H);
    if (showArrow)     drawDispArrow(ctx, W, H);
    drawCrosshair(ctx, W, H);

    if (selRectScr) {
      const { x0, y0, x1, y1 } = selRectScr;
      ctx.save();
      ctx.strokeStyle = 'rgba(255,210,50,0.9)';
      ctx.fillStyle   = 'rgba(255,210,50,0.07)';
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.rect(x0, y0, x1 - x0, y1 - y0);
      ctx.fill(); ctx.stroke();
      ctx.restore();
    }
  }

  function drawGrid(ctx, W, H) {
    const xMin = Math.max(0, Math.floor(viewport.x));
    const xMax = Math.min(15, Math.ceil(viewport.x + viewport.w));
    const yMin = Math.max(0, Math.floor(viewport.y));
    const yMax = Math.min(15, Math.ceil(viewport.y + viewport.h));
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth   = 0.5;
    for (let i = xMin; i <= xMax; i++) {
      const [sx] = xyToScreen(i, 0, viewport, W, H);
      ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, H); ctx.stroke();
    }
    for (let i = yMin; i <= yMax; i++) {
      const [, sy] = xyToScreen(0, i, viewport, W, H);
      ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(W, sy); ctx.stroke();
    }
    ctx.restore();
  }

  function drawCrosshair(ctx, W, H) {
    const [sx, sy] = xyToScreen(cell.score_away_p2, cell.score_away_p1, viewport, W, H);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth   = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(sx, 0);  ctx.lineTo(sx, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, sy);  ctx.lineTo(W, sy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  function drawDispArrow(ctx, W, H) {
    if (cell.mean_bary_p1_b == null) return;
    const [sx0, sy0] = xyToScreen(cell.score_away_p2,  cell.score_away_p1,  viewport, W, H);
    const [sx1, sy1] = xyToScreen(cell.mean_bary_p1_b, cell.mean_bary_p1_a, viewport, W, H);

    ctx.save();
    ctx.strokeStyle = 'rgba(255,180,50,0.9)';
    ctx.fillStyle   = 'rgba(255,180,50,0.9)';
    ctx.lineWidth   = 2;
    ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(sx1, sy1); ctx.stroke();
    const angle = Math.atan2(sy1 - sy0, sx1 - sx0);
    const L = 8;
    ctx.beginPath();
    ctx.moveTo(sx1, sy1);
    ctx.lineTo(sx1 - L * Math.cos(angle - Math.PI / 6),
               sy1 - L * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(sx1 - L * Math.cos(angle + Math.PI / 6),
               sy1 - L * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // ── Pointer interactions ───────────────────────────────────────────────────

  function cvRect() { return canvas.getBoundingClientRect(); }

  function onPointerDown(e) {
    canvas.setPointerCapture(e.pointerId);
    const r  = cvRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    dragState = {
      type: e.shiftKey ? 'select' : 'pan',
      startX: e.clientX, startY: e.clientY,
      startSX: sx, startSY: sy,
      startVP: { ...viewport },
    };
    if (e.shiftKey) {
      selRectScr = { x0: sx, y0: sy, x1: sx, y1: sy };
      selecting = true;
    }
  }

  function onPointerMove(e) {
    if (!dragState) return;
    const r  = cvRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    if (dragState.type === 'pan') {
      const scX = dragState.startVP.w / r.width;
      const scY = dragState.startVP.h / r.height;
      viewport = {
        ...dragState.startVP,
        x: dragState.startVP.x - (e.clientX - dragState.startX) * scX,
        y: dragState.startVP.y - (e.clientY - dragState.startY) * scY,
      };
    } else {
      selRectScr = {
        x0: Math.min(dragState.startSX, sx), y0: Math.min(dragState.startSY, sy),
        x1: Math.max(dragState.startSX, sx), y1: Math.max(dragState.startSY, sy),
      };
      scheduleRedraw();
    }
  }

  async function onPointerUp(e) {
    if (!dragState) return;
    const { type } = dragState;
    dragState = null;
    if (type === 'select' && selRectScr) {
      const r = cvRect();
      const [x0, y0] = screenToXy(selRectScr.x0, selRectScr.y0, viewport, r.width, r.height);
      const [x1, y1] = screenToXy(selRectScr.x1, selRectScr.y1, viewport, r.width, r.height);
      selRectScr = null;
      selecting  = false;
      scheduleRedraw();
      if (Math.abs(x1 - x0) > 0.05 && Math.abs(y1 - y0) > 0.05) {
        await doSelect({ x0, y0, x1, y1 });
      }
    }
  }

  async function doSelect(dataRect) {
    const body = {
      mode:    'cell',
      cell_id: cell.cell_id,
      rect:    dataRect,
      sort:    { field: 'move_played_error', order: 'desc' },
      limit:   500,
      offset:  0,
    };
    try {
      const resp = await postSelect(body);
      selection  = { rect: dataRect, total: resp.total, positions: resp.positions };
      onSelectionChange?.(selection);
    } catch (err) {
      console.error('[CellDetail] select error:', err);
    }
  }

  function onWheel(e) {
    e.preventDefault();
    const r      = cvRect();
    const sx     = e.clientX - r.left;
    const sy     = e.clientY - r.top;
    const factor = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    const pivotX = viewport.x + (sx / r.width)  * viewport.w;
    const pivotY = viewport.y + (sy / r.height) * viewport.h;
    const nW = viewport.w * factor, nH = viewport.h * factor;
    viewport = {
      x: pivotX - (sx / r.width)  * nW,
      y: pivotY - (sy / r.height) * nH,
      w: nW, h: nH,
    };
  }

  function resetView() {
    viewport = {
      x: (cell.score_away_p2 ?? 7) - MARGIN,
      y: (cell.score_away_p1 ?? 7) - MARGIN,
      w: MARGIN * 2, h: MARGIN * 2,
    };
  }
</script>

<!-- Backdrop -->
<div
  class="backdrop"
  role="dialog"
  aria-modal="true"
  aria-label={cell.display_label}
  tabindex="-1"
  onclick={e => e.target === e.currentTarget && onClose?.()}
  onkeydown={e => e.key === 'Escape' && onClose?.()}
>
  <div class="detail-panel">

    <!-- Header -->
    <div class="header">
      <span class="title">{cell.display_label}</span>
      {#if cell.crawford_variant !== 'normal'}
        <span class="badge">
          {cell.crawford_variant === 'crawford' ? 'Crawford' : 'Post-Crawford'}
        </span>
      {/if}
      <span class="meta">n = {(cell.n_total ?? 0).toLocaleString()}</span>
      {#if cell.mean_mwc_p1 != null}
        <span class="meta">MWC {cell.mean_mwc_p1.toFixed(3)} ± {(cell.std_mwc_p1 ?? 0).toFixed(3)}</span>
      {/if}
      <div class="spacer"></div>

      <!-- Controls -->
      <label class="ctrl">
        Color
        <select bind:value={colorBy}>
          {#each SUPPORTED_COLOR_FIELDS as f}
            <option value={f}>{f}</option>
          {/each}
        </select>
      </label>
      <label class="ctrl">
        <input type="checkbox" bind:checked={showArrow} /> Arrow
      </label>
      <label class="ctrl">
        <input type="checkbox" bind:checked={showEllipse} /> 2σ
      </label>
      <button class="btn" onclick={resetView}>Reset</button>
      <button class="btn close-btn" onclick={() => onClose?.()}>✕</button>
    </div>

    <!-- Canvas -->
    <div class="canvas-wrap">
      {#if loading}
        <div class="loading-msg">Loading…</div>
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
    </div>

    <!-- Status -->
    <div class="status">
      {points.length.toLocaleString()} pts displayed
      {#if selection}
        · selection: <strong>{selection.total.toLocaleString()}</strong> positions
        · showing {selection.positions.length}
      {/if}
      · Shift-drag to select
    </div>

  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.65);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
  }

  .detail-panel {
    width: 80vw;
    height: 82vh;
    background: #1a1b26;
    border: 1px solid #3b4261;
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: #24283b;
    border-bottom: 1px solid #3b4261;
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .title  { font-size: 15px; font-weight: 600; color: #c0caf5; }
  .badge  { background: #3d59a1; color: #7aa2f7; border-radius: 3px;
            padding: 1px 6px; font-size: 11px; }
  .meta   { font-size: 12px; color: #9aa5ce; }
  .spacer { flex: 1; }

  .ctrl {
    display: flex; align-items: center; gap: 3px;
    font-size: 12px; color: #9aa5ce; white-space: nowrap;
  }
  .ctrl select {
    background: #1a1b26; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 1px 4px; font-size: 11px;
  }
  .ctrl input[type="checkbox"] { cursor: pointer; }

  .btn {
    background: #2a2d3e; color: #c0caf5;
    border: 1px solid #3b4261; border-radius: 3px;
    padding: 2px 8px; cursor: pointer; font-size: 12px;
  }
  .btn:hover  { background: #3b4261; }
  .close-btn  { font-size: 14px; padding: 2px 10px; }

  .canvas-wrap {
    position: relative;
    flex: 1;
    overflow: hidden;
  }

  canvas {
    width: 100%; height: 100%;
    display: block;
    cursor: crosshair;
    touch-action: none;
  }
  canvas.selecting { cursor: cell; }

  .loading-msg {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    color: #9aa5ce; font-size: 14px; pointer-events: none;
  }

  .status {
    padding: 4px 12px;
    background: #24283b;
    border-top: 1px solid #3b4261;
    font-size: 11px; color: #9aa5ce;
    flex-shrink: 0;
  }
  .status strong { color: #c0caf5; }
</style>
