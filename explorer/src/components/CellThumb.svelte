<script>
  /**
   * BE.6 — CellThumb
   * Mini canvas thumbnail for one score cell.
   * Lazily fetches its scatter sample when it enters the viewport.
   */
  import { onMount }       from 'svelte';
  import { xyToScreen }    from '../lib/canvas-bary.js';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    cell,
    colorBy   = 'mwc_p1',
    showArrow = true,
    getCellPoints,        // async (cellId) => Point[]
    onClick   = null,
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let points  = $state([]);
  let loading = $state(false);
  let loaded  = $state(false);

  let container;
  let canvas = $state();

  // Fixed viewport: ±2.5 data-units around the cell's score values.
  // Axis: x = bary_p1_b (score_away_p2), y = bary_p1_a (score_away_p1).
  const HALF = 2.5;
  let vp = $derived({
    x: (cell.score_away_p2 ?? 7) - HALF,
    y: (cell.score_away_p1 ?? 7) - HALF,
    w: HALF * 2,
    h: HALF * 2,
  });

  let tipText = $derived(
    `${cell.display_label}` +
    `  n=${(cell.n_total ?? 0).toLocaleString()}` +
    `  MWC ${(cell.mean_mwc_p1 ?? 0).toFixed(2)} ± ${(cell.std_mwc_p1 ?? 0).toFixed(3)}`
  );

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(() => {
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !loaded) {
        loaded = true;
        io.disconnect();
        loadData();
      }
    }, { rootMargin: '200px' });
    io.observe(container);
    return () => io.disconnect();
  });

  async function loadData() {
    loading = true;
    try {
      points = await getCellPoints(cell.cell_id);
    } catch (_) {
      // leave points empty; canvas will show only crosshair
    } finally {
      loading = false;
    }
  }

  // ── Reactive redraws ───────────────────────────────────────────────────────

  $effect(() => {
    void points; void colorBy; void showArrow; void vp;
    if (canvas && loaded) redraw();
  });

  // ── Drawing ────────────────────────────────────────────────────────────────

  function redraw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const W   = canvas.clientWidth  || 80;
    const H   = canvas.clientHeight || 80;
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#1a1b26';
    ctx.fillRect(0, 0, W, H);

    if (points.length) drawThumbScatter(ctx, points, vp, colorBy, W, H);
    drawCrosshair(ctx, vp, W, H);
    if (showArrow && cell.mean_bary_p1_b != null) drawArrow(ctx, vp, W, H);
  }

  function drawThumbScatter(ctx, pts, viewport, cb, W, H) {
    const BINS = 32;
    const buckets = Array.from({ length: BINS }, () => []);
    for (const p of pts) {
      const v   = p[cb] ?? 0.5;
      const [lo, hi] = colorRange(cb);
      const t   = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
      const bin = Math.min(BINS - 1, Math.floor(t * BINS));
      buckets[bin].push(p);
    }
    ctx.save();
    ctx.globalAlpha = 0.45;
    const r = 1.5;
    for (let b = 0; b < BINS; b++) {
      if (!buckets[b].length) continue;
      ctx.fillStyle = rdbuCss(b / (BINS - 1));
      ctx.beginPath();
      for (const p of buckets[b]) {
        const [sx, sy] = xyToScreen(p.bary_p1_b, p.bary_p1_a, viewport, W, H);
        ctx.moveTo(sx + r, sy);
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
      }
      ctx.fill();
    }
    ctx.restore();
  }

  function drawCrosshair(ctx, viewport, W, H) {
    const [sx, sy] = xyToScreen(cell.score_away_p2, cell.score_away_p1, viewport, W, H);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.lineWidth   = 0.8;
    ctx.setLineDash([2, 2]);
    ctx.beginPath(); ctx.moveTo(sx, 0);  ctx.lineTo(sx, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, sy);  ctx.lineTo(W, sy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  function drawArrow(ctx, viewport, W, H) {
    const [sx0, sy0] = xyToScreen(cell.score_away_p2,  cell.score_away_p1,  viewport, W, H);
    const [sx1, sy1] = xyToScreen(cell.mean_bary_p1_b, cell.mean_bary_p1_a, viewport, W, H);
    const std = cell.std_mwc_p1 || 0.01;
    const sw  = Math.max(0.5, Math.min(2.5, 0.025 / std));

    ctx.save();
    ctx.strokeStyle = 'rgba(255,220,80,0.85)';
    ctx.fillStyle   = 'rgba(255,220,80,0.85)';
    ctx.lineWidth   = sw;
    ctx.beginPath(); ctx.moveTo(sx0, sy0); ctx.lineTo(sx1, sy1); ctx.stroke();
    const angle = Math.atan2(sy1 - sy0, sx1 - sx0);
    const L = 4;
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

  // ── Inline colour helpers ──────────────────────────────────────────────────

  const RDBU = [
    [103,0,31],[178,24,43],[214,96,77],[244,165,130],[253,219,199],
    [247,247,247],[209,229,240],[146,197,222],[67,147,195],[33,102,172],[5,48,97],
  ];
  function rdbuCss(t) {
    const s  = Math.max(0, Math.min(1, t)) * (RDBU.length - 1);
    const lo = Math.floor(s), hi = Math.min(lo + 1, RDBU.length - 1);
    const f  = s - lo;
    const r  = Math.round(RDBU[lo][0] + f * (RDBU[hi][0] - RDBU[lo][0]));
    const g  = Math.round(RDBU[lo][1] + f * (RDBU[hi][1] - RDBU[lo][1]));
    const b  = Math.round(RDBU[lo][2] + f * (RDBU[hi][2] - RDBU[lo][2]));
    return `rgb(${r},${g},${b})`;
  }
  const COLOR_RANGES = {
    mwc_p1: [0,1], cubeless_mwc_p1: [0,1],
    cube_gap_p1: [-0.25,0.25], cubeful_equity_p1: [-1,1],
  };
  function colorRange(f) { return COLOR_RANGES[f] ?? [0,1]; }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="cell-thumb"
  bind:this={container}
  title={tipText}
  role="button"
  tabindex="0"
  onclick={onClick ? () => onClick(cell) : null}
  onkeydown={onClick ? e => e.key === 'Enter' && onClick(cell) : null}
>
  {#if loading}
    <div class="skeleton"></div>
  {:else}
    <canvas bind:this={canvas}></canvas>
  {/if}
  <div class="footer">
    <span class="label">{cell.display_label}</span>
    {#if cell.crawford_variant !== 'normal'}
      <span class="badge">{cell.crawford_variant === 'crawford' ? 'CRA' : 'PCR'}</span>
    {/if}
  </div>
</div>

<style>
  .cell-thumb {
    display: flex;
    flex-direction: column;
    background: #1a1b26;
    border: 1px solid #2a2d3e;
    border-radius: 3px;
    overflow: hidden;
    cursor: pointer;
    transition: border-color 0.12s;
    min-width: 0;
  }
  .cell-thumb:hover { border-color: #565f89; }
  .cell-thumb:focus { outline: 2px solid #7aa2f7; outline-offset: -1px; }

  canvas {
    width: 100%;
    aspect-ratio: 1;
    display: block;
  }

  .skeleton {
    width: 100%;
    aspect-ratio: 1;
    background: linear-gradient(90deg, #1e2030 25%, #24283b 50%, #1e2030 75%);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
  }
  @keyframes shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  .footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 3px;
    padding: 1px 3px;
    font-size: 9px;
    color: #9aa5ce;
    white-space: nowrap;
    overflow: hidden;
  }

  .badge {
    background: #3d59a1;
    color: #7aa2f7;
    border-radius: 2px;
    padding: 0 2px;
    font-size: 8px;
  }
</style>
