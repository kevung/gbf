# GBF — Project Guide

Gammon Binary Format: binary record format + Go library + data system for
large-scale backgammon position storage, querying, and visualization.

## Repository Structure

```
gbf/
  SPEC.md              # Binary format specification (v1.0-draft)
  ARCHITECTURE.md      # System architecture (5 layers)
  ROADMAP.md           # Implementation plan (M0-M9)
  README.md            # Project overview
  legacy/              # v0.3 reference implementation (DO NOT MODIFY)
    gbf.go, record.go, zobrist.go, hash.go, parse.go
    convert_xg.go, convert_gnubg.go, convert_bgf.go
    gbf_test.go, SPEC.md
  data/                # Test files and BMAB dataset (git-ignored for bmab)
  docs/tasks/          # Detailed task sheets (M0-M9)
```

## Conventions

- **Language**: Go (library, import pipeline, API), Python (exploration, viz)
- **Binary format**: Little Endian, integer-only (no float), see SPEC.md
- **Tests**: Go test files, human-readable specs in docs/tasks/
- **Documents**: English, max 500 lines per file

## Key References

- Format spec: SPEC.md (base record layout, analysis blocks, Zobrist)
- Architecture: ARCHITECTURE.md (Store interface, SQL schema, 5 layers)
- Roadmap: ROADMAP.md (milestones M0-M9, dependency graph)
- Legacy code: legacy/ (v0.3, read-only reference for porting)

## Important Rules

- Do not modify files in `legacy/` — it is preserved for reference only
- BaseRecord is 80 bytes — to be re-evaluated after Phase 1 (M5)
- All numeric values in the binary format use integer scaling (x10000)
- Zobrist hashes: context-aware (in record) + board-only (DB column only)
- SQL schema must work on both SQLite and PostgreSQL
