/**
 * BE.4/BE.5 — Shared fetch helpers for the barycentric service (/api/bary/*).
 *
 * The service runs on localhost:8100 and is proxied via Vite's dev server
 * at /api/bary (wired in BE.9). All functions return parsed JSON or throw.
 */

const BASE = '/api/bary';

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`GET ${path}: ${res.status} ${text}`);
  }
  return res.json();
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`POST ${path}: ${res.status} ${text}`);
  }
  return res.json();
}

// ── Cells (bootstrap or raw aggregates) ────────────────────────────────────

/**
 * @param {{ sampling?: 'bootstrap'|'raw', variant?: string }} opts
 */
export function fetchCells(opts = {}) {
  const p = new URLSearchParams();
  if (opts.sampling) p.set('sampling', opts.sampling);
  if (opts.variant) p.set('variant', opts.variant);
  const qs = p.toString();
  return get(`/cells${qs ? '?' + qs : ''}`);
}

// ── Scatter (downsampled global or per-cell) ────────────────────────────────

/**
 * @param {{ mode?: 'global'|'cell', cell_id?: string, per_cell?: number,
 *            limit?: number, seed?: number, variant?: string }} opts
 */
export function fetchScatter(opts = {}) {
  const p = new URLSearchParams();
  if (opts.mode)     p.set('mode', opts.mode);
  if (opts.cell_id)  p.set('cell_id', opts.cell_id);
  if (opts.per_cell != null) p.set('per_cell', opts.per_cell);
  if (opts.limit != null)    p.set('limit', opts.limit);
  if (opts.seed != null)     p.set('seed', opts.seed);
  if (opts.variant)  p.set('variant', opts.variant);
  return get(`/scatter?${p}`);
}

// ── Rectangle select ────────────────────────────────────────────────────────

/**
 * @param {{ mode?: string, cell_id?: string,
 *            rect: { x0, y0, x1, y1 },
 *            filters?: object, sort?: object,
 *            limit?: number, offset?: number }} body
 */
export function postSelect(body) {
  return post('/select', body);
}

// ── Match trajectory ────────────────────────────────────────────────────────

/** Returns full match trajectory for the match containing positionId. */
export function fetchMatch(positionId) {
  return get(`/match/${encodeURIComponent(positionId)}`);
}

// ── Position detail ─────────────────────────────────────────────────────────

/** Returns rich position detail (board, evals, bary context). */
export function fetchPosition(id) {
  return get(`/position/${encodeURIComponent(id)}`);
}
