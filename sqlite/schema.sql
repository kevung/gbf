-- GBF SQLite Schema v1.0
-- Compatible with PostgreSQL (see ARCHITECTURE.md for dialect differences)

CREATE TABLE IF NOT EXISTS positions (
    id           INTEGER PRIMARY KEY,
    zobrist_hash INTEGER NOT NULL,   -- context-aware uint64 stored as int64
    board_hash   INTEGER NOT NULL,   -- board-only uint64 stored as int64
    base_record  BLOB    NOT NULL,   -- 80 bytes
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
    side_to_move INTEGER
);

CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    block_type  INTEGER NOT NULL,
    engine_name TEXT,
    payload     BLOB    NOT NULL,
    UNIQUE(position_id, block_type)
);

CREATE TABLE IF NOT EXISTS matches (
    id               INTEGER PRIMARY KEY,
    match_hash       TEXT NOT NULL,
    canonical_hash   TEXT NOT NULL,
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
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    game_number INTEGER,
    score_x     INTEGER,
    score_o     INTEGER,
    winner      INTEGER,
    points_won  INTEGER,
    crawford    INTEGER
);

CREATE TABLE IF NOT EXISTS moves (
    id             INTEGER PRIMARY KEY,
    game_id        INTEGER NOT NULL REFERENCES games(id),
    move_number    INTEGER,
    position_id    INTEGER REFERENCES positions(id),
    player         INTEGER,
    move_type      TEXT,
    dice_1         INTEGER,
    dice_2         INTEGER,
    move_string    TEXT,
    equity_diff    INTEGER,   -- x10000, equity loss of played move
    best_equity    INTEGER,   -- x10000, best move equity
    played_equity  INTEGER    -- x10000, played move equity
);

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_zobrist  ON positions(zobrist_hash);
CREATE        INDEX IF NOT EXISTS idx_positions_board    ON positions(board_hash);
CREATE        INDEX IF NOT EXISTS idx_positions_away     ON positions(away_x, away_o);
CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_canonical  ON matches(canonical_hash);
CREATE        INDEX IF NOT EXISTS idx_matches_player1    ON matches(player1);
CREATE        INDEX IF NOT EXISTS idx_matches_player2    ON matches(player2);
CREATE        INDEX IF NOT EXISTS idx_moves_game         ON moves(game_id, move_number);
CREATE        INDEX IF NOT EXISTS idx_moves_equity_diff  ON moves(equity_diff);
