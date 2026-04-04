# GBF Roadmap

## Current Status — 2026-04-04

| Milestone | Status | Notes |
|-----------|--------|-------|
| M0 Foundations | ✅ Complete | All sub-steps + 4 validation experiments done |
| M1 Import XG   | ✅ Complete | Full pipeline: parse → convert → store |
| M2 Import Multi-format | ✅ Complete | SGF/MAT/TXT + cross-format dedup |
| M3 Import BMAB | ✅ Complete | 5K files validated, 11K pos/s, 14µs lookup |
| M4 Feature Extraction | ✅ Complete | 44-dim vector, .npy + CSV export, normalization |
| M5 Visualization Exploration | ✅ Complete | UMAP/PCA/HDBSCAN on 1.57M pos, 6 clusters, synthesis report |
| M9 Phase 2 Refinement        | ✅ Complete | 4 derived cols, backfill, indexes, query docs, SPEC v1.0 final |
| M6 Query API                 | ✅ Complete | 5 Go query methods, Python helper, migration tool |
| M7 PostgreSQL Backend        | ✅ Complete | PGStore + pgxpool, migration SQLite→PG, concurrency tests (race-clean) |
| M8 Visualization SaaS        | ✅ Complete | Projection runs, viz API (4 endpoints), import-projections CLI |
| M10 Performance + LoD + Tiles | 🔄 In progress | M10.0+M10.1 done; M10.2 done (VP-tree + parallel SGD) |

## Overview

10 milestones from foundations to production-ready system. Each milestone
has a dedicated task sheet in `docs/tasks/` with sub-steps, acceptance
criteria, and test specifications.

## Dependency Graph

```
M0 Foundations + Validation
|
+-- M1 Import XG
|   |
|   +-- M2 Import Multi-format
|   |   |
|   |   +-- M3 Import BMAB (progressive)
|   |       |
|   |       +-- M4 Feature Extraction
|   |           |
|   |           +-- M5 Visualization Exploration (Jupyter)
|   |           |   |
|   |           |   +-- M9 Phase 2 Refinement
|   |           |
|   |           +-- M8 Visualization SaaS (needs M7)
|   |
|   +-- M6 Query API
|       |
|       +-- M7 PostgreSQL Backend
|           |
|           +-- M8 Visualization SaaS
|                   |
|                   +-- M10 Performance + LoD + Tiles (needs M8+M9)
```

## Test Conventions

Tests are described in human language in each task sheet.

- **[U]** Unit test: validates a single function or component in isolation
- **[F]** Functional test: validates an end-to-end flow

Each test has: name, description, inputs, expected output, success criterion.

---

## M0 — Foundations + Validation ✅

**Objective**: Set up the repository structure, core interfaces, and run 4
validation experiments to test fundamental assumptions before investing
in the full implementation.

**Pre-requisites**: None.

**Sub-steps** (all complete):
1. Restructure repository (packages, move legacy code)
2. Define `Store` interface (minimal: Upsert, Query, Close)
3. Implement SQL schema (DDL for 5 tables + indexes)
4. Implement `SQLiteStore` (connect, create tables, close)
5. Implement board-only Zobrist hash
6. Port data structures from legacy
7. Validation experiments — results (2026-04-03):
   - Exp 1: all 3 target queries expressible, return non-empty results ✓
   - Exp 2: 1.1% of board_hash have multiple zobrist_hash → index worth keeping ✓
   - Exp 3: UMAP shows visible pip-diff gradient + contact/race cluster separation ✓
   - Exp 4: ~6 900 pos/sec, 166K extrapolation ~2h27 (< 24h limit) ✓

**Task sheet**: [docs/tasks/M0-foundations.md](docs/tasks/M0-foundations.md)

---

## M1 — Import XG ✅

**Objective**: Working import pipeline for a single XG file into SQLite.

**Pre-requisites**: M0.

**Sub-steps** (all complete):
1. Integrate xgparser v1.3.0 into the pipeline
2. Convert XG Match to GBF records — fixed 1-indexed Checkers bug vs legacy
3. UpsertPosition in SQLiteStore (M0.4)
4. UpsertMatch / InsertGame / InsertMove / AddAnalysis in SQLiteStore
5. `convert.ImportFile` + `gbf.Importer.ImportMatch` — end-to-end pipeline
6. Non-fatal errors logged and skipped; fatal errors returned with context

**Task sheet**: [docs/tasks/M1-import-xg.md](docs/tasks/M1-import-xg.md)

---

## M2 — Import Multi-format ✅

**Objective**: Support GnuBG and BGBlitz formats, with cross-format dedup.

