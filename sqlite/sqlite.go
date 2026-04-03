// Package sqlite implements the GBF Store interface using SQLite.
package sqlite

import (
	"context"
	"database/sql"
	_ "embed"
	"fmt"
	"math/bits"

	gbf "github.com/kevung/gbf"
	_ "modernc.org/sqlite"
)

//go:embed schema.sql
var schemaDDL string

// sqlConn is satisfied by both *sql.DB and *sql.Tx.
type sqlConn interface {
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
}

// SQLiteStore implements gbf.Store backed by a SQLite database.
type SQLiteStore struct {
	db *sql.DB
	tx *sql.Tx // non-nil during a batch transaction
}

// conn returns the active transaction if one is open, otherwise the raw DB.
func (s *SQLiteStore) conn() sqlConn {
	if s.tx != nil {
		return s.tx
	}
	return s.db
}

// BeginBatch starts a transaction that groups subsequent Store calls.
// All writes go to the transaction until CommitBatch or RollbackBatch.
func (s *SQLiteStore) BeginBatch(ctx context.Context) error {
	if s.tx != nil {
		return fmt.Errorf("batch already in progress")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin batch: %w", err)
	}
	s.tx = tx
	return nil
}

// CommitBatch commits the current batch transaction.
func (s *SQLiteStore) CommitBatch() error {
	if s.tx == nil {
		return fmt.Errorf("no batch in progress")
	}
	err := s.tx.Commit()
	s.tx = nil
	return err
}

// RollbackBatch rolls back the current batch transaction.
func (s *SQLiteStore) RollbackBatch() {
	if s.tx != nil {
		s.tx.Rollback()
		s.tx = nil
	}
}

// NewSQLiteStore opens (or creates) a SQLite database at path, runs the DDL,
// and enables WAL mode.
func NewSQLiteStore(path string) (*SQLiteStore, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		db.Close()
		return nil, fmt.Errorf("enable WAL: %w", err)
	}

	if _, err := db.Exec("PRAGMA foreign_keys=ON"); err != nil {
		db.Close()
		return nil, fmt.Errorf("enable foreign keys: %w", err)
	}

	if _, err := db.Exec(schemaDDL); err != nil {
		db.Close()
		return nil, fmt.Errorf("create schema: %w", err)
	}

	return &SQLiteStore{db: db}, nil
}

// Close releases the database connection.
func (s *SQLiteStore) Close() error {
	return s.db.Close()
}

// DB returns the underlying *sql.DB for raw queries.
func (s *SQLiteStore) DB() *sql.DB {
	return s.db
}

