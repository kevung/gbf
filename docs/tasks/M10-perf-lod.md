# M10 — Performance, LoD & Tile System

## Objective

Optimize projection algorithms (UMAP, t-SNE, HDBSCAN) for scalability,
introduce a 3-level Level of Detail (LoD) system for progressive
visualization, and implement a tile-based rendering pipeline for the
web explorer. Enable interactive exploration of the full BMAB dataset
(~110M positions) without blocking the user on expensive computations.

## Pre-requisites

M8 (projection storage + viz API), M9 (derived columns + indexes).

## Performance Audit — Current Bottlenecks

Audit performed 2026-04-04 on the pure Go implementations.

### UMAP (`umap.go`, 613 lines)

| Step | Complexity | Issue |
|------|-----------|-------|
| k-NN brute force (L109-174) | O(n²·d) | `math.Sqrt` unnecessary for comparison; `sort.Slice` O(n·log n) instead of heap O(n·log k); alloc per point |
| SGD optimize (L501-601) | O(epochs·edges) | `math.Pow` per edge per epoch (slow); single-threaded |
| umapFindAB (L302-367) | O(1) ~12K evals | Recalculated for same params every time |

### t-SNE (`tsne.go`, 239 lines)

| Issue | Detail |
|-------|--------|
| O(n²) memory | `dist` n×n + `p` n×n + `qNum` n×n |
| `qNum` reallocated each iter | GC pressure from `make([][]float64, n)` × 1000 iters |
| Hard cap 5000 | No Barnes-Hut approximation |

### HDBSCAN (`hdbscan.go`, 355 lines)

| Issue | Detail |
|-------|--------|
| `quickSelect` is full sort | `sort.Float64s` O(n·log n) instead of real quickselect O(n) |
| Core distances O(n²) | Brute force, sequential |
| Distance recalculation | `eucDist` called in both core dist and MST steps |

## Sub-steps

### M10.0 — Benchmark Baseline

Establish reference benchmarks before optimizing.

1. Extend `benchmark_test.go` with projection benchmarks:
   - `BenchmarkUMAPKNN` at n=1K, 5K, 10K, 50K
   - `BenchmarkUMAPFull` at n=1K, 5K, 10K
   - `BenchmarkTSNE` at n=1K, 2K, 5K
   - `BenchmarkHDBSCAN` at n=1K, 5K, 10K, 50K
   - `BenchmarkKMeans` at n=10K, 50K, 100K
2. Profile with `go tool pprof` to validate audit findings
3. Record baseline in this file (Results section below)

Files: `benchmark_test.go`

### M10.1 — Quick Wins (no structural changes)

**M10.1a — Heap k-NN + remove Sqrt** (`umap.go:109-174`)
- Replace `sort.Slice` with max-heap of size k → O(n·log k)
- Compare `distSq` instead of `dist`; apply `math.Sqrt` only to final k
- Pre-allocate heap buffer per goroutine (not per point)

**M10.1b — Fast pow in SGD** (`umap.go:555-583`)
- Replace `math.Pow(distSq, b-1)` with `math.Exp((b-1)*math.Log(distSq))`
- Compute `pow_b = pow_bm1 * distSq` to avoid second Pow call
- Same for negative sampling (L583)

**M10.1c — Cache umapFindAB** (`umap.go:302-367`)
- For spread=1.0, minDist=0.1: return a=1.929, b=0.7915 directly
- Keep grid search as fallback for non-default params

**M10.1d — Real quickselect** (`hdbscan.go:302-310`)
- Implement partition-based quickselect O(n) average
- Introselect variant (median-of-medians fallback) for O(n) worst case

**M10.1e — Pre-allocate qNum in t-SNE** (`tsne.go:100-115`)
- Allocate `qNum` once before the iteration loop
- Zero it each iteration instead of reallocating

**M10.1f — Parallelize HDBSCAN core distances** (`hdbscan.go:41-62`)
- Same pattern as `umapKNN`: chunk points across `runtime.NumCPU()` workers
- Each goroutine computes core distances for its chunk

