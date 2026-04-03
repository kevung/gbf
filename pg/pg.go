// Package pg implements the GBF Store interface using PostgreSQL via pgx/v5.
package pg

import (
	"context"
	_ "embed"
	"fmt"
	"math/bits"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	gbf "github.com/kevung/gbf"
)

//go:embed schema.sql
var schemaDDL string

// pgQuerier is satisfied by both *pgxpool.Pool and pgx.Tx.
type pgQuerier interface {
	Exec(ctx context.Context, sql string, args ...any) (interface{ RowsAffected() int64 }, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
}

// PGStore implements gbf.Store backed by a PostgreSQL database.
type PGStore struct {
	pool *pgxpool.Pool
	tx   pgx.Tx // non-nil during a batch transaction
}

// NewPGStore connects to PostgreSQL using the given DSN, runs the DDL,
// and returns a PGStore ready for use.
//
// DSN format: "postgresql://user:pass@host:5432/dbname"
func NewPGStore(ctx context.Context, dsn string) (*PGStore, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, fmt.Errorf("pg connect: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pg ping: %w", err)
	}

	// Run DDL. Split on ; to execute each statement individually.
	for _, stmt := range splitStatements(schemaDDL) {
		if _, err := pool.Exec(ctx, stmt); err != nil {
			pool.Close()
			return nil, fmt.Errorf("create schema: %w (stmt: %.60s...)", err, stmt)
		}
	}

	return &PGStore{pool: pool}, nil
}

// Close releases the connection pool.
func (s *PGStore) Close() error {
	s.pool.Close()
	return nil
}

// TruncateAll removes all rows from every table, resetting sequences.
// Intended for test setup/teardown only.
func (s *PGStore) TruncateAll(ctx context.Context) {
	s.pool.Exec(ctx,
		`TRUNCATE analyses, moves, games, matches, positions RESTART IDENTITY CASCADE`)
}

// conn returns the active transaction if in a batch, otherwise the pool.
func (s *PGStore) conn() interface {
	Exec(context.Context, string, ...any) (interface{ RowsAffected() int64 }, error)
	QueryRow(context.Context, string, ...any) pgx.Row
	Query(context.Context, string, ...any) (pgx.Rows, error)
} {
	if s.tx != nil {
		return txQuerier{s.tx}
	}
	return poolQuerier{s.pool}
}

// ── Batcher ──────────────────────────────────────────────────────────────────

// BeginBatch starts a transaction that groups subsequent Store calls.
func (s *PGStore) BeginBatch(ctx context.Context) error {
	if s.tx != nil {
		return fmt.Errorf("batch already in progress")
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("begin batch: %w", err)
	}
	s.tx = tx
	return nil
}

// CommitBatch commits the current batch transaction.
func (s *PGStore) CommitBatch() error {
	if s.tx == nil {
		return fmt.Errorf("no batch in progress")
	}
	err := s.tx.Commit(context.Background())
	s.tx = nil
	return err
}

// RollbackBatch rolls back the current batch transaction.
func (s *PGStore) RollbackBatch() {
	if s.tx != nil {
		s.tx.Rollback(context.Background())
		s.tx = nil
	}
}

// ── Write methods ─────────────────────────────────────────────────────────────

