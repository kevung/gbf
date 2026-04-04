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
	// M9 derived columns (0 if not yet backfilled).
	PosClass  int
	PipDiff   int
	PrimeLenX int
	PrimeLenO int
}

// PositionWithAnalyses bundles a position with all its stored analysis blocks.
type PositionWithAnalyses struct {
	Position
	Analyses []AnalysisBlock
}

// MoveRow is a move record as returned by query methods.
type MoveRow struct {
	ID           int64
	GameID       int64
	MoveNumber   int
	Player       int
	MoveType     string
	Dice         [2]int
	MoveString   string
	EquityDiff   *int // nil when NULL
	BestEquity   *int
	PlayedEquity *int
}

// PositionWithMoves bundles a position with associated move rows.
type PositionWithMoves struct {
	Position
	Moves []MoveRow
}

// PositionSummary is a lightweight position row (no BaseRecord blob).
// Used for large result sets where the full 80-byte record is not needed.
type PositionSummary struct {
	ID        int64
	PosClass  int
	PipX      int
	PipO      int
	PipDiff   int
	AwayX     int
	AwayO     int
	CubeLog2  int
	CubeOwner int
	BarX      int
	BarO      int
	PrimeLenX int
	PrimeLenO int
}

// ScoreDistribution holds aggregated stats for one away-score combination.

// MatchMetadataRow holds match metadata for display purposes.
type MatchMetadataRow struct {
	MatchID     int64
	Player1     string
	Player2     string
	MatchLength int
	Event       string
	Date        string
}
type ScoreDistribution struct {
	AwayX         int
	AwayO         int
	Count         int
	AvgEquityDiff float64 // average equity loss (×10000 units)
}

// QueryFilter defines optional filters for QueryByFeatures.
// Nil pointer fields are ignored; only non-nil fields constrain the query.
// Use the Ptr helper to build filter pointers inline.
type QueryFilter struct {
	PosClass     *int // 0=contact, 1=race, 2=bearoff
	AwayX        *int
	AwayO        *int
	PipDiffMin   *int
	PipDiffMax   *int
	PrimeLenXMin *int // X prime length ≥ value
	PrimeLenOMin *int // O prime length ≥ value
	CubeLog2     *int
	CubeOwner    *int // 0=center, 1=X, 2=O
	BarXMin      *int // bar_x ≥ value
	BarOMin      *int
	// EquityDiffMin, when non-nil, triggers a JOIN with the moves table.
	// Value is in ×10000 units (e.g. 1000 = 0.1 equity loss).
	EquityDiffMin *int
	// Limit caps the number of returned rows (default 100 when 0).
	Limit int
}

// Ptr is a convenience helper to get a pointer to an int literal.
//
//	filter := QueryFilter{PosClass: gbf.Ptr(gbf.ClassContact)}
func Ptr(v int) *int { return &v }

