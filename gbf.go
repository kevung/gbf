// Package gbf implements the Gammon Binary Format (GBF) v1.0.
//
// GBF is a deterministic, compact binary format for representing backgammon
// positions and associated engine analysis. It provides a unified interface
// for parsing backgammon files from multiple sources (eXtreme Gammon, GNU
// Backgammon, BGBlitz) and serializing them into the GBF binary format.
//
// Point indexing:
//
//	0  = Player X 1-point (home)
//	23 = Player X 24-point
//
// Player convention:
//
//	PlayerX = 0 (bottom player, moving from 24 to 1)
//	PlayerO = 1 (top player, moving from 1 to 24)
package gbf

const (
	// NumPoints is the number of backgammon points on the board.
	NumPoints = 24

	// MaxCheckers is the maximum number of checkers per player.
	MaxCheckers = 15

	// PlayerX is the first player (bottom, moving high to low).
	PlayerX = 0
	// PlayerO is the second player (top, moving low to high).
	PlayerO = 1

	// CubeCenter means the cube is centered (neither player owns it).
	CubeCenter = 0
	// CubeX means Player X owns the cube.
	CubeX = 1
	// CubeO means Player O owns the cube.
	CubeO = 2

	// BaseRecordSize is the padded base record size in bytes.
	BaseRecordSize = 80
	// BaseRecordPayload is the actual payload size before padding.
	BaseRecordPayload = 66
	// PaddingSize is the number of padding bytes.
	PaddingSize = BaseRecordSize - BaseRecordPayload

	// Block types for analysis blocks.
	BlockTypeCheckerPlay    = 1
	BlockTypeCubeDecision   = 2
	BlockTypeEngineMetadata = 3
	BlockTypeMatchMetadata  = 4
	BlockTypeGameBoundary   = 5

	// Move encoding constants.
	MoveFromBar   = 24  // from_point = 24 means entering from bar
	MoveToBearOff = 24  // to_point = 24 means bearing off
	MoveUnused    = 255 // unused move slot sentinel

	// Cube best action values.
	CubeActionNoDouble   = 0
	CubeActionDoubleTake = 1
	CubeActionDoublePass = 2
)

// Record represents a complete GBF record: a base position plus optional
// analysis blocks.
type Record struct {
	Base   BaseRecord
	Blocks []AnalysisBlock
}

// BaseRecord is the 80-byte base record for a backgammon position.
type BaseRecord struct {
	// LayersX contains 4 layer bitboards for Player X.
	// Each uint32 has 24 significant bits (bit i = point i).
	LayersX [4]uint32

	// LayersO contains 4 layer bitboards for Player O.
	LayersO [4]uint32

	// PointCounts stores exact checker counts per point (4 bits each).
	// The player occupying each point is determined by the layer bitboards.
	PointCounts [24]uint8

	// BarX is the number of Player X checkers on the bar (0-15).
	BarX uint8
	// BarO is the number of Player O checkers on the bar (0-15).
	BarO uint8
	// BorneOffX is the number of Player X checkers borne off (0-15).
	BorneOffX uint8
	// BorneOffO is the number of Player O checkers borne off (0-15).
	BorneOffO uint8

	// SideToMove: 0 = Player X, 1 = Player O.
	SideToMove uint8

	// CubeLog2 is log2 of the cube value (0=1, 1=2, 2=4, etc.).
	CubeLog2 uint8
	// CubeOwner: 0 = centered, 1 = X, 2 = O.
	CubeOwner uint8

	// AwayX is the number of points Player X needs to win the match.
	AwayX uint8
	// AwayO is the number of points Player O needs to win the match.
	AwayO uint8

	// PipX is Player X's pip count.
	PipX uint16
	// PipO is Player O's pip count.
	PipO uint16

	// Zobrist is the context-aware deterministic hash of this position.
	Zobrist uint64

	// BlockCount is the number of analysis blocks following this base record.
	BlockCount uint8
}

// AnalysisBlock represents a generic analysis block following the base record.
type AnalysisBlock struct {
	BlockType   uint8
	Version     uint8
	BlockLength uint16
	Payload     []byte // raw payload; use typed accessors
}

// CheckerPlayAnalysis represents a decoded block_type=1 analysis block.
type CheckerPlayAnalysis struct {
	MoveCount uint8
	Moves     []CheckerMoveAnalysis
}