**Pre-requisites**: M1.

**Sub-steps** (all complete):
1. Integrate gnubgparser v1.2.0 (SGF, MAT)
2. Integrate bgfparser v1.2.0 (BGF, TXT)
3. Auto-detect format by file extension (5 extensions)
4. Cross-format deduplication via canonical_hash (INSERT OR IGNORE)
5. Verified: charlot1-charlot2 SGF + MAT → 1 match entry, identical hash

**Task sheet**: [docs/tasks/M2-import-multi.md](docs/tasks/M2-import-multi.md)

---

## M3 — Import BMAB (Progressive) ✅

**Objective**: Import the BMAB dataset region by region with monitoring.

**Pre-requisites**: M2.

**Sub-steps** (all complete):
1. Recursive directory traversal + extension filter + sorted order
2. Transaction batching (SQLiteStore.BeginBatch/CommitBatch via Batcher interface)
3. Progress tracking: pos/s, ETA, per-batch logging
4. Error recovery: journal file for resume, error log for failures
5. Import report: DirectoryReport struct + CLI printReport
6. Validated at 5,000 files (15% of one region) — results in task sheet

**Task sheet**: [docs/tasks/M3-import-bmab.md](docs/tasks/M3-import-bmab.md)

---

## M4 — Feature Extraction ✅

**Objective**: Extract numeric feature vectors from positions for visualization.

**Pre-requisites**: M3 (at least 1 region imported).

**Sub-steps** (all complete):
1. Raw vector (34): signed point counts, bar, borne-off, pip, cube, away
2. Derived (10): blots, made points, prime length, anchors, pip_diff, position class
3. `ExtractAllFeatures(BaseRecord) → []float64` (44 dims), `ClassifyPosition`
4. Normalization: `ComputeNormParams`, `StandardScale`, `MinMaxScale`
5. Export: `ExportFeaturesNpy` (.npy v1.0) + `ExportFeaturesCSV`

**Task sheet**: [docs/tasks/M4-features.md](docs/tasks/M4-features.md)

---

## M9 — Phase 2 Refinement ✅

**Objective**: Finalize the schema, add derived columns, tune indexes,
document queries, and finalize SPEC v1.0.

**Sub-steps** (all complete):
1. Schema: 4 derived columns (pos_class, pip_diff, prime_len_x/o) + 4 indexes
2. UpsertPosition: auto-populates derived columns at insert time
3. BackfillDerivedColumns: cursor-based migration for existing databases
4. Query docs: `docs/queries.md` — 7 query categories, benchmarks included
5. SPEC v1.0 finalized: 80-byte layout confirmed unchanged
6. Benchmarks: Zobrist ~21 µs, class+away ~33 µs, pip_diff range ~35 µs

**Task sheet**: [docs/tasks/M9-refinement.md](docs/tasks/M9-refinement.md)

## M5 — Visualization Exploration (Jupyter) ✅

**Objective**: Explore the dataset visually, identify position families and
discriminant features. Inform Phase 2 decisions.

**Pre-requisites**: M4.

**Sub-steps** (all complete):
1. Export tool (`cmd/export-features`) → 1.57M positions, 527 MB .npy
2. UMAP-2D — 3 hyperparameter configs; n=15/d=0.10 recommended; 66s for 100K
3. PCA — PC1=19% (pip counts), PC3=6% (pip_diff standalone); 8 PCs → 50%
4. Clustering — HDBSCAN: 6 clusters, 3.4% noise; k-means silhouette=0.391
5. Difficulty map — contact 4× harder than race, 10× vs bearoff
6. Synthesis report — 3 M9 schema columns, UMAP hyperparameters, findings

**Task sheet**: [docs/tasks/M5-viz-exploration.md](docs/tasks/M5-viz-exploration.md)

---

## M6 — Query API ✅

**Objective**: Complete Go query API and Python helpers for the 3 target queries.

**Pre-requisites**: M1, M9.

**Sub-steps** (all complete):
1. QueryByZobrist / QueryByBoardHash — returns PositionWithAnalyses
2. QueryByMatchScore — PositionSummary, wildcard support, composite index
3. QueryByFeatures — dynamic SQL builder, EquityDiffMin triggers JOIN
4. Aggregations — QueryScoreDistribution, QueryPositionClassDistribution
5. Python helper — GBFQuery (7 methods, pandas DataFrames)
6. migrate-v1 cmd — ALTER TABLE + backfill for pre-M9 databases

Validated on 1.57M positions: 17,904 DMP positions, correct class distribution.

**Task sheet**: [docs/tasks/M6-query-api.md](docs/tasks/M6-query-api.md)