Files: `umap.go`, `tsne.go`, `hdbscan.go`
Validation: all existing tests pass + benchmarks show improvement

### M10.2 — VP-Tree + Parallel SGD

**M10.2a — VP-tree implementation**
- New file `vptree.go`
- Build: random vantage point → median distance split → recurse
- Query: k-NN with max-heap, branch pruning
- Build O(n·log n), query O(log n) per point
- Used by both UMAP and HDBSCAN

**M10.2b — Integrate VP-tree into UMAP k-NN**
- Replace brute-force in `umapKNN` with VP-tree build + query
- Fallback to brute-force if n < 1000 (overhead not worth it)

**M10.2c — Integrate VP-tree into HDBSCAN**
- Use VP-tree for core distance computation (k-th NN distance)
- Reduces core distance step from O(n²) to O(n·log n)

**M10.2d — Parallelize UMAP SGD**
- Partition edges by head node into chunks
- Each goroutine processes its chunk with per-goroutine RNG
- Slightly racy reads on shared embedding (acceptable, standard practice)

Files: new `vptree.go`, `vptree_test.go`, `umap.go`, `hdbscan.go`

### M10.3 — Level of Detail System

3 fixed LoD levels with stratified sampling:

| LoD | Sample size | Target compute | Use case |
|-----|-------------|----------------|----------|
| 0   | ~5-10K      | < 30s          | Instant overview after import |
| 1   | ~50-100K    | 2-10 min       | Medium exploration |
| 2   | Complete    | Background     | Full dataset analysis |

**M10.3a — Schema migration**
```sql
ALTER TABLE projection_runs ADD COLUMN lod INTEGER DEFAULT 0;
ALTER TABLE projection_runs ADD COLUMN bounds_json TEXT;
```

**M10.3b — Stratified sampling**
- New Store method: `ExportStratifiedFeatures(ctx, sampleSize, seed)`
- Sample proportionally from each `pos_class` to preserve distribution
- Both SQLite and PG implementations

**M10.3c — ProjectionConfig LoD parameter**
- Add `LoD int` to `ProjectionConfig`
- `ComputeProjectionFromStore` uses stratified sampling for LoD 0/1
- Compute bounds (min/max x/y) after projection, store in run

**M10.3d — Activation per (method, lod)**
- `ActivateProjectionRun`: deactivate only same method AND lod
- Multiple active runs per method (one per LoD level)

**M10.3e — API updates**
- `POST /api/projection/compute`: accept `lod` param (default 0)
- `GET /api/viz/projection`: accept `lod` query param
- `GET /api/viz/runs`: return `lod` field per run
- Auto-trigger LoD 0 after import completion (cheap)

Files: `store.go`, `sqlite/schema.sql`, `sqlite/sqlite.go`, `pg/pg.go`,
`projection.go`, `viz/api.go`, `cmd/explorer/main.go`

### M10.4 — Tile System

Pre-computed tiles following slippy map convention.

**Tile grid**: projection space normalized to [0,1]², zoom z → 2^z × 2^z tiles.
Tile (z, tx, ty) covers [tx/2^z, (tx+1)/2^z] × [ty/2^z, (ty+1)/2^z].

**LoD → zoom mapping**:

| LoD | Zoom levels | Max tiles | Points per tile (110M) |
|-----|-------------|-----------|----------------------|
| 0   | 0-2         | 16        | ~625                 |
| 1   | 3-5         | 1024      | ~100                 |
| 2   | 6+          | 4096+     | ~27K                 |

**M10.4a — Schema**
```sql
CREATE TABLE projection_tiles (
    id       INTEGER PRIMARY KEY,
    run_id   INTEGER NOT NULL REFERENCES projection_runs(id),
    zoom     INTEGER NOT NULL,
    tile_x   INTEGER NOT NULL,
    tile_y   INTEGER NOT NULL,
    n_points INTEGER NOT NULL,
    data     BLOB NOT NULL,  -- gzipped JSON [{id,x,y,c,pc}, ...]
    UNIQUE(run_id, zoom, tile_x, tile_y)
);
CREATE INDEX idx_tiles_run_zoom ON projection_tiles(run_id, zoom);
```

