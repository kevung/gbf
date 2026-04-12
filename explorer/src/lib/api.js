const BASE = '';

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`);
  return res.json();
}

// ── Config / Setup ───────────────────────────────────────────────────────────

export function fetchConfig() {
  return get('/api/config');
}

export function setDB(path) {
  return post('/api/config/db', { path });
}

export function setBMAB(path) {
  return post('/api/config/bmab', { path });
}

export function browseDir(path = '', mode = '') {
  const params = new URLSearchParams();
  if (path) params.set('path', path);
  if (mode) params.set('mode', mode);
  const qs = params.toString();
  return get(`/api/config/browse${qs ? '?' + qs : ''}`);
}

// ── Stats / Features ─────────────────────────────────────────────────────────

export function fetchStats() {
  return get('/api/stats');
}

export function fetchFeatureNames() {
  return get('/api/features/names');
}

export function fetchFeatureSample(n = 5000) {
  return get(`/api/features/sample?n=${n}`);
}

// ── Projections ──────────────────────────────────────────────────────────────

export function fetchProjection(method = 'umap_2d', opts = {}) {
  const params = new URLSearchParams({ method });
  if (opts.limit) params.set('limit', opts.limit);
  if (opts.offset) params.set('offset', opts.offset);
  if (opts.cluster_id != null) params.set('cluster_id', opts.cluster_id);
  if (opts.pos_class != null) params.set('pos_class', opts.pos_class);
  if (opts.away_x != null) params.set('away_x', opts.away_x);
  if (opts.away_o != null) params.set('away_o', opts.away_o);
  return get(`/api/viz/projection?${params}`);
}

export function fetchClusters(method = 'umap_2d') {
  return get(`/api/viz/clusters?method=${method}`);
}

export function fetchRuns() {
  return get('/api/viz/runs');
}

export function fetchPosition(id) {
  return get(`/api/viz/position/${id}`);
}

// ── Tiles (M10.4/M10.5) ──────────────────────────────────────────────────────

export function fetchTileMeta(method = 'umap_2d', lod = 0) {
  return get(`/api/viz/tilemeta/${method}/${lod}`);
}

/**
 * Fetch a tile and decompress the gzipped JSON payload.
 * Returns an array of {id, x, y, c, pc} objects, or [] for empty tiles.
 */
export async function fetchTile(method, lod, z, x, y) {
  const res = await fetch(`${BASE}/api/viz/tile/${method}/${lod}/${z}/${x}/${y}`);
  if (res.status === 204) return [];
  if (!res.ok) throw new Error(`tile ${z}/${x}/${y}: ${res.status}`);
  // Server sends Content-Encoding: gzip — the browser decompresses it.
  return res.json();
}

// ── Themes ───────────────────────────────────────────────────────────────────

export function setDataDir(path) {
  return post('/api/config/data', { path });
}

export function fetchThemeStats() {
  return get('/api/themes/stats');
}

export function fetchThemePositions(theme, n = 24) {
  return get(`/api/themes/positions?theme=${encodeURIComponent(theme)}&n=${n}`);
}

// ── Import ───────────────────────────────────────────────────────────────────

export function startImport(proportion = 0.01, batchSize = 100) {
  return post('/api/import/start', { proportion, batch_size: batchSize });
}

export function fetchImportStatus() {
  return get('/api/import/status');
}

export function cancelImport() {
  return post('/api/import/cancel', {});
}

export function subscribeImportProgress(onEvent, onDone) {
  const source = new EventSource(BASE + '/api/import/progress');
  source.onmessage = (e) => {
    const data = JSON.parse(e.data);
    onEvent(data);
    if (data.done) {
      source.close();
      if (onDone) onDone(data);
    }
  };
  source.onerror = () => {
    source.close();
    if (onDone) onDone({ done: true, error: 'connection lost' });
  };
  return () => source.close();
}

// ── Projection Compute ──────────────────────────────────────────────────────

export function startProjectionCompute(params = {}) {
  return post('/api/projection/compute', {
    method: params.method || 'pca_2d',
    k: params.k || 8,
    sample_size: params.sampleSize || 0,
    cluster_method: params.clusterMethod || 'kmeans',
    perplexity: params.perplexity || 30,
    tsne_iter: params.tsneIter || 1000,
    hdbscan_min_size: params.hdbscanMinSize || 100,
    hdbscan_min_sample: params.hdbscanMinSample || 50,
    feature_indices: params.featureIndices || null,
    n_neighbors: params.nNeighbors || 15,
    umap_min_dist: params.umapMinDist || 0.1,
  });
}

export function fetchProjectionStatus() {
  return get('/api/projection/status');
}

export function rebuildProjectionTiles() {
  return post('/api/projection/rebuild-tiles', {});
}

export function subscribeProjectionProgress(onEvent, onDone) {
  const source = new EventSource(BASE + '/api/projection/progress');
  source.onmessage = (e) => {
    const data = JSON.parse(e.data);
    onEvent(data);
    if (data.done) {
      source.close();
      if (onDone) onDone(data);
    }
  };
  source.onerror = () => {
    source.close();
    if (onDone) onDone({ done: true, error: 'connection lost' });
  };
  return () => source.close();
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export function formatNumber(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}
