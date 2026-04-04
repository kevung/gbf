-- GBF PostgreSQL Schema v1.0
-- Dialect differences from SQLite:
--   BIGSERIAL instead of INTEGER PRIMARY KEY
--   BYTEA instead of BLOB
--   $N placeholders (handled in Go)
--   HASH indexes for exact lookups
--   ON CONFLICT DO NOTHING for upserts

CREATE TABLE IF NOT EXISTS positions (
    id           BIGSERIAL   PRIMARY KEY,
    zobrist_hash BIGINT      NOT NULL,
    board_hash   BIGINT      NOT NULL,
    base_record  BYTEA       NOT NULL,
    pip_x        INTEGER,
    pip_o        INTEGER,
    away_x       INTEGER,
    away_o       INTEGER,
    cube_log2    INTEGER,
    cube_owner   INTEGER,
    bar_x        INTEGER,
    bar_o        INTEGER,
    borne_off_x  INTEGER,
    borne_off_o  INTEGER,
    side_to_move INTEGER,
    pos_class    INTEGER,
    pip_diff     INTEGER,
    prime_len_x  INTEGER,
    prime_len_o  INTEGER
);

CREATE TABLE IF NOT EXISTS analyses (
    id          BIGSERIAL PRIMARY KEY,
    position_id BIGINT    NOT NULL REFERENCES positions(id),
    block_type  INTEGER   NOT NULL,
    engine_name TEXT,
    payload     BYTEA     NOT NULL,
    UNIQUE(position_id, block_type)
);

CREATE TABLE IF NOT EXISTS matches (
    id               BIGSERIAL PRIMARY KEY,
    match_hash       TEXT    NOT NULL,
    canonical_hash   TEXT    NOT NULL,
    source_file      TEXT,
    source_format    TEXT,
    player1          TEXT,
    player2          TEXT,
    match_length     INTEGER,
    event            TEXT,
    date             TEXT,
    import_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id          BIGSERIAL PRIMARY KEY,
    match_id    BIGINT  NOT NULL REFERENCES matches(id),
    game_number INTEGER,
    score_x     INTEGER,
    score_o     INTEGER,
    winner      INTEGER,
    points_won  INTEGER,
    crawford    INTEGER
);

CREATE TABLE IF NOT EXISTS moves (
    id             BIGSERIAL PRIMARY KEY,
    game_id        BIGINT  NOT NULL REFERENCES games(id),
    move_number    INTEGER,
    position_id    BIGINT  REFERENCES positions(id),
    player         INTEGER,
    move_type      TEXT,
    dice_1         INTEGER,
    dice_2         INTEGER,
    move_string    TEXT,
    equity_diff    INTEGER,
    best_equity    INTEGER,
    played_equity  INTEGER
);

-- Unique constraints (B-tree required for ON CONFLICT target)
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_zobrist  ON positions(zobrist_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_canonical  ON matches(canonical_hash);

-- HASH indexes for fast equality lookups (M7.3)
CREATE INDEX IF NOT EXISTS idx_positions_board    ON positions USING HASH (board_hash);

-- B-tree indexes for range / composite queries
CREATE INDEX IF NOT EXISTS idx_positions_away     ON positions(away_x, away_o);
CREATE INDEX IF NOT EXISTS idx_positions_class    ON positions(pos_class);
CREATE INDEX IF NOT EXISTS idx_positions_pip_diff ON positions(pip_diff);
CREATE INDEX IF NOT EXISTS idx_positions_class_away ON positions(pos_class, away_x, away_o);
CREATE INDEX IF NOT EXISTS idx_matches_player1    ON matches(player1);
CREATE INDEX IF NOT EXISTS idx_matches_player2    ON matches(player2);
CREATE INDEX IF NOT EXISTS idx_moves_game         ON moves(game_id, move_number);
CREATE INDEX IF NOT EXISTS idx_moves_equity_diff  ON moves(equity_diff);
CREATE INDEX IF NOT EXISTS idx_moves_error        ON moves(equity_diff) WHERE equity_diff > 500;

-- M8: projection tables (decoupled from feature format via versioned runs)
CREATE TABLE IF NOT EXISTS projection_runs (
    id              BIGSERIAL PRIMARY KEY,
    method          TEXT    NOT NULL,       -- 'umap_2d', 'pca_2d', 'umap_3d'
    feature_version TEXT    NOT NULL,       -- e.g. 'v1.0', 'v2-no-pip'
    params          JSONB,                  -- {n_neighbors, min_dist, ...}
    n_points        INTEGER,
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT FALSE,  -- one active per (method, lod)
    -- M10.3: LoD level (0=overview ~5-10K, 1=medium ~50-100K, 2=complete)
    lod             INTEGER DEFAULT 0,
    bounds_json     TEXT                    -- {"min_x":…,"max_x":…,"min_y":…,"max_y":…}
);

-- M10.3: migration for existing databases.
ALTER TABLE projection_runs ADD COLUMN IF NOT EXISTS lod INTEGER DEFAULT 0;
ALTER TABLE projection_runs ADD COLUMN IF NOT EXISTS bounds_json TEXT;

CREATE TABLE IF NOT EXISTS projections (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT  NOT NULL REFERENCES projection_runs(id),
    position_id BIGINT  NOT NULL REFERENCES positions(id),
    x           REAL    NOT NULL,
    y           REAL    NOT NULL,
    z           REAL,                       -- NULL for 2D projections
    cluster_id  INTEGER                     -- from HDBSCAN / k-means
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_proj_run_pos  ON projections(run_id, position_id);
CREATE        INDEX IF NOT EXISTS idx_proj_run      ON projections(run_id);
CREATE        INDEX IF NOT EXISTS idx_proj_cluster  ON projections(run_id, cluster_id);

-- M10.4: pre-computed slippy-map tiles (gzipped JSON per zoom/tile cell)
CREATE TABLE IF NOT EXISTS projection_tiles (
    id       BIGSERIAL PRIMARY KEY,
    run_id   BIGINT  NOT NULL REFERENCES projection_runs(id),
    zoom     INTEGER NOT NULL,
    tile_x   INTEGER NOT NULL,
    tile_y   INTEGER NOT NULL,
    n_points INTEGER NOT NULL,
    data     BYTEA   NOT NULL,   -- gzipped JSON [{id,x,y,c,pc}, ...]
    UNIQUE(run_id, zoom, tile_x, tile_y)
);

CREATE INDEX IF NOT EXISTS idx_tiles_run_zoom ON projection_tiles(run_id, zoom);