// UpsertPosition inserts a position or ignores if zobrist_hash already exists.
// Returns the ID of the existing or newly inserted row.
func (s *SQLiteStore) UpsertPosition(ctx context.Context, rec gbf.BaseRecord, boardHash uint64) (int64, error) {
	blob := gbf.MarshalBaseRecord(&rec)

	// Derived columns (M9): computed once at insert time.
	derived := gbf.ExtractDerivedFeatures(rec)
	posClass  := int(derived[9]) // pos_class
	pipDiff   := int(derived[8]) // pip_diff
	primeLenX := int(derived[4]) // prime_len_x
	primeLenO := int(derived[5]) // prime_len_o

	_, err := s.conn().ExecContext(ctx, `
		INSERT OR IGNORE INTO positions
			(zobrist_hash, board_hash, base_record,
			 pip_x, pip_o, away_x, away_o, cube_log2, cube_owner,
			 bar_x, bar_o, borne_off_x, borne_off_o, side_to_move,
			 pos_class, pip_diff, prime_len_x, prime_len_o)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		int64(bits.RotateLeft64(rec.Zobrist, 0)), // uint64 → int64 (bit-identical)
		int64(boardHash),
		blob,
		int(rec.PipX), int(rec.PipO),
		int(rec.AwayX), int(rec.AwayO),
		int(rec.CubeLog2), int(rec.CubeOwner),
		int(rec.BarX), int(rec.BarO),
		int(rec.BorneOffX), int(rec.BorneOffO),
		int(rec.SideToMove),
		posClass, pipDiff, primeLenX, primeLenO,
	)
	if err != nil {
		return 0, fmt.Errorf("upsert position: %w", err)
	}

	var id int64
	err = s.conn().QueryRowContext(ctx,
		`SELECT id FROM positions WHERE zobrist_hash = ?`,
		int64(rec.Zobrist),
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("select position id: %w", err)
	}

	return id, nil
}

// UpsertMatch inserts a match or ignores if canonical_hash already exists.
// Returns the match ID (existing or newly inserted).
func (s *SQLiteStore) UpsertMatch(ctx context.Context, m gbf.Match, matchHash, canonHash string) (int64, error) {
	_, err := s.conn().ExecContext(ctx, `
		INSERT OR IGNORE INTO matches
			(match_hash, canonical_hash, source_format, player1, player2, match_length)
		VALUES (?, ?, 'xg', ?, ?, ?)`,
		matchHash, canonHash,
		m.Metadata.Player1Name, m.Metadata.Player2Name,
		m.Metadata.MatchLength,
	)
	if err != nil {
		return 0, fmt.Errorf("upsert match: %w", err)
	}

	var id int64
	err = s.conn().QueryRowContext(ctx,
		`SELECT id FROM matches WHERE canonical_hash = ?`, canonHash,
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("select match id: %w", err)
	}
	return id, nil
}

// InsertGame inserts a game row for the given match. Returns the game ID.
func (s *SQLiteStore) InsertGame(ctx context.Context, matchID int64, g gbf.Game) (int64, error) {
	crawford := 0
	if g.Crawford {
		crawford = 1
	}
	res, err := s.conn().ExecContext(ctx, `
		INSERT INTO games
			(match_id, game_number, score_x, score_o, winner, points_won, crawford)
		VALUES (?, ?, ?, ?, ?, ?, ?)`,
		matchID, g.GameNumber,
		g.InitialScore[0], g.InitialScore[1],
		g.Winner, g.PointsWon, crawford,
	)
	if err != nil {
		return 0, fmt.Errorf("insert game: %w", err)
	}
	return res.LastInsertId()
}

// InsertMove inserts a move row linking game → position.
func (s *SQLiteStore) InsertMove(ctx context.Context, gameID int64, moveNum int, posID int64, mv gbf.Move) error {
	_, err := s.conn().ExecContext(ctx, `
		INSERT INTO moves
			(game_id, move_number, position_id, player, move_type,
			 dice_1, dice_2, move_string, equity_diff, best_equity, played_equity)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		gameID, moveNum, posID,
		mv.Player, string(mv.MoveType),
		mv.Dice[0], mv.Dice[1],
		mv.MoveString,
		mv.EquityDiff, mv.BestEquity, mv.PlayedEquity,
	)
	if err != nil {
		return fmt.Errorf("insert move: %w", err)
	}
	return nil
}

// AddAnalysis inserts an analysis block for a position.
func (s *SQLiteStore) AddAnalysis(ctx context.Context, posID int64, blockType uint8, engineName string, payload []byte) error {
	_, err := s.conn().ExecContext(ctx, `
		INSERT OR IGNORE INTO analyses (position_id, block_type, engine_name, payload)
		VALUES (?, ?, ?, ?)`,
		posID, blockType, engineName, payload,
	)
	if err != nil {
		return fmt.Errorf("add analysis: %w", err)
	}
	return nil
}

// QueryByZobrist returns all positions matching the given context-aware hash.
func (s *SQLiteStore) QueryByZobrist(ctx context.Context, hash uint64) ([]gbf.Position, error) {
	rows, err := s.conn().QueryContext(ctx,
		`SELECT id, zobrist_hash, board_hash, base_record,
		        pip_x, pip_o, away_x, away_o, cube_log2, cube_owner,
		        bar_x, bar_o, borne_off_x, borne_off_o, side_to_move
		 FROM positions WHERE zobrist_hash = ?`,
		int64(hash),
	)
	if err != nil {
		return nil, fmt.Errorf("query by zobrist: %w", err)
	}
	defer rows.Close()

	return scanPositions(rows)
}

func scanPositions(rows *sql.Rows) ([]gbf.Position, error) {
	var positions []gbf.Position
	for rows.Next() {
		var p gbf.Position
		var zobrist, board int64
		var blob []byte

		err := rows.Scan(
			&p.ID, &zobrist, &board, &blob,
			&p.PipX, &p.PipO, &p.AwayX, &p.AwayO,
			&p.CubeLog2, &p.CubeOwner,
			&p.BarX, &p.BarO, &p.BorneOffX, &p.BorneOffO,
			&p.SideToMove,
		)
		if err != nil {
			return nil, fmt.Errorf("scan position: %w", err)
		}

		p.ZobristHash = uint64(zobrist)
		p.BoardHash = uint64(board)

		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			return nil, fmt.Errorf("unmarshal base record: %w", err)
		}
		p.BaseRecord = *rec

		positions = append(positions, p)
	}
	return positions, rows.Err()
}
