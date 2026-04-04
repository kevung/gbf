<script>
</script>

<div class="help-content">
  <h2>GBF Explorer — Documentation</h2>
  <p>
    Standalone data exploration tool for the GBF (Gammon Binary Format) database.
    Explore backgammon position data through interactive visualizations.
    Everything runs from a single executable — no installation required.
  </p>

  <h2>Getting Started</h2>
  <ol>
    <li>Double-click <code>gbf-explorer</code> — the browser opens automatically</li>
    <li>Go to the <strong>Setup</strong> tab to create a database and set the BMAB directory</li>
    <li>Import data from the <strong>Import</strong> tab</li>
    <li>Compute projections from the <strong>Import</strong> tab (PCA + k-means)</li>
    <li>Explore projections and features from the corresponding tabs</li>
  </ol>

  <h2>Command-line Options (optional)</h2>
  <p>All options can also be configured from the Setup tab in the UI.</p>
  <pre><code>gbf-explorer                                # default: auto-open browser
gbf-explorer -db bmab.db                    # open existing database
gbf-explorer -db bmab.db -bmab ./bmab-data  # set BMAB dir
gbf-explorer -addr :8080                    # use specific port
gbf-explorer -no-browser                    # don't auto-open browser</code></pre>

  <h2>Views</h2>

  <h3>⚙️ Setup</h3>
  <p>
    Configure the database path and BMAB data directory.
    Create new databases or open existing ones. Browse the filesystem to find directories.
  </p>

  <h3>📊 Dashboard</h3>
  <p>
    Overview of the database: position, match, game, move, and analysis counts.
    Pie chart of position class distribution (contact/race/bearoff).
    Bar chart of the top 20 match score combinations.
    Lists active projection runs.
  </p>

  <h3>🗺️ Projections</h3>
  <p>
    Interactive 2D scatter plot of projection data (PCA).
  </p>
  <ul>
    <li><strong>Method</strong>: select the projection method (pca_2d)</li>
    <li><strong>Color by</strong>: cluster ID, position class, away scores</li>
    <li><strong>Points</strong>: limit the number of displayed points</li>
    <li><strong>Cluster / Class filter</strong>: restrict to specific subsets</li>
    <li><strong>Click</strong> on a point to see the full position detail</li>
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
    Progressive import of XG files from the BMAB dataset directory +
    projection computation (PCA + k-means).
  </p>
  <ul>
    <li><strong>Import</strong>: select proportion of BMAB files and batch size</li>
    <li><strong>Compute Projections</strong>: run PCA + k-means clustering directly (no Python needed)</li>
    <li>Progress is streamed in real-time</li>
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

  <h2>Building from Source</h2>
  <pre><code># Build for current platform
make build

# Build for all platforms (Linux + Windows)
make all

# The result is a single executable in bin/
ls -la bin/gbf-explorer*</code></pre>
</div>
