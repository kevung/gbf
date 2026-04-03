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

// SQLiteStore implements gbf.Store backed by a SQLite database.
type SQLiteStore struct {
	db *sql.DB
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

// UpsertPosition inserts a position or ignores if zobrist_hash already exists.
// Returns the ID of the existing or newly inserted row.
func (s *SQLiteStore) UpsertPosition(ctx context.Context, rec gbf.BaseRecord, boardHash uint64) (int64, error) {
	blob := gbf.MarshalBaseRecord(&rec)

	_, err := s.db.ExecContext(ctx, `
		INSERT OR IGNORE INTO positions
			(zobrist_hash, board_hash, base_record,
			 pip_x, pip_o, away_x, away_o, cube_log2, cube_owner,
			 bar_x, bar_o, borne_off_x, borne_off_o, side_to_move)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		int64(bits.RotateLeft64(rec.Zobrist, 0)), // uint64 → int64 (bit-identical)
		int64(boardHash),
		blob,
		int(rec.PipX), int(rec.PipO),
		int(rec.AwayX), int(rec.AwayO),
		int(rec.CubeLog2), int(rec.CubeOwner),
		int(rec.BarX), int(rec.BarO),
		int(rec.BorneOffX), int(rec.BorneOffO),
		int(rec.SideToMove),
	)
	if err != nil {
		return 0, fmt.Errorf("upsert position: %w", err)
	}

	var id int64
	err = s.db.QueryRowContext(ctx,
		`SELECT id FROM positions WHERE zobrist_hash = ?`,
		int64(rec.Zobrist),
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("select position id: %w", err)
	}

	return id, nil
}

// QueryByZobrist returns all positions matching the given context-aware hash.
func (s *SQLiteStore) QueryByZobrist(ctx context.Context, hash uint64) ([]gbf.Position, error) {
	rows, err := s.db.QueryContext(ctx,
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
