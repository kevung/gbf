# Barycentric Explorer — Interactive Analysis Tools

Interactive evolution of the RG (Reverse Gammon) static plots into three
inter-linked analysis views driven by a bootstrap-averaged, perspective-
corrected version of the barycentric dataset.

## Objective

Turn the current static barycentric plots (`data/barycentric/plots/*.png`)
into a first-class interactive tool inside the explorer frontend, with
three coordinated views:

1. **Global Scatter** — every position's barycenter plotted in score
   space, with rectangular region selection that opens a list of
   annotated board cards for the selected positions.
2. **Score Clouds** — per score-cell scatter of barycenters (15×15
   grid), with the same region-selection workflow; the 1-away cells
   are split into **Crawford (CRA)** and **Post-Crawford (PCR)**
   variants so the two distinct cube regimes are never conflated.
3. **Match Trajectory** — click a point → load every position of the
   match the point belongs to → draw a polyline through their
   barycenters + a companion chart of MWC vs move index, so the user
   can see the match-equity trajectory. All values are reported in a
   canonical player-1 point of view (P1-POV) so segments where P1 and
   P2 alternate as the player on roll are continuous, not mirrored.

All statistics shown are produced by **bootstrap resampling**: K
sub-samples of the full ~16M-row source are drawn, per-cell aggregates
are computed on each draw, then averaged; the standard deviation
across draws is surfaced as an uncertainty signal on every plotted
statistic.

## Pre-requisites

- RG.1 pipeline outputs (`data/barycentric/barycentric.parquet`,
  `…/barycentric_aggregates.csv`) — reference.
- `data/parquet/positions_enriched/` — source with `player_on_roll`,
  `eval_*`, `score_away_*`, `crawford`, `is_post_crawford`,
  `game_id`, `move_number`, `decision_type`, `board_p1`, `board_p2`,
  `move_played`, `best_move`, `move_played_error`.
- `data/parquet/games.parquet` — provides `match_id` for each
  `game_id`.
- `data/parquet/matches.parquet` — provides player names, match
  length.
- Explorer stack (`explorer/`, Svelte 4 + Vite) and existing
  components: `Board.svelte`, `PositionDetail.svelte`, `TileMap.svelte`,
  `AnalysisTable.svelte`.

## Fiches list

| Fiche | File                                          | Summary                                          |
|-------|-----------------------------------------------|--------------------------------------------------|
| BE.1  | `BE.1-perspective-trajectory.md`              | Rebuild barycentric parquet, correct POV, add match_id/game_id keys |
| BE.2  | `BE.2-bootstrap-cells.md`                     | K-draw bootstrap resampling of cell statistics with σ, p05/p95 |
| BE.3  | `BE.3-crawford-split.md`                      | Split 1-away cells into CRA / PCR / normal variants |
| BE.4  | `BE.4-query-service.md`                       | Python/DuckDB HTTP service for scatter, selection, trajectories |
| BE.5  | `BE.5-global-scatter-view.md`                 | Canvas-based global scatter with rectangle selection + σ overlay |
| BE.6  | `BE.6-score-clouds-view.md`                   | 15×15 per-cell cloud grid with CRA/PCR split and zoom-to-cell |
| BE.7  | `BE.7-trajectory-view.md`                     | Match trajectory polyline + MWC chart, POV toggle |
| BE.8  | `BE.8-selection-panel.md`                     | Shared board-card list + detail drawer for region selections |
| BE.9  | `BE.9-integration.md`                         | Explorer tab, vite proxy, run script, end-to-end verification |

Dependency graph:

```
BE.1 ─┬─> BE.2 ─┐
      ├─> BE.3 ─┤
      └─> BE.4 ─┼─> BE.5 ─┐
                │          ├─> BE.8 ─> BE.9
                ├─> BE.6 ─┤
                └─> BE.7 ─┘
```

