<script>
</script>

<div class="help-content">
  <h2>GBF Explorer — Documentation</h2>
  <p>
    Minimal data exploration tool for the GBF (Gammon Binary Format) database.
    Explore backgammon position data through interactive visualizations.
  </p>

  <h2>Getting Started</h2>
  <ol>
    <li>Start the server: <code>go run ./cmd/explorer -db bmab.db -bmab data/bmab-2025-06-23</code></li>
    <li>Open <code>http://localhost:8080</code> in your browser</li>
    <li>Import data from the <strong>Import</strong> tab (or use existing database)</li>
    <li>Explore projections and features from the corresponding tabs</li>
  </ol>

  <h2>Views</h2>

  <h3>📊 Dashboard</h3>
  <p>
    Overview of the database: position, match, game, move, and analysis counts.
    Pie chart of position class distribution (contact/race/bearoff).
    Bar chart of the top 20 match score combinations.
    Lists active projection runs.
  </p>

  <h3>🗺️ Projections</h3>
  <p>
    Interactive 2D scatter plot of projection data (UMAP, PCA).
    Computed offline and imported via <code>import-projections</code>.
  </p>
  <ul>
    <li><strong>Method</strong>: select the projection method (umap_2d, pca_2d, …)</li>
    <li><strong>Color by</strong>: cluster ID, position class, away scores</li>
    <li><strong>Points</strong>: limit the number of displayed points</li>
    <li><strong>Cluster / Class filter</strong>: restrict to specific subsets</li>
    <li><strong>Click</strong> on a point to see the full position detail (board, cube, pip counts)</li>
    <li><strong>Scroll</strong> to zoom, drag to pan</li>
  </ul>

  <h3>📈 Explorer</h3>
  <p>
    Feature-level data exploration. Samples random positions from the database
    and extracts all 44 features for visualization.
  </p>
  <ul>
    <li><strong>Scatter</strong>: choose any feature for X, Y, and color axes</li>
    <li><strong>Histogram</strong>: distribution of a single feature</li>
    <li><strong>Box Plot</strong>: quartile summary of derived features</li>
    <li><strong>Correlation Matrix</strong>: heatmap of pairwise correlations</li>
  </ul>

  <h3>📥 Import</h3>
  <p>
    Progressive import of XG files from the BMAB dataset directory.
    Requires <code>-bmab</code> flag when starting the server.
  </p>
  <ul>
    <li><strong>Proportion</strong>: percentage of BMAB files to import (e.g. 1% = ~330 files)</li>
    <li><strong>Batch size</strong>: files per transaction (100 is usually optimal)</li>
    <li>Progress is streamed in real-time via Server-Sent Events</li>
    <li>Shows rate (positions/second), elapsed and estimated remaining time</li>
  </ul>

  <h2>Features (44 dimensions)</h2>
  <h3>Raw Features (34)</h3>
  <ul>
    <li><strong>point01–point24</strong>: Signed checker counts (-15 to +15, positive = Player X)</li>
    <li><strong>bar_x, bar_o</strong>: Checkers on the bar</li>
    <li><strong>borne_off_x, borne_off_o</strong>: Checkers borne off</li>
    <li><strong>pip_x, pip_o</strong>: Pip counts</li>
    <li><strong>cube_log2</strong>: log2 of cube value (0=1, 1=2, 2=4, …)</li>
    <li><strong>cube_owner</strong>: 0=center, 1=X, 2=O</li>
    <li><strong>away_x, away_o</strong>: Points needed to win match</li>
  </ul>

  <h3>Derived Features (10)</h3>
  <ul>
    <li><strong>blot_x, blot_o</strong>: Number of single checkers (blots)</li>
    <li><strong>made_x, made_o</strong>: Number of made points (≥2 checkers)</li>
    <li><strong>prime_x, prime_o</strong>: Longest consecutive run of made points</li>
    <li><strong>anchor_x, anchor_o</strong>: Made points in opponent's home board</li>
    <li><strong>pip_diff</strong>: pip_x − pip_o (positive = X leads)</li>
    <li><strong>pos_class</strong>: 0=contact, 1=race, 2=bearoff</li>
  </ul>

  <h2>Projection Pipeline</h2>
  <p>
    Projections are computed offline (Python) and imported into the database.
  </p>
  <pre><code># 1. Export features
go run ./cmd/export-features -db bmab.db -out features.npy -ids ids.npy

# 2. Compute UMAP projections
python python/compute_projections.py \
  --features features.npy --ids ids.npy \
  --method umap_2d --output projections.csv

# 3. Import into database
go run ./cmd/import-projections -db bmab.db -method umap_2d \
  -version v1.0 -params '{{"n_neighbors":15,"min_dist":0.1}}' \
  projections.csv</code></pre>

  <h2>Server Flags</h2>
  <table>
    <thead><tr><th>Flag</th><th>Default</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td><code>-db</code></td><td>bmab.db</td><td>Path to SQLite database</td></tr>
      <tr><td><code>-bmab</code></td><td>(none)</td><td>BMAB dataset directory (enables Import tab)</td></tr>
      <tr><td><code>-addr</code></td><td>:8080</td><td>Listen address</td></tr>
      <tr><td><code>-static</code></td><td>explorer/dist</td><td>Frontend static files directory</td></tr>
    </tbody>
  </table>

  <h2>API Endpoints</h2>
  <table>
    <thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td>GET</td><td><code>/api/stats</code></td><td>Database statistics and distributions</td></tr>
      <tr><td>GET</td><td><code>/api/features/names</code></td><td>List of 44 feature names</td></tr>
      <tr><td>GET</td><td><code>/api/features/sample?n=5000</code></td><td>Random sample with all features</td></tr>
      <tr><td>GET</td><td><code>/api/viz/projection</code></td><td>Projection data points</td></tr>
      <tr><td>GET</td><td><code>/api/viz/clusters</code></td><td>Cluster summaries</td></tr>
      <tr><td>GET</td><td><code>/api/viz/position/&#123;id&#125;</code></td><td>Full position detail</td></tr>
      <tr><td>GET</td><td><code>/api/viz/runs</code></td><td>Active projection runs</td></tr>
      <tr><td>POST</td><td><code>/api/import/start</code></td><td>Start BMAB import</td></tr>
      <tr><td>GET</td><td><code>/api/import/progress</code></td><td>Import progress (SSE stream)</td></tr>
    </tbody>
  </table>

  <h2>Key Findings (from M5)</h2>
  <ul>
    <li><strong>85.9%</strong> of positions are contact, 7.4% race, 6.7% bearoff</li>
    <li>Contact positions are 4× harder than race (mean equity loss)</li>
    <li>UMAP with n_neighbors=15, min_dist=0.1 produces best separation</li>
    <li>HDBSCAN finds 6 natural clusters (3.4% noise)</li>
    <li>PCA PC1 (19%) = pip counts, PC3 (6%) = pip_diff</li>
    <li>8 PCA components capture 50% of variance</li>
  </ul>
</div>
