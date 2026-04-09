# S4.1 — Dashboard View Definitions

Functional specifications for the 7 dashboard views, grounded in
S1–S3 analysis outputs.

## Data Sources Summary

| Parquet / CSV | Produced by | Used in views |
|---|---|---|
| `positions_enriched/*.parquet` | S0.3/S0.4 | 1, 4 |
| `position_clusters.parquet` | S1.3 | 1, 4, 7 |
| `positions_with_hash.parquet` | S0.5 | 7 |
| `trajectory_graph.parquet` | S0.7 | 7 |
| `descriptive_stats.json` | S1.1 | 6 |
| `dice_stats.csv` | S1.2 | 6 |
| `anomaly_report.csv` | S1.4 | 4 |
| `temporal_series.csv` | S1.7 | 6 |
| `graph_topology.csv` | S1.8 | 7 |
| `player_profiles.parquet` | S2.1 | 3, 6 |
| `player_clusters.parquet` | S2.2 | 3 |
| `player_ranking.parquet` | S2.3 | 6 |
| `strengths_weaknesses.csv` | S2.4 | 3 |
| `cube_heatmap_global.csv` | S3.1 | 2 |
| `cube_heatmap_by_length.csv` | S3.1 | 2 |
| `cube_hotspots.csv` | S3.1 | 2 |
| `cube_error_types.csv` | S3.1 | 2 |
| `cube_thresholds.csv` | S3.3 | 5 |
| `cube_thresholds_gammon.csv` | S3.3 | 5 |
| `heuristics.csv` | S3.4 | 4, 5 |
| `gammon_value_by_score.csv` | S3.5 | 5 |
| `cube_model_report.txt` | S3.6 | 5 |

---

## View 1 — Database Explorer

**Purpose**: Browse and filter the 160M-position database by any combination
of criteria; inspect individual positions on a board.

### Filters Panel (left sidebar)

| Filter | Type | Values |
|---|---|---|
| Player name | Text autocomplete | from `matches.parquet` |
| Tournament | Text autocomplete | from `matches.parquet` |
| Match length | Multi-select | 1, 3, 5, 7, 9, 11, 13, 15, 17 |
| Away score (p1, p2) | Dual range slider | 1–17 |
| Game phase | Checkbox | Contact / Race / Bearoff |
| Decision type | Checkbox | Checker / Cube |
| Error magnitude | Range slider | 0.0–2.0 |
| Cluster | Multi-select | loaded from `position_clusters.parquet` |
| Show blunders only | Toggle | error > 0.080 |

### Results Table

Columns: `match_id`, `move_number`, `player`, `away_p1 × away_p2`,
`match_phase` label, `decision_type`, `move_played_error` (color-coded:
green < 0.010, yellow 0.010–0.080, red ≥ 0.080), `eval_equity`.

Pagination: 50 rows per page. Sort by any column.

### Position Detail Panel (right)

Opens on row click:
- Board rendering (S4.3 component): 24 points + bar + cube + away scores
- Move played vs optimal move (if different)
- Position stats from cluster: cluster label, typical error in this cluster
- Link: "view all positions in this cluster"

### API endpoints
```
GET /api/positions?player=&tournament=&away_p1=&away_p2=&phase=
    &error_min=&error_max=&cluster=&decision_type=&limit=50&page=0
GET /api/positions/{position_id}/detail
GET /api/players/autocomplete?q=
GET /api/tournaments/autocomplete?q=
```

---

## View 2 — Cube Error Heatmap

**Purpose**: Visualise cube error rates across all score combinations;
drill down to specific score cells.

### Heatmap Panel

- X-axis: `away_p1` (1–15), Y-axis: `away_p2` (1–15)
- Cell color: avg `move_played_error` (sequential colorscale, white → red)
- Cell size encodes number of decisions (min 20 to render)
- Hot-spot border (orange outline): cells from `cube_hotspots.csv`
- Toggle: raw error | missed_double rate | wrong_take rate | wrong_pass rate
- Match length selector: "All" + per-length tabs (5 / 7 / 9 / 11 / 13)
  (grayed if < 40 decisions for that cell × length)
- Player filter: compare a named player's heatmap against population

### Score Detail Panel (click a cell)