**M10.4b — Tile building pipeline** (`tiles.go`)
- Input: completed projection run (points with x, y, cluster_id)
- Normalize coordinates to [0,1]² using `bounds_json`
- For each zoom level: bin points into tiles, serialize as gzipped JSON
- Insert tiles in batch transaction
- ~40 bytes/point in JSON, ~1K points/tile → ~40 KB/tile

**M10.4c — Store methods**
- `InsertTileBatch(ctx, runID, []Tile) error`
- `QueryTile(ctx, runID, zoom, tileX, tileY) ([]byte, error)`
- `QueryTileMeta(ctx, runID) (*TileMeta, error)`

**M10.4d — API endpoints**
- `GET /api/viz/tile/{method}/{lod}/{z}/{x}/{y}` — tile data (cache-friendly)
- `GET /api/viz/tilemeta/{method}/{lod}` — bounds, zoom levels, counts
- 204 No Content for empty tiles

**M10.4e — Post-projection hook**
- After `SaveProjectionResult`, call `BuildTiles(ctx, store, runID)`
- GC old tiles: `DELETE FROM projection_tiles WHERE run_id NOT IN (active)`

Files: new `tiles.go`, `tiles_test.go`, `store.go`, `sqlite/schema.sql`,
`sqlite/sqlite.go`, `pg/pg.go`, `viz/api.go`, `cmd/explorer/main.go`

### M10.5 — Frontend Tile Renderer (deck.gl)

Replace ECharts scatter plot with deck.gl TileLayer.

**M10.5a** — Add deck.gl dependency to explorer Svelte project
**M10.5b** — New `TileMap.svelte` component:
- deck.gl TileLayer with URL template `/api/viz/tile/{method}/{lod}/{z}/{x}/{y}`
- Viewport-based tile loading, caching, LoD transitions
- WebGL scatter rendering (handles millions of points)
**M10.5c** — LoD level selector in Projection view
**M10.5d** — Color-by controls (cluster, pos_class, away scores)
**M10.5e** — Point click → position detail (existing endpoint)

Files: new `explorer/src/components/TileMap.svelte`,
`explorer/src/views/Projection.svelte`, `explorer/package.json`

### M10.6 — Import Parallelization

Pipeline fan-out for parsing:

```
files channel → [N parser goroutines] → parsed channel → [1 DB writer]
```

- N = `runtime.NumCPU()` parser workers
- DB writer uses existing batch transaction pattern
- Journal/error log remain single-writer
- Target: >20K pos/s (vs 11K baseline)

Files: `import_dir.go`

### M10.7 — Integration + Final Documentation

1. E2E test: import 100 files → compute LoD 0 → build tiles → query tile API
2. Update ROADMAP.md with M10 completion
3. Update ARCHITECTURE.md with LoD + tile system
4. Performance comparison table (before/after at various n)

## Dependency Graph

```
M10.0 (benchmarks)
  ├── M10.1 (quick wins) ── M10.2 (VP-tree + parallel SGD)
  ├── M10.3 (LoD) ── M10.4 (tuiles) ── M10.5 (frontend deck.gl)
  ├── M10.6 (import parallèle)
  └── M10.7 (intégration, dépend de tout)
```

M10.1, M10.3, and M10.6 can proceed in parallel after M10.0.

## Acceptance Criteria

- [x] Benchmark baseline recorded (M10.0)
- [x] UMAP k-NN: heap for n > 1000 + VP-tree for low-dim (≤15D); 44D uses heap (M10.1/M10.2)
- [x] HDBSCAN uses real quickselect + parallel core distances + VP-tree for n ≥ 1000 (M10.1/M10.2)
- [x] t-SNE pre-allocates qNum (M10.1)
- [x] Parallel UMAP SGD via edge-chunked goroutines + atomic CAS (M10.2d, race-clean)
- [ ] LoD 0 computes in < 30s on 1.57M position database
- [ ] Tile API serves pre-computed tiles with cache headers
- [ ] deck.gl frontend renders tiles with zoom/pan
- [ ] Import throughput > 20K pos/s
- [x] All tests pass (`go test ./... -short -race`)

