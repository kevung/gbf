# S4 — Interactive Dashboard & Web Application

## Objective

Build a web application that makes the mining study results accessible
through interactive visualizations: position explorer, error heatmaps,
player profiles, position catalogue, cube helper, and a trajectory map.

## Pre-requisites

S1.x, S2.x, S3.x (analysis results inform view design), S0.6/S0.7
(hashing + trajectory graph for S4.7).

## Sub-steps

### S4.1 — User View Definitions

**Objective**: Specify dashboard views and interactions based on S1-S3 results.

**Input**: Results from all previous fiches.
**Output**: Wireframes / functional specifications.
**Dependencies**: S1.x, S2.x, S3.x results.
**Complexity**: Medium.

**View 1 — Database Explorer**:
- Search by player, tournament, away score
- Combinable filters: game phase, error size, decision type
- Position display in visual board format

**View 2 — Error Map**:
- Interactive heatmap away score x away score (S3.1)
- Select a score → detail of typical errors at that score
- Slider to filter by player level or tournament

**View 3 — Player Profile**:
- Radar chart of profile
- Strengths/weaknesses vs population
- Temporal evolution
- Comparison with another player

**View 4 — Position Catalogue**:
- Browse by position cluster (S1.3)
- Most frequent trap positions (S1.4)
- Per cluster: associated practical rules (S3.4)

**View 5 — Cube Helper**:
- Interactive threshold table by score (S3.3)
- Calculator: enter equity + score → cube recommendation

**View 6 — Global Statistics**:
- Summary dashboard (S1.1)
- Player rankings (S2.3)
- Temporal trends

**View 7 — Trajectory Explorer (Position Map)**:
- 2D UMAP projection of position space as interactive map
- Zoom levels: density heatmap (macro) → individual points (max zoom)
- Click a position → display board + all match trajectories through it
- Trajectories as polylines connecting successive positions in 2D space
- Filters: player, tournament, game phase, error size
- Trajectory coloring by match, play quality (error gradient), or result
- Side panel: crossroad detail (match count, mean error, moves played,
  continuation diversity)
- Comparison mode: overlay trajectories of two players through same crossroad

---

### S4.2 — Web Application Architecture

**Objective**: Define tech stack and application architecture.

**Input**: Specifications (S4.1).
**Output**: Architecture document, technology choices.
**Dependencies**: S4.1.
**Complexity**: Medium.

**Suggested stack**:
- **Backend**: Go (consistent with xgparser) or Python (FastAPI)
- **Database**: DuckDB embedded (data rarely changes, no need for Postgres)
  or ClickHouse if queries are too slow
- **Frontend**: React + Recharts/D3 for visualizations, Tailwind CSS
- **Board rendering**: SVG or Canvas for backgammon position display
- **Deployment**: Docker container, simple server (Fly.io, Railway, VPS)
- **Cache**: pre-compute heavy aggregations (heatmaps, player profiles) as
  materialized tables

---

### S4.3 — Board Visualization Component

**Objective**: Reusable backgammon board display component.

**Input**: JSON representation of a position (board + cube + score).
**Output**: React/SVG component displaying the board.
**Dependencies**: None (can be developed in parallel).
**Complexity**: Medium.

**Features**:
- Faithful rendering of 24-point board + bar
- Stacked checkers with counter when > 5
- Cube position and value display
- Away score for each player
- Optional dice display
- Optional move highlight (arrows showing movement)
- Responsive (mobile-adapted)

---

### S4.4 — Data API Endpoints

**Objective**: REST API powering the dashboard.

**Input**: Parquet tables + pre-computed aggregations.
**Output**: REST endpoints.
**Dependencies**: S0.3, S4.2.
**Complexity**: Medium.

**Main endpoints**:
```
GET /api/players?search=...&limit=20
GET /api/players/{name}/profile
GET /api/players/{name}/positions?filters=...
GET /api/players/compare?p1=...&p2=...

GET /api/tournaments?search=...
GET /api/tournaments/{name}/stats

GET /api/heatmap/cube-error?match_length=7
GET /api/heatmap/cube-error?match_length=7&player=...

GET /api/positions?cluster=...&error_min=...&limit=50
GET /api/positions/{id}/detail

GET /api/cube/thresholds?score_away_1=3&score_away_2=5

GET /api/stats/overview
GET /api/stats/rankings?metric=pr&limit=50

GET /api/clusters
GET /api/clusters/{id}/profile
GET /api/clusters/{id}/positions?limit=20

GET /api/map/positions?zoom=...&bounds=...
GET /api/map/density?bounds=...&resolution=...
GET /api/trajectories/{position_hash}
GET /api/trajectories/{position_hash}/detail
GET /api/trajectories/compare?hash=...&player1=...&player2=...
```

