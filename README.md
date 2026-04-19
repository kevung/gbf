# GBF — Gammon Binary Format

A binary record format, Go library, and data system for large-scale
backgammon position storage, querying, and visualization.

## Context

Backgammon analysis software (eXtreme Gammon, GNU Backgammon, BGBlitz)
stores match data in proprietary, incompatible formats. Position analysis
— equities, gammon rates, move evaluations — is trapped in these silos.
No existing tool consolidates and queries this data at scale.

GBF solves this by defining a deterministic binary format for positions
and analysis, importing from all major formats, and storing the results
in an indexed database for fast querying and visualization.

## Objectives

- **Unified import** from all major backgammon software formats
- **Deterministic hashing** for deduplication within and across formats
- **Queryable storage** for 20M+ positions with engine analysis
- **Structural queries** on board features (primes, blots, anchors) via bitboard layers
- **Statistical analysis** of large match corpora
- **Visualization** of multidimensional position data via dimensionality reduction
  (UMAP, PCA) and clustering, for both exploration (Jupyter) and production (SaaS)
- **Multi-language access**: Go library and Python interface

## Constraints

- No floating-point in the binary format — integer-only, deterministic precision
- Multi-backend storage: SQLite (local/exploration) + PostgreSQL (SaaS/production)
- Extensible format via variable-length analysis blocks
- Import performance: 166K files in reasonable time
- Query performance: < 1s on 20M positions for indexed lookups
- Concurrent writes in production (simultaneous multi-user imports)

## Input Formats

| Format    | Extension | Source         | Type   |
|-----------|-----------|----------------|--------|
| XG        | .xg       | eXtreme Gammon | Binary |
| GnuBG SGF | .sgf      | GNU Backgammon | Text   |
| GnuBG MAT | .mat      | GNU Backgammon | Text   |
| BGBlitz   | .bgf      | BGBlitz        | Binary |
| BGBlitz   | .txt      | BGBlitz export | Text   |

## Outputs

- **SQLite database**: single-file, portable, for local use and exploration
- **PostgreSQL database**: for SaaS with concurrent access
- **Parquet export**: columnar format for Python/numpy/pandas/sklearn workflows
- **Go API**: `Store` interface with query methods, backend-agnostic
- **Python access**: direct SQLite/PostgreSQL via standard libraries
- **Visualizations**: 2D/3D scatter plots, cluster maps, difficulty heatmaps

## Target Queries

1. **Position lookup**: find all occurrences of a specific position across the
   dataset, compare analyses from different engines (XG vs GnuBG)
2. **Error analysis**: find all positions where the played move has equity loss
   above a threshold, filtered by match score and position type
3. **Structural patterns**: find positions matching structural criteria (e.g.,
   5-prime with opponent on the bar), grouped by match score

## Dataset: BMAB

The primary dataset is BMAB (Bot Match Analysis Base):

- **166,713 XG match files** (~24 GB raw)
- **~20 million positions** with engine analysis
- **5 geographic regions**, roughly equal distribution:
  Asia, Europe, Middle East/North Africa/Greater Arabia, North America, Oceania
- Stored in `data/bmab-2025-06-23/` (git-ignored)

Import is progressive: one region (~33K files) first, then region by region.

## Project Status

| Component      | Status         |
|----------------|----------------|
| Binary format  | v0.3 in `legacy/`, v1.0-draft in SPEC.md |
| Format parsers | Functional (xgparser, gnubgparser, bgfparser) |
| Database layer | Planned (see ARCHITECTURE.md) |
| Import pipeline| Planned |
| Query API      | Planned |
| Visualization  | Planned |
| PostgreSQL     | Planned |

See ROADMAP.md for the detailed implementation plan.

### Barycentric Explorer

After running the full pipeline, launch the interactive tool:

    ./scripts/run_barycentric_stack.sh

Then open <http://localhost:5173> and navigate to **Barycentric**.
Three views are available:

- **Global scatter** — every position's barycenter in score space;
  draw a rectangle to select positions and inspect them as board cards.
- **Score clouds** — per-cell barycenter scatter, with CRA and PCR
  variants shown separately at 1-away scores.
- **Match trajectory** — click any point to trace the entire match it
  belongs to, with MWC evolution plotted in a companion chart.

## Documentation

- [SPEC.md](SPEC.md) — Binary format specification (v1.0-draft)
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture (5 layers)
- [ROADMAP.md](ROADMAP.md) — Implementation plan (10 milestones)
- [docs/tasks/](docs/tasks/) — Detailed task sheets per milestone
- [legacy/SPEC.md](legacy/SPEC.md) — Historical v0.3 format specification