Shows for the selected `(away_p1, away_p2)`:
- Avg error + 95 % CI
- Error-type breakdown: pie chart (missed_double / wrong_take / wrong_pass)
- Top 5 most frequent positions at this score (board thumbnails, S4.3)
- Kazaross take-point reference (from `kazaross_tp*.csv`)
- S3.3 empirical threshold for this cell (from `cube_thresholds.csv`)

### API endpoints
```
GET /api/heatmap/cube-error?match_length=&player=
GET /api/heatmap/cube-error/cell?away_p1=&away_p2=&match_length=
GET /api/cube/thresholds?away_p1=&away_p2=
```

---

## View 3 — Player Profile

**Purpose**: Deep profile of a player — strengths, weaknesses, cluster,
temporal trends, side-by-side comparison.

### Profile Header

Player name, total games, total positions, date range, PR (from
`player_ranking.parquet`), cluster archetype badge.

### Radar Chart

8 axes (from `player_profiles.parquet`):
`avg_error_checker`, `avg_error_cube`, `blunder_rate`,
`missed_double_rate`, `wrong_take_rate`, `contact_error`,
`race_error`, `bearoff_error`.

Population band (mean ± 1σ) shown underneath. Option to overlay a
second player's profile.

### Strengths & Weaknesses Panel

Data from `strengths_weaknesses.csv`:
- 5 score zones (DMP / GS / 4–5away / 6–9away / 10+away):
  each shown as a horizontal bar (z-score), labelled strength / average / weakness
- Phase error profile: ASCII bar chart reproduced in CSS

### Temporal Evolution

Line chart of rolling PR by year (from `temporal_pr.csv`). Shows
improvement / decline trend.

### Comparison Mode

Select a second player: both radar charts overlaid, strengths table
shown side-by-side, Δ column highlighting differences > 0.5 σ.

### API endpoints
```
GET /api/players/{name}/profile
GET /api/players/{name}/strengths
GET /api/players/{name}/temporal
GET /api/players/compare?p1=&p2=
```

---

## View 4 — Position Catalogue

**Purpose**: Browse positions by structural type (cluster), find trap
positions, and read associated practical rules.

### Cluster Browser (left)

List of clusters from `position_clusters.parquet` (K-means / HDBSCAN
labels from S1.3), each with:
- Cluster name / archetype label
- Icon encoding dominant phase (contact / race / bearoff)
- Avg error bar
- Position count

Click a cluster → right panel updates.

### Cluster Detail Panel

- 6 representative board thumbnails (S4.3) — highest-frequency positions
- Error distribution histogram for this cluster
- Associated heuristic rules from `heuristics.csv` (filtered by cluster
  if available, else by match_phase)
- Trap positions from `anomaly_report.csv` in this cluster: boards
  with error magnitude and description

### Filter Bar

- Phase: Contact / Race / Bearoff
- Show only trap positions (toggle)
- Sort: by avg error | by position count | alphabetical

### API endpoints
```
GET /api/clusters
GET /api/clusters/{id}/profile
GET /api/clusters/{id}/positions?limit=20&traps_only=
GET /api/clusters/{id}/heuristics
```

---

## View 5 — Cube Helper

**Purpose**: Practical reference tool for cube decisions at any score.

### Threshold Table

Interactive grid (away_p1 × away_p2, 1–13). Each cell shows:
- Double threshold (equity)
- Pass threshold (equity)
- Color gradient: green (forgiving) → red (narrow window)
- Hover tooltip: Kazaross TP reference, gammon-adjusted threshold
  (from `cube_thresholds_gammon.csv`)

Match length selector (affects Crawford / post-Crawford display).

### Equity Calculator

Input fields:
- `away_p1`, `away_p2` (dropdowns)
- `cube_value` (1 / 2 / 4 / 8)
- `eval_equity` (slider −1.0 → +1.0)
- `gammon_threat` (slider 0 → 1)

Output:
- Recommendation badge: **No Double** / **Double/Take** / **Double/Pass**
- Distance to nearest threshold (e.g., "0.04 above pass threshold")
- Gammon-adjusted recommendation (if gammon_threat > 0.3)
- Top-3 heuristic rules applicable at this score (from `heuristics.csv`)

### Gammon Value Reference

Table: cube 1 / 2 / 4 × score zone (DMP / GS / 4–6away / 7+)
sourced from `gammon_value_by_score.csv` + Kazaross reference column.

