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
    side_to_move INTEGER,
    -- M9: derived columns (populated on insert, backfilled by migrate_v1.go)
    pos_class    INTEGER,            -- 0=contact, 1=race, 2=bearoff
    pip_diff     INTEGER,            -- pip_x - pip_o (signed)
    prime_len_x  INTEGER,            -- longest consecutive made-point run (X)
    prime_len_o  INTEGER             -- longest consecutive made-point run (O)
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

-- Core lookup indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_zobrist  ON positions(zobrist_hash);
CREATE        INDEX IF NOT EXISTS idx_positions_board    ON positions(board_hash);
CREATE        INDEX IF NOT EXISTS idx_positions_away     ON positions(away_x, away_o);
CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_canonical  ON matches(canonical_hash);
CREATE        INDEX IF NOT EXISTS idx_matches_player1    ON matches(player1);
CREATE        INDEX IF NOT EXISTS idx_matches_player2    ON matches(player2);
CREATE        INDEX IF NOT EXISTS idx_moves_game         ON moves(game_id, move_number);
CREATE        INDEX IF NOT EXISTS idx_moves_equity_diff  ON moves(equity_diff);

-- M9: derived column indexes
CREATE INDEX IF NOT EXISTS idx_positions_class
    ON positions(pos_class);

CREATE INDEX IF NOT EXISTS idx_positions_pip_diff
    ON positions(pip_diff);

CREATE INDEX IF NOT EXISTS idx_positions_class_away
    ON positions(pos_class, away_x, away_o);

CREATE INDEX IF NOT EXISTS idx_moves_error
    ON moves(equity_diff) WHERE equity_diff > 500;