## Benchmark Results

Environment: AMD Ryzen 7 PRO 6850U (16 threads), Go 1.25, synthetic 44D data.
Note: t-SNE bug fixed (dist/qNum rows not pre-allocated → panic) as part of M10.0.

### Baseline (before M10.1)

| Algorithm | n=1K | n=5K | n=10K | n=50K | Scaling |
|-----------|------|------|-------|-------|---------|
| UMAP k-NN | 75ms | 823ms | 2.8s | 73.6s | O(n²) |
| HDBSCAN | 56ms | 1.7s | 7.2s | **3m30s** | O(n²) |
| t-SNE (200 iters) | 3.3s | 107s | — (cap) | — (cap) | O(n²) |
| K-Means/2D | <1ms | — | 28ms | 217ms | O(n·k) |
| PCA/44D | <1ms | — | 17ms | — | O(n·d²) |

Key observations:
- HDBSCAN at 50K: 210s → completely blocks interactive use
- UMAP k-NN at 50K: 73.6s → 70% of total UMAP time
- t-SNE hard-capped at 5K (107s at 5K already); not viable for LoD 1+
- PCA and K-Means scale well; no optimization needed

### After M10.1 (quick wins)

| Algorithm | n=1K | n=5K | n=10K | n=50K | Speedup vs baseline |
|-----------|------|------|-------|-------|---------------------|
| UMAP k-NN | 49ms | 391ms | 1.07s | 24.6s | **~3x** |
| HDBSCAN | 8.6ms | 186ms | 776ms | 19.7s | **~10x** |
| t-SNE | — | — | — | — | see below |

t-SNE (pre-alloc qNum only): n=500: 861ms→751ms, n=2K: 14.7s→14.1s (~5%). The
gradient computation O(n²) dominates; pre-allocation has marginal impact. Real
improvement requires Barnes-Hut (M10.2+).

HDBSCAN gains: real quickselect O(n) vs sort O(n·log n) + parallel core distances.
UMAP gains: heap O(n·log k) vs sort O(n·log n) + no Sqrt per pair + fast pow in SGD.

### After M10.2 (VP-tree + parallel SGD)

**UMAP k-NN (44D features)**: VP-tree disabled in high-dimensional space.
The triangle-inequality pruning degrades to near O(n) per query in d=44 (curse
of dimensionality). Threshold set to `dims ≤ 15`; brute-force heap retained for
GBF feature vectors. k-NN times vs M10.1 remain comparable due to -benchtime=1x
variance.

**HDBSCAN (2D embeddings)**: VP-tree IS beneficial (2D → excellent pruning).

| Algorithm | n=1K | n=5K | n=10K | n=50K | Speedup vs M10.1 |
|-----------|------|------|-------|-------|------------------|
| UMAP k-NN (44D) | ~58ms | ~505ms | ~1.3s | ~27.6s | ~same (VP disabled) |
| HDBSCAN (2D) | ~7ms | ~132ms | ~557ms | ~15.7s | **~1.3x** |
| UMAP Full (default epochs) | — | ~2.2s | ~4.8s | — | ↓ parallel SGD |

HDBSCAN gains: VP-tree drops core distance step from O(n²) → O(n·log n) for 2D.
UMAP Full gains: parallel SGD (Hogwild! via atomic CAS) adds goroutine-level
speedup on top of the already-parallel k-NN step. Embeddings updated with
`sync/atomic` CAS loops to remain race-detector clean.

Note on VP-tree applicability: the VP-tree in `vptree.go` is general-purpose
and will be useful for any low-dimensional k-NN query (e.g., future LoD
projection queries on 2D tiles). For GBF's 44D feature vectors, the
parallelised heap remains faster.