// UpsertPosition inserts a position or ignores if zobrist_hash already exists.
func (s *PGStore) UpsertPosition(ctx context.Context, rec gbf.BaseRecord, boardHash uint64) (int64, error) {
	blob := gbf.MarshalBaseRecord(&rec)
	derived := gbf.ExtractDerivedFeatures(rec)
	posClass := int(derived[9])
	pipDiff := int(derived[8])
	primeLenX := int(derived[4])
	primeLenO := int(derived[5])

	conn := s.conn()
	_, err := conn.Exec(ctx, `
		INSERT INTO positions
			(zobrist_hash, board_hash, base_record,
			 pip_x, pip_o, away_x, away_o, cube_log2, cube_owner,
			 bar_x, bar_o, borne_off_x, borne_off_o, side_to_move,
			 pos_class, pip_diff, prime_len_x, prime_len_o)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
		ON CONFLICT (zobrist_hash) DO NOTHING`,
		int64(bits.RotateLeft64(rec.Zobrist, 0)),
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
	err = conn.QueryRow(ctx,
		`SELECT id FROM positions WHERE zobrist_hash = $1`,
		int64(rec.Zobrist),
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("select position id: %w", err)
	}
	return id, nil
}

// UpsertMatch inserts a match or ignores if canonical_hash already exists.
func (s *PGStore) UpsertMatch(ctx context.Context, m gbf.Match, matchHash, canonHash string) (int64, error) {
	conn := s.conn()
	_, err := conn.Exec(ctx, `
		INSERT INTO matches
			(match_hash, canonical_hash, source_format, player1, player2, match_length)
		VALUES ($1,$2,'xg',$3,$4,$5)
		ON CONFLICT (canonical_hash) DO NOTHING`,
		matchHash, canonHash,
		m.Metadata.Player1Name, m.Metadata.Player2Name,
		m.Metadata.MatchLength,
	)
	if err != nil {
		return 0, fmt.Errorf("upsert match: %w", err)
	}

	var id int64
	err = conn.QueryRow(ctx,
		`SELECT id FROM matches WHERE canonical_hash = $1`, canonHash,
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("select match id: %w", err)
	}
	return id, nil
}

// InsertGame inserts a game row for the given match. Returns the game ID.
func (s *PGStore) InsertGame(ctx context.Context, matchID int64, g gbf.Game) (int64, error) {
	crawford := 0
	if g.Crawford {
		crawford = 1
	}
	var id int64
	err := s.conn().QueryRow(ctx, `
		INSERT INTO games
			(match_id, game_number, score_x, score_o, winner, points_won, crawford)
		VALUES ($1,$2,$3,$4,$5,$6,$7)
		RETURNING id`,
		matchID, g.GameNumber,
		g.InitialScore[0], g.InitialScore[1],
		g.Winner, g.PointsWon, crawford,
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("insert game: %w", err)
	}
	return id, nil
}

// InsertMove inserts a move row linking game → position.
func (s *PGStore) InsertMove(ctx context.Context, gameID int64, moveNum int, posID int64, mv gbf.Move) error {
	_, err := s.conn().Exec(ctx, `
		INSERT INTO moves
			(game_id, move_number, position_id, player, move_type,
			 dice_1, dice_2, move_string, equity_diff, best_equity, played_equity)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
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
func (s *PGStore) AddAnalysis(ctx context.Context, posID int64, blockType uint8, engineName string, payload []byte) error {
	_, err := s.conn().Exec(ctx, `
		INSERT INTO analyses (position_id, block_type, engine_name, payload)
		VALUES ($1,$2,$3,$4)
		ON CONFLICT (position_id, block_type) DO NOTHING`,
		posID, blockType, engineName, payload,
	)
	if err != nil {
		return fmt.Errorf("add analysis: %w", err)
	}
	return nil
}

// ── Query methods ─────────────────────────────────────────────────────────────

const pgPositionCols = `
	id, zobrist_hash, board_hash, base_record,
	pip_x, pip_o, away_x, away_o, cube_log2, cube_owner,
	bar_x, bar_o, borne_off_x, borne_off_o, side_to_move,
	COALESCE(pos_class,0), COALESCE(pip_diff,0),
	COALESCE(prime_len_x,0), COALESCE(prime_len_o,0)`

// QueryByZobrist returns positions matching the context-aware hash, with analyses.
func (s *PGStore) QueryByZobrist(ctx context.Context, hash uint64) ([]gbf.PositionWithAnalyses, error) {
	rows, err := s.conn().Query(ctx,
		`SELECT`+pgPositionCols+`FROM positions WHERE zobrist_hash = $1`,
		int64(hash),
	)
	if err != nil {
		return nil, fmt.Errorf("query by zobrist: %w", err)
	}
	defer rows.Close()

	positions, err := pgScanPositions(rows)
	if err != nil {
		return nil, err
	}
	return s.attachAnalyses(ctx, positions)
}

// QueryByBoardHash returns all context variations of the same board layout.
func (s *PGStore) QueryByBoardHash(ctx context.Context, hash uint64) ([]gbf.PositionWithAnalyses, error) {
	rows, err := s.conn().Query(ctx,
		`SELECT`+pgPositionCols+`FROM positions WHERE board_hash = $1`,
		int64(hash),
	)
	if err != nil {
		return nil, fmt.Errorf("query by board hash: %w", err)
	}
	defer rows.Close()

	positions, err := pgScanPositions(rows)
	if err != nil {
		return nil, err
	}
	return s.attachAnalyses(ctx, positions)
}

// attachAnalyses fetches and bundles analysis blocks for each position.
func (s *PGStore) attachAnalyses(ctx context.Context, positions []gbf.Position) ([]gbf.PositionWithAnalyses, error) {
	result := make([]gbf.PositionWithAnalyses, len(positions))
	for i, p := range positions {
		pwa := gbf.PositionWithAnalyses{Position: p}
		rows, err := s.conn().Query(ctx,
			`SELECT block_type, COALESCE(engine_name,''), payload
			 FROM analyses WHERE position_id = $1`, p.ID)
		if err != nil {
			return nil, fmt.Errorf("query analyses for pos %d: %w", p.ID, err)
		}
		for rows.Next() {
			var a gbf.AnalysisBlock
			if err := rows.Scan(&a.BlockType, &a.EngineName, &a.Payload); err != nil {
				rows.Close()
				return nil, err
			}
			pwa.Analyses = append(pwa.Analyses, a)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		result[i] = pwa
	}
	return result, nil
}

// QueryByMatchScore returns position summaries filtered by away scores.
func (s *PGStore) QueryByMatchScore(ctx context.Context, awayX, awayO int) ([]gbf.PositionSummary, error) {
	var conds []string
	var args []any
	if awayX >= 0 {
		args = append(args, awayX)
		conds = append(conds, fmt.Sprintf("away_x = $%d", len(args)))
	}
	if awayO >= 0 {
		args = append(args, awayO)
		conds = append(conds, fmt.Sprintf("away_o = $%d", len(args)))
	}

	q := `SELECT id,
	             COALESCE(pos_class,0), pip_x, pip_o, COALESCE(pip_diff,0),
	             away_x, away_o, cube_log2, cube_owner, bar_x, bar_o,
	             COALESCE(prime_len_x,0), COALESCE(prime_len_o,0)
	      FROM positions`
	if len(conds) > 0 {
		q += " WHERE " + strings.Join(conds, " AND ")
	}

	rows, err := s.conn().Query(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("query by match score: %w", err)
	}
	defer rows.Close()

	var out []gbf.PositionSummary
	for rows.Next() {
		var p gbf.PositionSummary
		if err := rows.Scan(
			&p.ID, &p.PosClass, &p.PipX, &p.PipO, &p.PipDiff,
			&p.AwayX, &p.AwayO, &p.CubeLog2, &p.CubeOwner,
			&p.BarX, &p.BarO, &p.PrimeLenX, &p.PrimeLenO,
		); err != nil {
			return nil, fmt.Errorf("scan position summary: %w", err)
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// QueryByFeatures returns positions with their moves, filtered by the supplied QueryFilter.
func (s *PGStore) QueryByFeatures(ctx context.Context, f gbf.QueryFilter) ([]gbf.PositionWithMoves, error) {
	sqliteQ, args := gbf.BuildFeatureQuery(f)
	q := toPgParams(sqliteQ)

	rows, err := s.conn().Query(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("query by features: %w", err)
	}
	defer rows.Close()

	positions, err := pgScanPositions(rows)
	if err != nil {
		return nil, err
	}

	result := make([]gbf.PositionWithMoves, len(positions))
	for i, p := range positions {
		pwm := gbf.PositionWithMoves{Position: p}
		mrows, err := s.conn().Query(ctx,
			`SELECT id, game_id, move_number, player, COALESCE(move_type,''),
			        COALESCE(dice_1,0), COALESCE(dice_2,0), COALESCE(move_string,''),
			        equity_diff, best_equity, played_equity
			 FROM moves WHERE position_id = $1`, p.ID)
		if err != nil {
			return nil, fmt.Errorf("query moves for pos %d: %w", p.ID, err)
		}
		for mrows.Next() {
			var mv gbf.MoveRow
			var ed, be, pe *int
			if err := mrows.Scan(
				&mv.ID, &mv.GameID, &mv.MoveNumber, &mv.Player, &mv.MoveType,
				&mv.Dice[0], &mv.Dice[1], &mv.MoveString,
				&ed, &be, &pe,
			); err != nil {
				mrows.Close()
				return nil, fmt.Errorf("scan move: %w", err)
			}
			mv.EquityDiff = ed
			mv.BestEquity = be
			mv.PlayedEquity = pe
			pwm.Moves = append(pwm.Moves, mv)
		}
		mrows.Close()
		if err := mrows.Err(); err != nil {
			return nil, err
		}
		result[i] = pwm
	}
	return result, nil
}

// QueryScoreDistribution returns position counts and avg equity loss per score.
func (s *PGStore) QueryScoreDistribution(ctx context.Context) ([]gbf.ScoreDistribution, error) {
	rows, err := s.conn().Query(ctx, `
		SELECT p.away_x, p.away_o,
		       COUNT(DISTINCT p.id) AS cnt,
		       COALESCE(AVG(m.equity_diff::REAL), 0) AS avg_diff
		FROM positions p
		LEFT JOIN moves m ON m.position_id = p.id
		GROUP BY p.away_x, p.away_o
		ORDER BY p.away_x, p.away_o`)
	if err != nil {
		return nil, fmt.Errorf("score distribution: %w", err)
	}
	defer rows.Close()

	var out []gbf.ScoreDistribution
	for rows.Next() {
		var d gbf.ScoreDistribution
		if err := rows.Scan(&d.AwayX, &d.AwayO, &d.Count, &d.AvgEquityDiff); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// QueryPositionClassDistribution returns position counts per class.
func (s *PGStore) QueryPositionClassDistribution(ctx context.Context) (map[int]int, error) {
	rows, err := s.conn().Query(ctx,
		`SELECT COALESCE(pos_class,0), COUNT(*) FROM positions GROUP BY pos_class`)
	if err != nil {
		return nil, fmt.Errorf("class distribution: %w", err)
	}
	defer rows.Close()

	dist := make(map[int]int)
	for rows.Next() {
		var cls, cnt int
		if err := rows.Scan(&cls, &cnt); err != nil {
			return nil, err
		}
		dist[cls] += cnt
	}
	return dist, rows.Err()
}

// ── Internal helpers ──────────────────────────────────────────────────────────

// pgScanPositions scans pgx.Rows into []gbf.Position.
func pgScanPositions(rows pgx.Rows) ([]gbf.Position, error) {
	var positions []gbf.Position
	for rows.Next() {
		var p gbf.Position
		var zobrist, board int64
		var blob []byte

		if err := rows.Scan(
			&p.ID, &zobrist, &board, &blob,
			&p.PipX, &p.PipO, &p.AwayX, &p.AwayO,
			&p.CubeLog2, &p.CubeOwner,
			&p.BarX, &p.BarO, &p.BorneOffX, &p.BorneOffO,
			&p.SideToMove,
			&p.PosClass, &p.PipDiff, &p.PrimeLenX, &p.PrimeLenO,
		); err != nil {
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

// toPgParams converts SQLite-style ? placeholders to PostgreSQL $N style.
func toPgParams(sql string) string {
	var sb strings.Builder
	n := 0
	for _, c := range sql {
		if c == '?' {
			n++
			sb.WriteString(fmt.Sprintf("$%d", n))
		} else {
			sb.WriteRune(c)
		}
	}
	return sb.String()
}

// splitStatements splits a SQL script on semicolons, returning non-empty statements.
func splitStatements(ddl string) []string {
	parts := strings.Split(ddl, ";")
	var out []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// ── Querier adapters ──────────────────────────────────────────────────────────

// pgxpool.Pool wraps pgx commands but its Exec returns pgconn.CommandTag,
// not the interface{ RowsAffected() int64 } we declared. We adapt here.

type poolQuerier struct{ p *pgxpool.Pool }

func (q poolQuerier) Exec(ctx context.Context, sql string, args ...any) (interface{ RowsAffected() int64 }, error) {
	tag, err := q.p.Exec(ctx, sql, args...)
	return tag, err
}
func (q poolQuerier) QueryRow(ctx context.Context, sql string, args ...any) pgx.Row {
	return q.p.QueryRow(ctx, sql, args...)
}
func (q poolQuerier) Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error) {
	return q.p.Query(ctx, sql, args...)
}

type txQuerier struct{ tx pgx.Tx }

func (q txQuerier) Exec(ctx context.Context, sql string, args ...any) (interface{ RowsAffected() int64 }, error) {
	tag, err := q.tx.Exec(ctx, sql, args...)
	return tag, err
}
func (q txQuerier) QueryRow(ctx context.Context, sql string, args ...any) pgx.Row {
	return q.tx.QueryRow(ctx, sql, args...)
}
func (q txQuerier) Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error) {
	return q.tx.Query(ctx, sql, args...)
}