---

## M7 — PostgreSQL Backend ✅

**Objective**: Implement PGStore for production SaaS with concurrent writes.

**Pre-requisites**: M6.

**Sub-steps**:
1. ✅ Implement `PGStore` (pgxpool, BeginBatch/CommitBatch/RollbackBatch)
2. ✅ Adapt upserts (ON CONFLICT DO NOTHING, $N placeholders via toPgParams)
3. ✅ HASH index on board_hash, B-tree on zobrist_hash (required for ON CONFLICT)
4. ✅ Concurrency test: 10 goroutines, race detector clean
5. ✅ `MigrateStore(ctx, src *sql.DB, dst Store, batchSize)` — SQLite→PG
6. ⬜ Partitioning (skipped — M5 findings don't justify it yet)

**Task sheet**: [docs/tasks/M7-postgresql.md](docs/tasks/M7-postgresql.md)

---

## M8 — Visualization SaaS ✅

**Objective**: Production visualization components for the SaaS platform.

**Pre-requisites**: M5 (exploration findings), M7 (PostgreSQL backend).

**Sub-steps**:
1. ✅ Projection run schema (projection_runs + projections tables, both SQLite and PG)
2. ✅ Store interface: 6 projection methods (Create/Activate/Insert/Active/Query/ClusterSummary)
3. ✅ `viz` package: HTTP API with 4 endpoints (projection, clusters, position detail, runs)
4. ✅ `cmd/import-projections`: CSV → SQLite projection import CLI
5. ✅ `python/compute_projections.py`: features.npy → UMAP/HDBSCAN → CSV pipeline
6. ✅ Decoupled architecture: API serves (x, y, cluster_id) per versioned run, no feature knowledge
7. ⬜ Frontend scatter plot component (deferred to SaaS project)
8. ⬜ Player comparison endpoint (deferred — needs query-by-player in Store)

**Task sheet**: [docs/tasks/M8-viz-saas.md](docs/tasks/M8-viz-saas.md)

---

## M9 — Phase 2 Refinement

**Objective**: Optimize schema, indexes, and format based on Phase 1 findings.

**Pre-requisites**: M5 (exploration findings).

**Sub-steps**:
1. Add derived columns identified in M5 (e.g., contact/race, prime length)
2. Optimize indexes based on observed query patterns
3. Revise BaseRecord if needed (v1.0 finalization)
4. Document standard queries with SQL examples
5. Performance benchmarks (import throughput, query latency)

**Task sheet**: [docs/tasks/M9-refinement.md](docs/tasks/M9-refinement.md)

---

## M10 — Performance + LoD + Tiles �

**Objective**: Optimize projection algorithms for scalability, introduce a
3-level LoD system for progressive visualization, and implement tile-based
rendering in the web explorer. Enable interactive exploration of the full
BMAB dataset (~110M positions).

**Pre-requisites**: M8, M9.

**Context**: Performance audit (2026-04-04) found O(n²) bottlenecks in UMAP
k-NN (brute force), HDBSCAN (fake quickselect, sequential core distances),
and t-SNE (per-iteration allocation). These prevent scaling beyond ~100K
points interactively. Strategy: pure Go optimization (VP-tree, heap k-NN,
parallel SGD) + LoD for progressive computation + pre-computed tiles for
fluid rendering.

**Sub-steps**:
1. ✅ M10.0 — Benchmark baseline (projection algorithms at various n)
2. ✅ M10.1 — Quick wins: heap k-NN, fast pow, cached findAB, real quickselect,
   pre-alloc qNum, parallel HDBSCAN core distances
3. ✅ M10.2 — VP-tree for HDBSCAN core distances + parallel UMAP SGD (atomic
   CAS, race-clean); VP-tree disabled for 44D UMAP k-NN (high-D ineffective)
4. M10.3 — LoD system: 3 levels (5-10K / 50-100K / complete), stratified
   sampling, per-(method, lod) activation, bounds storage
5. M10.4 — Tile system: slippy map convention, pre-computed gzipped JSON
   tiles, LoD→zoom mapping, tile API endpoints
6. M10.5 — Frontend: deck.gl TileLayer replacing ECharts scatter plot
7. M10.6 — Import parallelization: fan-out parsing pipeline (target >20K pos/s)
8. M10.7 — Integration testing + documentation updates

**Dependency graph**:
```
M10.0 → M10.1 → M10.2
M10.0 → M10.3 → M10.4 → M10.5
M10.0 → M10.6
All → M10.7
```

**Task sheet**: [docs/tasks/M10-perf-lod.md](docs/tasks/M10-perf-lod.md)