---

### S4.5 — Frontend Implementation

**Objective**: Complete user interface development.

**Input**: Specifications (S4.1), API (S4.4), board component (S4.3).
**Output**: Functional web application.
**Dependencies**: S4.1, S4.3, S4.4.
**Complexity**: High.

**Pages**:
- Home with key statistics and navigation
- Explorer with filters and position display
- Interactive heatmap page
- Player profile with comparison
- Position catalogue by cluster
- Cube helper with calculator
- Rankings page
- Position map / trajectory explorer page

---

### S4.6 — Testing & Deployment

**Objective**: Finalize, test, and deploy the application.

**Input**: Complete application.
**Output**: Deployed, accessible application.
**Dependencies**: S4.5.
**Complexity**: Medium.

**Tasks**:
- Performance testing: query response times on 160M positions
- Optimization: indexes, pre-computed aggregations, pagination
- Functional tests of main views
- Dockerization
- Deployment
- Minimal user documentation

---

### S4.7 — Position Map & Trajectory Explorer

**Objective**: Interactive 2D map of positions with trajectory exploration.

**Input**: UMAP projection (S1.3), trajectory graph (S0.7), convergence
index (S0.6).
**Output**: Interactive React component integrated in dashboard.
**Dependencies**: S0.6, S0.7, S1.3, S1.8, S4.3.
**Complexity**: Very High.

**Multi-scale rendering** (required for 160M points):
- Zoom 0-3 (global view): pre-computed tile heatmap (like a geographic map),
  colored by position density. Tiling pyramid pre-rendered as PNG or client
  WebGL rendering.
- Zoom 4-7 (intermediate): hexbin aggregation, each hexagon = N positions.
  Coloring by density, average error, or cluster.
- Zoom 8+ (detail): individual points. Backend query for positions in
  current viewport. Limit to ~5000 simultaneously visible points.
- Technology: deck.gl (WebGL, handles millions of points) or react-map-gl
  with custom layers. Not leaflet/mapbox (designed for geo, not arbitrary
  projections).

**Click → trajectory interaction**:
1. User clicks a point (or hexbin)
2. Frontend retrieves the corresponding `position_hash`
3. API request: `GET /api/trajectories/{position_hash}` → returns N
   trajectories (2D coordinate sequences) through this point
4. Render trajectories as polylines on the map, each line = one game
5. Optional animation: trace trajectories progressively (move by move)
6. On trajectory point hover: display board in side panel (S4.3 component)

**Crossroad detail panel**:
- Board of the clicked position
- Number of matches/games passing through this point
- Distribution of moves played at this position (pie/bar chart)
- Average error at this crossroad
- List of players who traversed this crossroad
- "Continuations": N most frequent branches, with game outcome per branch

**Filters and modes**:
- Filter trajectories by player, tournament, match result
- Color trajectories by: match (unique color per match), play quality
  (green→red gradient), result (won/lost)
- "Comparison" mode: choose 2 players, show only their respective
  trajectories through the same crossroad
- "Error heatmap" mode: color the map by average error per zone instead
  of density

**Required pre-computations (backend/batch)**:
- UMAP projection of all positions (or representative sample + out-of-sample
  projection via `umap.transform()` for the rest)
- Tiling pyramid at different zoom levels
- Spatial index (R-tree or quadtree) for "positions in this rectangle" queries
- Pre-aggregated trajectories per crossroad (top 100-1000 crossroads with
  pre-computed trajectories)

**Anticipated technical challenges**:
- UMAP on 160M points: impossible directly. Options: (a) UMAP on 1-5M
  sample then project the rest via `umap.transform()`, (b) parametric
  UMAP (neural network), (c) PaCMAP as more scalable alternative
- Rendering performance: WebGL mandatory for > 10K points. deck.gl
  ScatterplotLayer + PathLayer are suitable.
- Trajectory data size: a frequent crossroad may have thousands of
  trajectories → paginate, limit, or sample server-side
- Projection coherence: positions close in feature space must be close in
  2D. Visually verify that UMAP projection preserves cluster structure.