### API endpoints
```
GET /api/cube/thresholds?away_p1=&away_p2=&cube_value=
GET /api/cube/recommendation?away_p1=&away_p2=&cube_value=&equity=&gammon_threat=
GET /api/cube/heuristics?away_p1=&away_p2=
GET /api/cube/gammon-values?away_p1=&away_p2=
```

---

## View 6 — Global Statistics

**Purpose**: High-level overview of the dataset and player rankings.

### Overview Cards (top row)

Sourced from `descriptive_stats.json` (S1.1):
- Total positions | Total matches | Date range
- Avg match length | Most common match length
- Checker blunder rate | Cube blunder rate
- Avg PR (population)

### Error Distribution Chart

Histogram of `move_played_error` with log-Y axis. Separate series:
checker / cube decisions. Blunder threshold line at 0.080.

### Player Rankings Table

Data from `player_ranking.parquet` (S2.3):
Columns: rank, name, PR, CI, games, blunder_rate, cluster archetype.
Sortable by any metric. Search by name. Paginated (25 per page).

Dimension ranking tabs: Overall PR | Checker | Cube | Contact | Race
| Bearoff | Gammon handling | Consistency.

### Temporal Trends Panel

Line chart: avg population error by year (from `temporal_series.csv`).
Separate lines for checker / cube. Annotation if sample < 100 matches.

### Over/Under-Performers

Table from `over_under_performers.csv`: players who perform better or
worse than expected for their PR rating. Columns: name, predicted PR,
actual PR, delta, direction badge.

### API endpoints
```
GET /api/stats/overview
GET /api/stats/error-distribution?decision_type=
GET /api/stats/rankings?metric=pr&limit=50&page=0
GET /api/stats/temporal?metric=avg_error
GET /api/stats/over-under-performers?limit=20
```

---

## View 7 — Trajectory Explorer (Position Map)

**Purpose**: Navigate the 2D UMAP projection of position space, trace
game trajectories through crossroad positions.

*Full specification deferred to S4.7 — detailed in task sheet.*

### Summary spec

- UMAP 2D projection: sample 1–5M positions, project rest via
  `umap.transform()`; coordinates stored in `positions_with_hash.parquet`
- Multi-scale rendering (deck.gl WebGL):
  - Zoom 0–3: pre-rendered density tile pyramid (PNG)
  - Zoom 4–7: hexbin aggregation colored by density / avg error / cluster
  - Zoom 8+: individual points, max 5K visible per viewport
- Click a point → fetch trajectories through `position_hash` →
  render as polylines; side panel shows board (S4.3), match count,
  error distribution, continuation branches
- Filters: player, tournament, match result, game phase, error size
- Color modes: cluster | avg error (green → red) | match (unique color)
- Comparison mode: overlay trajectories of two players

### API endpoints
```
GET /api/map/tiles/{z}/{x}/{y}.png
GET /api/map/hexbins?bounds=&resolution=&color_by=
GET /api/map/points?bounds=&limit=5000&filters=
GET /api/trajectories/{hash}?limit=100
GET /api/trajectories/{hash}/detail
GET /api/trajectories/compare?hash=&p1=&p2=
```

---

## Cross-View Interaction Patterns

| From | Action | To |
|---|---|---|
| View 1 row click | "See cluster" | View 4 filtered to cluster |
| View 2 cell click | "Browse positions at this score" | View 1 pre-filtered |
| View 3 player | "Find on map" | View 7 with player filter |
| View 4 position | "See in map" | View 7 centered on point |
| View 5 calculator | "Browse similar positions" | View 1 filtered by equity range + score |
| View 6 player row | "Open profile" | View 3 for that player |
| View 7 point | "Open in explorer" | View 1 for that position_id |

---

## Pre-computed Materialisations Required

To meet < 200 ms query budget on 160M positions:

| Aggregation | Granularity | Refresh |
|---|---|---|
| Cube heatmap cells | (away_p1, away_p2, match_length) | Static |
| Player profiles | per player | Static |
| Cluster summaries | per cluster_id | Static |
| Cube thresholds | (away_p1, away_p2, cube_value) | Static |
| Gammon values by score | (away_p1, away_p2, cube_value) | Static |
| Error distribution | global + per decision_type | Static |
| Rankings | per metric | Static |
| Temporal series | per year | Static |
| UMAP tile pyramid | zoom 0–7 | Static |
| Hexbin grids | zoom 4–7 per color mode | Static |
