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
