<script>
  /**
   * BE.7 — TrajectoryCanvas
   * Score-space canvas: polyline through a match's barycentric positions,
   * nodes colored by MWC, Crawford segments dashed, cube-action squares.
   */
  import { onMount }           from 'svelte';
  import { xyToScreen, screenToXy } from '../lib/canvas-bary.js';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    match              = null,
    pov                = 'p1',
    hoveredMoveIndex   = null,
    backgroundPoints   = [],
    focusGameNumber    = null,   // null → show all; number → dim other games
    onHover            = null,   // (index | null) => void
    onClickPosition    = null,   // (position_id) => void
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let canvas;
  let animFrame = null;

  // Viewport: start global; auto-fit when match loads
  let viewport = $state({ x: -0.5, y: -0.5, w: 16.5, h: 16.5 });
  let dragState = null;

  // Derived: POV-transformed position array
  let transformed = $derived(
    (match?.positions ?? []).map((p, i) => ({ ...p, _i: i, ...povTransform(p, pov) }))
  );

  // ── POV transform ──────────────────────────────────────────────────────────

  function povTransform(p, pv) {
    if (pv === 'p1') return { x: p.bary_p1_b, y: p.bary_p1_a, mwc: p.mwc_p1 ?? 0.5 };
    return { x: p.bary_p1_a, y: p.bary_p1_b, mwc: 1 - (p.mwc_p1 ?? 0.5) };
  }

  // ── Viewport auto-fit ──────────────────────────────────────────────────────

  function fitViewport(pts) {
    if (!pts.length) return;
    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (const p of pts) {
      if (p.x != null && p.x < xMin) xMin = p.x;
      if (p.x != null && p.x > xMax) xMax = p.x;
      if (p.y != null && p.y < yMin) yMin = p.y;
      if (p.y != null && p.y > yMax) yMax = p.y;
    }
    const px = Math.max(0.5, (xMax - xMin) * 0.15);
    const py = Math.max(0.5, (yMax - yMin) * 0.15);
    viewport = {
      x: xMin - px, y: yMin - py,
      w: xMax - xMin + 2 * px,
      h: yMax - yMin + 2 * py,
    };
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(() => {
    const ro = new ResizeObserver(() => scheduleRedraw());
    ro.observe(canvas);
    return () => {
      ro.disconnect();
      if (animFrame) cancelAnimationFrame(animFrame);
    };
  });

  // Fit viewport when match data arrives
  $effect(() => {
    const pts = transformed;
    if (pts.length) fitViewport(pts);
  });

  // Redraw on any visual dep change
  $effect(() => {
    void transformed; void viewport; void hoveredMoveIndex;
    void backgroundPoints; void focusGameNumber;
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

    drawGridLines(ctx, W, H);

    // Background scatter (context — very faint)
    if (backgroundPoints.length) drawBgScatter(ctx, W, H);

    const pts = transformed;
    if (!pts.length) {
      ctx.fillStyle = '#565f89';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Select a position to trace its match', W / 2, H / 2);
      return;
    }

    drawPolyline(ctx, pts, W, H);
    drawNodes(ctx, pts, W, H);
    if (hoveredMoveIndex != null) drawHovered(ctx, pts, W, H);
  }

  function drawGridLines(ctx, W, H) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 15; i++) {
      const [sx] = xyToScreen(i, 0, viewport, W, H);
      ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, H); ctx.stroke();
      const [, sy] = xyToScreen(0, i, viewport, W, H);
      ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(W, sy); ctx.stroke();
    }
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    for (let i = 1; i <= 15; i++) {
      const [sx] = xyToScreen(i, 0, viewport, W, H);
      if (sx > 10 && sx < W - 5) ctx.fillText(String(i), sx, H - 4);
      const [, sy] = xyToScreen(0, i, viewport, W, H);
      if (sy > 10 && sy < H - 4) { ctx.textAlign = 'left'; ctx.fillText(String(i), 3, sy + 4); ctx.textAlign = 'center'; }
    }
    ctx.restore();
  }

  function drawBgScatter(ctx, W, H) {
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.fillStyle = '#9aa5ce';
    const r = 1;
    ctx.beginPath();
    for (const p of backgroundPoints) {
      const px = pov === 'p1' ? p.bary_p1_b : p.bary_p1_a;
      const py = pov === 'p1' ? p.bary_p1_a : p.bary_p1_b;
      const [sx, sy] = xyToScreen(px, py, viewport, W, H);
      ctx.moveTo(sx + r, sy); ctx.arc(sx, sy, r, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.restore();
  }

  function drawPolyline(ctx, pts, W, H) {
    if (pts.length < 2) return;
    ctx.save();

    // Draw segments; switch style at game boundaries and for crawford
    let prevGameNum = pts[0].game_number;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      const dimmed = focusGameNumber != null && a.game_number !== focusGameNumber;
      const crawford = a.crawford === true;
      const postCraw  = a.is_post_crawford === true;

      ctx.beginPath();
      ctx.globalAlpha = dimmed ? 0.15 : 0.75;
      ctx.strokeStyle = '#7aa2f7';
      ctx.lineWidth   = 1.5;
      if (crawford)  ctx.setLineDash([4, 3]);
      else if (postCraw) ctx.setLineDash([2, 2]);
      else                ctx.setLineDash([]);

      const [ax, ay] = xyToScreen(a.x, a.y, viewport, W, H);
      const [bx, by] = xyToScreen(b.x, b.y, viewport, W, H);
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by);
      ctx.stroke();
      prevGameNum = a.game_number;
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  function drawNodes(ctx, pts, W, H) {
    ctx.save();
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const dimmed = focusGameNumber != null && p.game_number !== focusGameNumber;
      const [sx, sy] = xyToScreen(p.x, p.y, viewport, W, H);
      const r = 3;

      ctx.globalAlpha = dimmed ? 0.1 : 0.85;
      ctx.fillStyle = rdbuCss(Math.max(0, Math.min(1, p.mwc)));
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fill();

      // Cube-action marker: small square overlay
      const isCubeAction = p.decision_type === 'cube' || p.decision_type === 'double';
      if (isCubeAction) {
        ctx.globalAlpha = dimmed ? 0.1 : 0.9;
        ctx.strokeStyle = '#e0af68';
        ctx.lineWidth = 1;
        ctx.strokeRect(sx - 3, sy - 3, 6, 6);
      }
    }
    ctx.restore();
  }

  function drawHovered(ctx, pts, W, H) {
    const p = pts[hoveredMoveIndex];
    if (!p) return;
    const [sx, sy] = xyToScreen(p.x, p.y, viewport, W, H);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, 6, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
  }

  // ── Interaction ────────────────────────────────────────────────────────────

  function cvRect() { return canvas.getBoundingClientRect(); }

  function onPointerDown(e) {
    canvas.setPointerCapture(e.pointerId);
    dragState = {
      startX: e.clientX, startY: e.clientY, startVP: { ...viewport },
      moved: false,
    };
  }

  function onPointerMove(e) {
    const rect = cvRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (dragState) {
      const dx = e.clientX - dragState.startX;
      const dy = e.clientY - dragState.startY;
      if (Math.hypot(dx, dy) > 3) dragState.moved = true;
      if (dragState.moved) {
        viewport = {
          ...dragState.startVP,
          x: dragState.startVP.x - dx * (dragState.startVP.w / rect.width),
          y: dragState.startVP.y - dy * (dragState.startVP.h / rect.height),
        };
      }
    } else {
      // Hover: find nearest trajectory point
      const [dx, dy] = screenToXy(sx, sy, viewport, rect.width, rect.height);
      const pts = transformed;
      let best = null, bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = (pts[i].x - dx) ** 2 + (pts[i].y - dy) ** 2;
        if (d < bestDist) { bestDist = d; best = i; }
      }
      const threshold = (viewport.w / rect.width * 10) ** 2; // ~10px radius
      onHover?.(bestDist < threshold ? best : null);
    }
  }

  function onPointerUp(e) {
    if (!dragState) return;
    const moved = dragState.moved;
    dragState = null;
    if (!moved) {
      // Click → open position
      const rect = cvRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const [dx, dy] = screenToXy(sx, sy, viewport, rect.width, rect.height);
      const pts = transformed;
      let best = null, bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = (pts[i].x - dx) ** 2 + (pts[i].y - dy) ** 2;
        if (d < bestDist) { bestDist = d; best = i; }
      }
      const threshold = (viewport.w / rect.width * 12) ** 2;
      if (best != null && bestDist < threshold) {
        onClickPosition?.(pts[best].position_id);
      }
    }
  }

  function onWheel(e) {
    e.preventDefault();
    const rect = cvRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const f  = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    const px = viewport.x + (sx / rect.width)  * viewport.w;
    const py = viewport.y + (sy / rect.height) * viewport.h;
    const nW = viewport.w * f, nH = viewport.h * f;
    viewport = { x: px - (sx / rect.width) * nW, y: py - (sy / rect.height) * nH, w: nW, h: nH };
  }

  // ── Colour helper ──────────────────────────────────────────────────────────

  const RDBU = [
    [103,0,31],[178,24,43],[214,96,77],[244,165,130],[253,219,199],
    [247,247,247],[209,229,240],[146,197,222],[67,147,195],[33,102,172],[5,48,97],
  ];
  function rdbuCss(t) {
    const s = t * (RDBU.length - 1);
    const lo = Math.floor(s), hi = Math.min(lo + 1, RDBU.length - 1);
    const f = s - lo;
    return `rgb(${Math.round(RDBU[lo][0]+f*(RDBU[hi][0]-RDBU[lo][0]))},${Math.round(RDBU[lo][1]+f*(RDBU[hi][1]-RDBU[lo][1]))},${Math.round(RDBU[lo][2]+f*(RDBU[hi][2]-RDBU[lo][2]))})`;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<canvas
  bind:this={canvas}
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onwheel={onWheel}
  style="width:100%;height:100%;display:block;cursor:crosshair;touch-action:none"
></canvas>
