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

// Store defines the minimal interface for GBF storage backends.
// Implementations: SQLiteStore (local), PGStore (production SaaS).
// The interface grows with each milestone.
type Store interface {
	// UpsertPosition inserts a position or ignores if it already exists
	// (matched by zobrist_hash). Returns the position ID.
	UpsertPosition(ctx context.Context, rec BaseRecord, boardHash uint64) (int64, error)

	// QueryByZobrist returns all positions matching the given context-aware hash.
	QueryByZobrist(ctx context.Context, hash uint64) ([]Position, error)

	// Close releases the store's resources.
	Close() error
}