// Store defines the interface for GBF storage backends.
// Implementations: SQLiteStore (local), PGStore (production SaaS, M7).
type Store interface {
	// ── Write methods ────────────────────────────────────────────────────

	// UpsertPosition inserts a position or ignores if it already exists
	// (matched by zobrist_hash). Returns the position ID.
	UpsertPosition(ctx context.Context, rec BaseRecord, boardHash uint64) (int64, error)

	// UpsertMatch inserts a match or ignores if canonical_hash already exists.
	// Returns the match ID (existing or newly inserted).
	UpsertMatch(ctx context.Context, m Match, matchHash, canonHash string) (int64, error)

	// InsertGame inserts a game row for the given match. Returns the game ID.
	InsertGame(ctx context.Context, matchID int64, g Game) (int64, error)

	// InsertMove inserts a move row linking game → position.
	InsertMove(ctx context.Context, gameID int64, moveNum int, posID int64, mv Move) error

	// AddAnalysis inserts an analysis block for a position.
	AddAnalysis(ctx context.Context, posID int64, blockType uint8, engineName string, payload []byte) error

	// ── Lookup queries ───────────────────────────────────────────────────

	// QueryByZobrist returns positions matching the context-aware hash,
	// including all associated analysis blocks.
	QueryByZobrist(ctx context.Context, hash uint64) ([]PositionWithAnalyses, error)

	// QueryByBoardHash returns all context variations (different cube/score)
	// for the same board layout, including analyses.
	QueryByBoardHash(ctx context.Context, hash uint64) ([]PositionWithAnalyses, error)

	// ── Filtered queries ─────────────────────────────────────────────────

	// QueryByMatchScore returns position summaries filtered by away scores.
	// Use -1 as a wildcard for awayX or awayO to match any value.
	QueryByMatchScore(ctx context.Context, awayX, awayO int) ([]PositionSummary, error)

	// QueryByFeatures returns positions with their moves, filtered by the
	// supplied QueryFilter. Setting EquityDiffMin triggers a JOIN with moves.
	QueryByFeatures(ctx context.Context, f QueryFilter) ([]PositionWithMoves, error)

	// ── Aggregations ─────────────────────────────────────────────────────

	// QueryScoreDistribution returns position counts and average equity loss
	// per (away_x, away_o) combination, ordered by (away_x, away_o).
	QueryScoreDistribution(ctx context.Context) ([]ScoreDistribution, error)

	// QueryPositionClassDistribution returns the count of positions per class
	// (0=contact, 1=race, 2=bearoff).
	QueryPositionClassDistribution(ctx context.Context) (map[int]int, error)

	// ── Projections (M8) ─────────────────────────────────────────────────

	// CreateProjectionRun inserts a new projection run and returns its ID.
	CreateProjectionRun(ctx context.Context, run ProjectionRun) (int64, error)

	// ActivateProjectionRun sets is_active=true for the given run and
	// deactivates all other runs with the same method AND lod.
	ActivateProjectionRun(ctx context.Context, runID int64) error

	// InsertProjectionBatch inserts a batch of projection points for a run.
	InsertProjectionBatch(ctx context.Context, runID int64, pts []ProjectionPoint) error

	// ActiveProjectionRun returns the currently active run for the given
	// (method, lod) pair, or (nil, nil) if none.
	ActiveProjectionRun(ctx context.Context, method string, lod int) (*ProjectionRun, error)

	// ListActiveProjectionRuns returns all active runs across all methods and
	// LoD levels, ordered by method, lod.
	ListActiveProjectionRuns(ctx context.Context) ([]ProjectionRun, error)

	// QueryProjections returns projection points for the active run of the
	// given method and lod, with optional filters.
	QueryProjections(ctx context.Context, method string, lod int, f ProjectionFilter) ([]ProjectionRow, error)

	// QueryClusterSummary returns per-cluster counts and centroids for the
	// active run of the given method and lod.
	QueryClusterSummary(ctx context.Context, method string, lod int) ([]ClusterSummary, error)

	// ── Tiles (M10.4) ────────────────────────────────────────────────────

	// InsertTileBatch inserts a batch of pre-computed slippy-map tiles.
	InsertTileBatch(ctx context.Context, tiles []Tile) error

	// QueryTile returns the gzipped JSON payload for tile (zoom, tileX, tileY)
	// in the given run, or (nil, nil) if the tile does not exist (empty).
	QueryTile(ctx context.Context, runID int64, zoom, tileX, tileY int) ([]byte, error)

	// QueryTileMeta returns zoom range, tile count, and bounds for a run.
	// Returns (nil, nil) if no tiles exist for the run.
	QueryTileMeta(ctx context.Context, runID int64) (*TileMeta, error)

	// QueryProjectionsByRunID returns all projection points for a specific run.
	QueryProjectionsByRunID(ctx context.Context, runID int64) ([]ProjectionRow, error)

	// GCProjectionTiles deletes tiles whose projection run is no longer active.
	GCProjectionTiles(ctx context.Context) error

	// ── Lifecycle ────────────────────────────────────────────────────────

	// Close releases the store's resources.
	Close() error
}

// ── Projection types (M8) ────────────────────────────────────────────────────

// ProjectionRun describes a versioned projection computation.
type ProjectionRun struct {
	ID             int64
	Method         string // e.g. "umap_2d", "pca_2d"
	FeatureVersion string // e.g. "v1.0"
	Params         string // JSON string
	NPoints        int
	CreatedAt      string
	IsActive       bool
	// M10.3: LoD level (0=5-10K overview, 1=50-100K medium, 2=complete).
	LoD        int    `json:"lod"`
	BoundsJSON string `json:"bounds_json,omitempty"` // {"min_x":…,"max_x":…,"min_y":…,"max_y":…}
}

// ProjectionPoint is a single point to insert (no ID, no run_id).
type ProjectionPoint struct {
	PositionID int64
	X          float32
	Y          float32
	Z          *float32 // nil for 2D
	ClusterID  *int
}

// ProjectionRow is a stored projection point returned by queries.
type ProjectionRow struct {
	PositionID int64    `json:"position_id"`
	X          float32  `json:"x"`
	Y          float32  `json:"y"`
	Z          *float32 `json:"z,omitempty"`
	ClusterID  *int     `json:"cluster_id,omitempty"`
	// Joined position attributes (populated when filter is used).
	AwayX    int `json:"away_x"`
	AwayO    int `json:"away_o"`
	PosClass int `json:"pos_class"`
}

// ProjectionFilter constrains QueryProjections results.
type ProjectionFilter struct {
	ClusterID *int
	AwayX     *int
	AwayO     *int
	PosClass  *int
	Limit     int // 0 = default (10000)
	Offset    int
}

// ClusterSummary holds aggregate stats for one cluster in a projection run.
type ClusterSummary struct {
	ClusterID int     `json:"cluster_id"`
	Count     int     `json:"count"`
	CentroidX float64 `json:"centroid_x"`
	CentroidY float64 `json:"centroid_y"`
}

// Tile is a pre-computed slippy-map tile for a projection run.
// Data holds gzipped JSON of []TilePoint.
type Tile struct {
	RunID   int64
	Zoom    int
	TileX   int
	TileY   int
	NPoints int
	Data    []byte // gzipped JSON [{id,x,y,c,pc}, ...]
}

// TileMeta summarises the tile coverage for a projection run.
type TileMeta struct {
	RunID      int64  `json:"run_id"`
	MinZoom    int    `json:"min_zoom"`
	MaxZoom    int    `json:"max_zoom"`
	TileCount  int    `json:"tile_count"`
	NPoints    int    `json:"n_points"`
	BoundsJSON string `json:"bounds_json,omitempty"`
}