// CheckerMoveAnalysis represents analysis for one candidate move.
type CheckerMoveAnalysis struct {
	Equity            int32  // scaled x10000
	WinRate           uint16 // scaled x10000 (10000 = 100%)
	GammonRate        uint16
	BackgammonRate    uint16
	OppWinRate        uint16
	OppGammonRate     uint16
	OppBackgammonRate uint16
	EquityDiff        int16 // scaled x10000
	PlyDepth          uint8
	Reserved          uint8
	Move              MoveEncoding
}

// MoveEncoding encodes up to 4 checker sub-moves.
// Each sub-move is a (from, to) pair. Unused slots have from=to=MoveUnused.
type MoveEncoding struct {
	Submoves [4][2]uint8 // [i][0]=from, [i][1]=to
}

// CubeDecisionAnalysis represents a decoded block_type=2 analysis block.
type CubeDecisionAnalysis struct {
	WinRate           uint16 // scaled x10000
	GammonRate        uint16
	BackgammonRate    uint16
	OppWinRate        uint16
	OppGammonRate     uint16
	OppBackgammonRate uint16
	CubelessNoDouble  int32 // scaled x10000
	CubelessDouble    int32
	CubefulNoDouble   int32
	CubefulDoubleTake int32
	CubefulDoublePass int32
	BestAction        uint8 // 0=NoDouble, 1=Double/Take, 2=Double/Pass
}

// EngineMetadata represents a decoded block_type=3 metadata block.
type EngineMetadata struct {
	EngineName    string
	EngineVersion string
	METName       string
	AnalysisType  uint8
}

// GameBoundary represents a decoded block_type=5 game boundary marker.
type GameBoundary struct {
	GameNumber uint16
	ScoreX     uint16
	ScoreO     uint16
	Winner     int8  // 0=player1, 1=player2, -1=unfinished
	PointsWon  uint8
	Crawford   uint8 // 1 if Crawford game
	MoveCount  uint16
}

// Match represents a complete backgammon match parsed from any supported format.
type Match struct {
	Metadata MatchMetadata
	Games    []Game
}

// MatchMetadata contains match-level information.
type MatchMetadata struct {
	Player1Name   string
	Player2Name   string
	MatchLength   int // 0 = unlimited/money game
	Event         string
	Location      string
	Round         string
	Date          string
	Annotator     string
	EngineName    string
	EngineVersion string
	METName       string
}

// Game represents a single game within a match.
type Game struct {
	GameNumber   int
	InitialScore [2]int // score at start of game [player1, player2]
	Moves        []Move
	Winner       int // 0=player1, 1=player2, -1=unfinished
	PointsWon    int
	Crawford     bool
}

// Move represents a single action (checker move or cube action) within a game.
type Move struct {
	MoveType        MoveType
	Player          int    // 0=player1, 1=player2
	Dice            [2]int // dice values (0,0 for cube actions)
	MoveString      string // human-readable move notation
	CubeAction      string // for cube moves: "Double", "Take", "Pass", etc.
	Position        *PositionState
	CheckerAnalysis *CheckerPlayAnalysis
	CubeAnalysis    *CubeDecisionAnalysis
	EngineMetadata  *EngineMetadata
	// Equity columns for DB storage (x10000 scale, computed during conversion).
	BestEquity   int32 // equity of the best candidate move
	PlayedEquity int32 // equity of the move actually played
	EquityDiff   int32 // abs(BestEquity - PlayedEquity), always >= 0
}

// MoveType identifies the type of action.
type MoveType string

const (
	MoveTypeChecker MoveType = "checker"
	MoveTypeCube    MoveType = "cube"
	MoveTypeTake    MoveType = "take"
	MoveTypePass    MoveType = "pass"
	MoveTypeResign  MoveType = "resign"
)

// PositionState represents the board state at a given point in the game,
// using the GBF normalized representation.
type PositionState struct {
	// Board stores checker counts per point.
	// Positive = Player X, Negative = Player O.
	// Index 0 = point 1 (Player X home), Index 23 = point 24.
	Board [24]int

	// Bar checkers per player.
	BarX int
	BarO int

	// Borne off checkers per player.
	BorneOffX int
	BorneOffO int

	// Cube state.
	CubeValue int // actual value (1, 2, 4, 8, ...)
	CubeOwner int // CubeCenter, CubeX, or CubeO

	// Side to move: PlayerX or PlayerO.
	SideToMove int

	// Score state (away scores).
	AwayX int
	AwayO int

	// Match length (0 = unlimited).
	MatchLength int

	// Crawford flag.
	Crawford bool

	// Dice (0,0 if not rolled yet or cube decision).
	Dice [2]int

	// Player names for reference.
	Player1Name string
	Player2Name string

	// XGID string if available from source.
	XGID string
}
