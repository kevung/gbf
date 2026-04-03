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

export function fetchStats() {
  return get('/api/stats');
}

export function fetchFeatureNames() {
  return get('/api/features/names');
}

export function fetchFeatureSample(n = 5000) {
  return get(`/api/features/sample?n=${n}`);
}

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

export function startImport(proportion = 0.01, batchSize = 100) {
  return post('/api/import/start', { proportion, batch_size: batchSize });
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

export function formatNumber(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}
