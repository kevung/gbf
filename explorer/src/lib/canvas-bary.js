/**
 * Canvas rendering utilities for barycentric views.
 *
 * Coordinate convention
 * ---------------------
 *  Data space: x = bary_p1_b ∈ [0, 15], y = bary_p1_a ∈ [0, 15].
 *  Canvas:     x increases left→right, y increases top→bottom.
 *  Y is NOT flipped — bary_p1_a = 0 (P1 champion) maps naturally to
 *  screen top, matching the RG static plots.
 *
 * Viewport: { x, y, w, h } — data-space rectangle visible in the canvas.
 */

import { rdbu, normalizeField } from './color-scales.js';

// ── Coordinate transforms ────────────────────────────────────────────────────

/** Data → screen pixels. */
export function xyToScreen(dataX, dataY, viewport, canvasW, canvasH) {
  return [
    (dataX - viewport.x) / viewport.w * canvasW,
    (dataY - viewport.y) / viewport.h * canvasH,
  ];
}

/** Screen pixels → data. */
export function screenToXy(sx, sy, viewport, canvasW, canvasH) {
  return [
    viewport.x + (sx / canvasW) * viewport.w,
    viewport.y + (sy / canvasH) * viewport.h,
  ];
}

// ── Scatter drawing ──────────────────────────────────────────────────────────

const COLOR_BINS = 64;

/**
 * Draw all scatter points onto ctx, grouped by color bin for performance.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array}   points   — from /api/bary/scatter
 * @param {object}  viewport — { x, y, w, h }
 * @param {string}  colorBy  — field name on each point
 * @param {number}  canvasW
 * @param {number}  canvasH
 */
export function drawScatter(ctx, points, viewport, colorBy, canvasW, canvasH) {
  if (!points.length) return;

  // Bin points by normalised color value
  const bins = Array.from({ length: COLOR_BINS }, () => []);
  for (const p of points) {
    const v = p[colorBy] ?? 0.5;
    const bin = Math.min(COLOR_BINS - 1, Math.floor(normalizeField(v, colorBy) * COLOR_BINS));
    bins[bin].push(p);
  }

  ctx.save();
  ctx.globalAlpha = 0.18;
  const r = 2;

  for (let b = 0; b < COLOR_BINS; b++) {
    if (!bins[b].length) continue;
    ctx.fillStyle = rdbu(b / (COLOR_BINS - 1));
    ctx.beginPath();
    for (const p of bins[b]) {
      const [sx, sy] = xyToScreen(p.bary_p1_b, p.bary_p1_a, viewport, canvasW, canvasH);
      ctx.moveTo(sx + r, sy);
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
    }
    ctx.fill();
  }

  ctx.restore();
}

// ── Sigma ellipses ───────────────────────────────────────────────────────────

/**
 * Eigendecomposition of a 2×2 symmetric matrix [[a, b], [b, c]].
 * Returns { l1, l2, v1x, v1y } — l1 ≥ l2, (v1x, v1y) is the unit eigenvector of l1.
 */
function eigen2x2(a, b, c) {
  const mid  = (a + c) / 2;
  const diff = (a - c) / 2;
  const disc = Math.sqrt(diff * diff + b * b);
  const l1   = mid + disc;
  const l2   = mid - disc;

  let v1x, v1y;
  if (Math.abs(b) > 1e-12) {
    v1x = b;
    v1y = l1 - a;
  } else {
    // Diagonal — principal axis is x if a ≥ c, else y
    v1x = a >= c ? 1 : 0;
    v1y = a >= c ? 0 : 1;
  }
  const norm = Math.hypot(v1x, v1y) || 1;
  return { l1: Math.max(0, l1), l2: Math.max(0, l2), v1x: v1x / norm, v1y: v1y / norm };
}

/**
 * Draw σ ellipses for all cells.
 * Axis convention: cell.mean_bary_p1_b = x, cell.mean_bary_p1_a = y.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array}   cells   — from /api/bary/cells
 * @param {object}  viewport
 * @param {number}  k       — σ multiplier (default 2)
 * @param {number}  canvasW
 * @param {number}  canvasH
 */
export function drawSigmaEllipses(ctx, cells, viewport, k = 2, canvasW, canvasH) {
  const SEG = 48; // path segments per ellipse

  ctx.save();
  ctx.lineWidth = 1.2;

  for (const cell of cells) {
    const stdA  = cell.std_bary_p1_a ?? 0;
    const stdB  = cell.std_bary_p1_b ?? 0;
    const cov   = cell.cov_bary_p1_ab_mean ?? 0;
    const cx    = cell.mean_bary_p1_b; // x = bary_p1_b
    const cy    = cell.mean_bary_p1_a; // y = bary_p1_a

    if (cx == null || cy == null) continue;

    const { l1, l2, v1x, v1y } = eigen2x2(stdA * stdA, cov, stdB * stdB);
    // v1 is for the a-axis (row 0), v2 is perpendicular
    const r1 = k * Math.sqrt(l1); // semi-axis along v1
    const r2 = k * Math.sqrt(l2); // semi-axis along v2 = (-v1y, v1x)

    if (r1 < 1e-6 || r2 < 1e-6) continue;

    // Build parametric path in screen space
    ctx.beginPath();
    for (let i = 0; i <= SEG; i++) {
      const t  = (i / SEG) * Math.PI * 2;
      const dx = Math.cos(t) * r1 * v1x - Math.sin(t) * r2 * v1y;
      const dy = Math.cos(t) * r1 * v1y + Math.sin(t) * r2 * v1x;
      const [sx, sy] = xyToScreen(cx + dx, cy + dy, viewport, canvasW, canvasH);
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.closePath();

    if (cell.low_support) {
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(200,200,200,0.35)';
    } else {
      ctx.setLineDash([]);
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    }
    ctx.stroke();

    // "?" glyph for low-support cells
    if (cell.low_support) {
      const [labelX, labelY] = xyToScreen(cx, cy, viewport, canvasW, canvasH);
      ctx.fillStyle = 'rgba(200,200,200,0.5)';
      ctx.font = '10px sans-serif';
      ctx.fillText('?', labelX - 4, labelY + 4);
    }
  }

  ctx.setLineDash([]);
  ctx.restore();
}
