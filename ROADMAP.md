# GBF Roadmap

## Current Status — 2026-04-03

| Milestone | Status | Notes |
|-----------|--------|-------|
| M0 Foundations | ✅ Complete | All sub-steps + 4 validation experiments done |
| M1–M9 | ⬜ Not started | |

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

## M1 — Import XG

**Objective**: Working import pipeline for a single XG file into SQLite.

**Pre-requisites**: M0.

**Sub-steps**:
1. Integrate xgparser into the pipeline
2. Convert XG Match to GBF records (reuse legacy/convert_xg.go)
3. Implement UpsertPosition in SQLiteStore
4. Implement UpsertMatch / Game / Move with extracted analysis columns
5. End-to-end import of a single .xg file
6. Error logging and handling

**Task sheet**: [docs/tasks/M1-import-xg.md](docs/tasks/M1-import-xg.md)

---

## M2 — Import Multi-format

**Objective**: Support GnuBG and BGBlitz formats, with cross-format dedup.

**Pre-requisites**: M1.

**Sub-steps**:
1. Integrate gnubgparser (SGF, MAT)
2. Integrate bgfparser (BGF, TXT)
3. Auto-detect format by file extension
4. Cross-format deduplication via canonical_hash
5. Verify same match imported from XG and SGF produces one match entry

**Task sheet**: [docs/tasks/M2-import-multi.md](docs/tasks/M2-import-multi.md)

---

## M3 — Import BMAB (Progressive)

**Objective**: Import the BMAB dataset region by region with monitoring.

**Pre-requisites**: M2.

**Sub-steps**:
1. Recursive directory traversal of bmab-2025-06-23/
2. Transaction batching (N files per transaction)
3. Progress tracking (files imported / total, positions/second)
4. Error recovery (journal of failed files, skip & continue)
5. Import report (statistics summary)
6. Start with 1 region (~33K files), then add regions progressively

**Task sheet**: [docs/tasks/M3-import-bmab.md](docs/tasks/M3-import-bmab.md)

---

## M4 — Feature Extraction

**Objective**: Extract numeric feature vectors from positions for visualization.

**Pre-requisites**: M3 (at least 1 region imported).

**Sub-steps**:
1. Define raw feature vector (point counts, bar, borne-off, pip, cube, away)
2. Compute derived features (blot count, prime length, anchors, contact/race)
3. Implement `ExtractFeatures(BaseRecord) -> []float64` in Go
4. Feature normalization (scaling for UMAP/PCA)
5. Export features to numpy via Parquet or .npy file

**Task sheet**: [docs/tasks/M4-features.md](docs/tasks/M4-features.md)

---

## M5 — Visualization Exploration (Jupyter)

**Objective**: Explore the dataset visually, identify position families and
discriminant features. Inform Phase 2 decisions.

**Pre-requisites**: M4.

**Sub-steps**:
1. UMAP-2D notebook on sample (~100K positions)
2. PCA notebook — variance explained, component analysis
3. Clustering notebook (HDBSCAN) — identify position families
4. Color projections by features (pip count, away score, contact/race)
5. Difficulty map: color by average equity loss
6. Synthesis report: most discriminant features and recommended query dimensions

**Task sheet**: [docs/tasks/M5-viz-exploration.md](docs/tasks/M5-viz-exploration.md)

---

## M6 — Query API

**Objective**: Complete Go query API and Python helpers for the 3 target queries.

**Pre-requisites**: M1.

**Sub-steps**:
1. QueryByZobrist / QueryByBoardHash
2. QueryByMatchScore (away_x, away_o filtering)
3. QueryByFeatures (composite filters: pip range, cube, bar, equity_diff)
4. Aggregation queries (global stats, distributions)
5. Python helpers (pandas DataFrame wrappers)

**Task sheet**: [docs/tasks/M6-query-api.md](docs/tasks/M6-query-api.md)

---

## M7 — PostgreSQL Backend

**Objective**: Implement PGStore for production SaaS with concurrent writes.

**Pre-requisites**: M6.

**Sub-steps**:
1. Implement `PGStore` (connection pool, schema DDL)
2. Adapt upserts (ON CONFLICT DO NOTHING)
3. HASH indexes on zobrist_hash, board_hash
4. Concurrency tests (parallel imports)
5. Data migration from SQLite to PostgreSQL
6. Optional partitioning by away scores

**Task sheet**: [docs/tasks/M7-postgresql.md](docs/tasks/M7-postgresql.md)

---

## M8 — Visualization SaaS

**Objective**: Production visualization components for the SaaS platform.

**Pre-requisites**: M5 (exploration findings), M7 (PostgreSQL backend).

**Sub-steps**:
1. API endpoint `/api/viz/umap` — pre-computed 2D projections
2. API endpoint `/api/viz/cluster` — cluster membership and centroids
3. Interactive scatter plot component (hover = position detail, click = drill-down)
4. Dynamic filtering (by score, cube, features) with subset re-projection
5. Player comparison (overlay "my games" vs "full dataset")
6. Projection cache (materialized views or dedicated table)

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