## Architecture (5 layers)

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend — explorer/src/views/Barycentric.svelte            │
│   3 sub-views: GlobalScatter, ScoreClouds, MatchTrajectory  │
│   + SelectionPanel (board cards) + BoardCard mini-board     │
│   reuses Board.svelte, PositionDetail.svelte                │
└────────────────────┬────────────────────────────────────────┘
                     │  HTTP JSON  (/api/bary/*)
┌────────────────────▼────────────────────────────────────────┐
│ Backend query service — scripts/barycentric_service.py       │
│   GET  /api/bary/cells    bootstrap aggregates + σ           │
│   GET  /api/bary/scatter  down-sampled global / cell scatter │
│   POST /api/bary/select   rectangle → positions list         │
│   GET  /api/bary/match/{position_id}   full match trajectory │
│   GET  /api/bary/position/{id}         rich detail           │
│   Backed by DuckDB + polars on local parquet.                │
└────────────────────┬────────────────────────────────────────┘
                     │ reads parquet                           │
┌────────────────────▼────────────────────────────────────────┐
│ Derived data — data/barycentric/                            │
│   barycentric_v2.parquet     (BE.1 — perspective-corrected) │
│   cell_keys.parquet          (BE.3 — CRA/PCR/normal)        │
│   bootstrap_cells.parquet    (BE.2 — mean/σ/p05/p95 per cell)│
└────────────────────┬────────────────────────────────────────┘
                     │ produced by                             │
┌────────────────────▼────────────────────────────────────────┐
│ Compute scripts — scripts/                                  │
│   compute_barycentric_v2.py    (BE.1)                       │
│   bootstrap_cells.py           (BE.2 + BE.3)                │
└─────────────────────────────────────────────────────────────┘
```

## Perspective convention

All publicly-facing columns and endpoints are in **P1-POV**: equity,
MWC, barycenter coordinates, and displacement are reported as "from
player 1's point of view". The bug being corrected is that the current
`compute_barycentric.py` assumes the on-roll player's identity matches
`p1` in the score pair, which only holds roughly half the time. After
BE.1, for any position:

- `cubeless_mwc_p1 ∈ [0, 1]` — probability P1 wins the match (cubeless).
- `bary_p1_a` — expected P1 away score after the current game.
- `bary_p1_b` — expected P2 away score after the current game.
- `cubeful_equity_p1 = eval_equity × (+1 if on_roll==1 else −1)`.
- `cube_gap_p1 = cubeful_equity_p1 − (2·cubeless_mwc_p1 − 1)`.

The **on-roll-POV** values (`*_onroll`) are also stored so classical
per-position plots (RG.2 quiver, RG.3 heatmap) remain reproducible.

## Dataset size & sampling budgets

- Source: ~16 M rows across `positions_enriched/part-*.parquet`.
- Default bootstrap: K = 50 draws × 500 000 rows (≈ same size as the
  current single-sample analysis in `analysis.md`).
- Global scatter render: stratified 500 per cell → ~110 k points
  for 225 score cells (or ~130 k with the 30 CRA/PCR cells).
- Cell zoom view: up to 10 000 positions per cell.
- Match trajectory: typically 30–300 positions per match, no sampling.

Memory and runtime targets (dev laptop, 32 GB RAM):
- BE.1 full pass: < 8 min, < 16 GB peak.
- BE.2 K = 50: < 12 min, streams one draw at a time.
- BE.4 service cold start: < 15 s; per-request < 300 ms for selection
  queries up to 10 000 hits.

## Verification (plan-level)

- End-to-end acceptance is defined in BE.9. The short version:
  1. Pipeline runs producing the three derived parquet files.
  2. Service comes up, all endpoints return well-formed JSON.
  3. Explorer tab "Barycentric" renders the three views.
  4. Region selection on the global scatter returns coherent boards.
  5. Match trajectory of a known match reproduces the expected final
     score (from `matches.parquet`) and the MWC curve inverts when
     the P2-POV toggle is used.
- BE.1's sanity report must quantify the perspective correction
  (expected: ~50 % of rows change MWC by a non-trivial amount).
- BE.2's report must list cells with `mwc_p1_std / mwc_p1_mean >
  some threshold` as "low-support" — these are surfaced in the UI
  with de-saturated color + σ ellipse.
