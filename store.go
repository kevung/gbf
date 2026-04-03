package gbf

import "context"

// Position represents a stored position as returned by query methods.
type Position struct {
	ID          int64
	ZobristHash uint64
	BoardHash   uint64
	BaseRecord  BaseRecord
	PipX        int
	PipO        int
	AwayX       int
	AwayO       int
	CubeLog2    int
	CubeOwner   int
	BarX        int
	BarO        int
	BorneOffX   int
	BorneOffO   int
	SideToMove  int
}

// Store defines the interface for GBF storage backends.
// Implementations: SQLiteStore (local), PGStore (production SaaS).
type Store interface {
	// UpsertPosition inserts a position or ignores if it already exists
	// (matched by zobrist_hash). Returns the position ID.
	UpsertPosition(ctx context.Context, rec BaseRecord, boardHash uint64) (int64, error)

	// QueryByZobrist returns all positions matching the given context-aware hash.
	QueryByZobrist(ctx context.Context, hash uint64) ([]Position, error)

	// UpsertMatch inserts a match or ignores if canonical_hash already exists.
	// Returns the match ID (existing or newly inserted).
	UpsertMatch(ctx context.Context, m Match, matchHash, canonHash string) (int64, error)

	// InsertGame inserts a game row for the given match.
	// Returns the game ID.
	InsertGame(ctx context.Context, matchID int64, g Game) (int64, error)

	// InsertMove inserts a move row linking game → position.
	InsertMove(ctx context.Context, gameID int64, moveNum int, posID int64, mv Move) error

	// AddAnalysis inserts an analysis block for a position.
	AddAnalysis(ctx context.Context, posID int64, blockType uint8, engineName string, payload []byte) error

	// Close releases the store's resources.
	Close() error
}
