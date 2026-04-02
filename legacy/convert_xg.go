package gbf

import (
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/kevung/xgparser/xgparser"
)

// ConvertXGMatch converts an xgparser.Match into a gbf.Match.
func ConvertXGMatch(xgMatch *xgparser.Match) (*Match, error) {
	if xgMatch == nil {
		return nil, fmt.Errorf("nil XG match")
	}

	m := &Match{
		Metadata: MatchMetadata{
			Player1Name:   xgMatch.Metadata.Player1Name,
			Player2Name:   xgMatch.Metadata.Player2Name,
			MatchLength:   int(xgMatch.Metadata.MatchLength),
			Event:         xgMatch.Metadata.Event,
			Location:      xgMatch.Metadata.Location,
			Round:         xgMatch.Metadata.Round,
			Date:          xgMatch.Metadata.DateTime,
			EngineName:    "eXtreme Gammon",
			EngineVersion: xgMatch.Metadata.ProductVersion,
			METName:       xgMatch.Metadata.MET,
		},
	}

	for _, xgGame := range xgMatch.Games {
		game, err := convertXGGame(&xgGame, xgMatch.Metadata.MatchLength)
		if err != nil {
			return nil, fmt.Errorf("game %d: %w", xgGame.GameNumber, err)
		}
		m.Games = append(m.Games, *game)
	}

	return m, nil
}

func convertXGGame(xgGame *xgparser.Game, matchLength int32) (*Game, error) {
	game := &Game{
		GameNumber:   int(xgGame.GameNumber),
		InitialScore: [2]int{int(xgGame.InitialScore[0]), int(xgGame.InitialScore[1])},
		Winner:       int(xgGame.Winner),
		PointsWon:    int(xgGame.PointsWon),
	}

	for _, xgMove := range xgGame.Moves {
		mv, err := convertXGMove(&xgMove, xgGame, matchLength)
		if err != nil {
			continue // skip unparseable moves
		}
		game.Moves = append(game.Moves, *mv)
	}

	return game, nil
}

func convertXGMove(xgMove *xgparser.Move, xgGame *xgparser.Game, matchLength int32) (*Move, error) {
	mv := &Move{}

	switch xgMove.MoveType {
	case "checker":
		if xgMove.CheckerMove == nil {
			return nil, fmt.Errorf("nil checker move")
		}
		mv.MoveType = MoveTypeChecker
		mv.Player = convertXGPlayer(xgMove.CheckerMove.ActivePlayer)
		mv.Dice = [2]int{int(xgMove.CheckerMove.Dice[0]), int(xgMove.CheckerMove.Dice[1])}
		mv.MoveString = convertXGMoveToString(xgMove.CheckerMove.PlayedMove, &xgMove.CheckerMove.Position, xgMove.CheckerMove.ActivePlayer)

		pos := convertXGPosition(xgMove.CheckerMove.Position, xgGame, matchLength, xgMove.CheckerMove.ActivePlayer)
		pos.Dice = mv.Dice
		mv.Position = pos

		// Convert checker analysis
		if len(xgMove.CheckerMove.Analysis) > 0 {
			mv.CheckerAnalysis = convertXGCheckerAnalysis(xgMove.CheckerMove.Analysis)
		}

	case "cube":
		if xgMove.CubeMove == nil {
			return nil, fmt.Errorf("nil cube move")
		}
		mv.MoveType = MoveTypeCube
		mv.Player = convertXGPlayer(xgMove.CubeMove.ActivePlayer)
		mv.Dice = [2]int{0, 0}

		switch xgMove.CubeMove.CubeAction {
		case 1:
			mv.CubeAction = "Double"
		case 2:
			mv.CubeAction = "Take"
		case 3:
			mv.CubeAction = "Pass"
		default:
			mv.CubeAction = "No Double"
		}

		pos := convertXGPosition(xgMove.CubeMove.Position, xgGame, matchLength, xgMove.CubeMove.ActivePlayer)
		mv.Position = pos

		// Convert cube analysis
		if xgMove.CubeMove.Analysis != nil {
			mv.CubeAnalysis = convertXGCubeAnalysis(xgMove.CubeMove.Analysis)
		}

	default:
		return nil, fmt.Errorf("unknown move type: %s", xgMove.MoveType)
	}

	return mv, nil
}

// convertXGPosition converts an xgparser.Position into a GBF PositionState.
// XG board encoding:
//
//	Checkers[0-23] = points 1-24 (0-based indexing, but XG uses 1-based internally)
//	Checkers[24] = opponent's bar
//	Checkers[25] = active player's bar
//	Positive = active player, Negative = opponent
//
// GBF board encoding:
//
//	Board[0-23] = points 1-24 (index 0 = Player X 1-point)
//	Positive = Player X, Negative = Player O
func convertXGPosition(xgPos xgparser.Position, xgGame *xgparser.Game, matchLength int32, activePlayer int32) *PositionState {
	pos := &PositionState{
		CubeValue:  int(xgPos.Cube),
		SideToMove: convertXGPlayer(activePlayer),
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	// Convert cube owner from XG relative to GBF absolute
	activeBlunderDB := convertXGPlayer(activePlayer)
	opponentBlunderDB := 1 - activeBlunderDB

	switch xgPos.CubePos {
	case 0:
		pos.CubeOwner = CubeCenter
	case 1:
		if activeBlunderDB == PlayerX {
			pos.CubeOwner = CubeX
		} else {
			pos.CubeOwner = CubeO
		}
	case -1:
		if opponentBlunderDB == PlayerX {
			pos.CubeOwner = CubeX
		} else {
			pos.CubeOwner = CubeO
		}
	default:
		pos.CubeOwner = CubeCenter
	}

	// Convert away scores
	if matchLength > 0 {
		pos.AwayX = int(matchLength) - int(xgGame.InitialScore[0])
		pos.AwayO = int(matchLength) - int(xgGame.InitialScore[1])
		pos.MatchLength = int(matchLength)
	}

	// Convert checkers
	// XG convention: activePlayer sees positive values as own checkers
	for i := 0; i < 24; i++ {
		checkerCount := xgPos.Checkers[i]
		if checkerCount == 0 {
			continue
		}

		// Determine the GBF point index
		var gbfIndex int
		if activeBlunderDB == PlayerO {
			// Player O perspective: mirror the board
			gbfIndex = 23 - i
		} else {
			// Player X perspective: direct mapping
			gbfIndex = i
		}

		var ownerSign int
		if checkerCount > 0 {
			// Active player's checkers
			if activeBlunderDB == PlayerX {
				ownerSign = 1 // positive = X
			} else {
				ownerSign = -1 // negative = O
			}
		} else {
			// Opponent's checkers
			if opponentBlunderDB == PlayerX {
				ownerSign = 1
			} else {
				ownerSign = -1
			}
		}

		pos.Board[gbfIndex] = ownerSign * int(absInt8(checkerCount))
	}

	// Convert bars
	// XG[24] = opponent's bar, XG[25] = active player's bar
	activeBar := int(absInt8(xgPos.Checkers[25]))
	opponentBar := int(absInt8(xgPos.Checkers[24]))

	if activeBlunderDB == PlayerX {
		pos.BarX = activeBar
		pos.BarO = opponentBar
	} else {
		pos.BarO = activeBar
		pos.BarX = opponentBar
	}

	// Compute borne off from remaining checkers
	var totalX, totalO int
	for i := 0; i < 24; i++ {
		if pos.Board[i] > 0 {
			totalX += pos.Board[i]
		} else if pos.Board[i] < 0 {
			totalO += -pos.Board[i]
		}
	}
	totalX += pos.BarX
	totalO += pos.BarO
	pos.BorneOffX = MaxCheckers - totalX
	pos.BorneOffO = MaxCheckers - totalO

	return pos
}

func convertXGPlayer(xgPlayer int32) int {
	// XG: -1 = Player 1 (maps to PlayerX=0), 1 = Player 2 (maps to PlayerO=1)
	// But actually XG uses 1 = Player 1 and -1 = Player 2 based on blunderDB's convertXGPlayerToBlunderDB:
	// xgPlayer == 1 → return 0 (Player 1)
	// else → return 1 (Player 2)
	if xgPlayer == 1 {
		return PlayerX
	}
	return PlayerO
}

func absInt8(x int8) int8 {
	if x < 0 {
		return -x
	}
	return x
}

func convertXGCheckerAnalysis(xgMoves []xgparser.CheckerAnalysis) *CheckerPlayAnalysis {
	cpa := &CheckerPlayAnalysis{
		MoveCount: uint8(len(xgMoves)),
	}

	for _, xgMA := range xgMoves {
		ma := CheckerMoveAnalysis{
			Equity:            int32(math.Round(float64(xgMA.Equity) * 10000)),
			WinRate:           uint16(math.Round(float64(xgMA.Player1WinRate) * 10000)),
			GammonRate:        uint16(math.Round(float64(xgMA.Player1GammonRate) * 10000)),
			BackgammonRate:    uint16(math.Round(float64(xgMA.Player1BgRate) * 10000)),
			OppWinRate:        uint16(math.Round(float64(1-xgMA.Player1WinRate) * 10000)),
			OppGammonRate:     uint16(math.Round(float64(xgMA.Player2GammonRate) * 10000)),
			OppBackgammonRate: uint16(math.Round(float64(xgMA.Player2BgRate) * 10000)),
			PlyDepth:          uint8(xgMA.AnalysisDepth),
		}

		// Convert move encoding
		for j := 0; j < 4; j++ {
			if j*2 < len(xgMA.Move) && j*2+1 < len(xgMA.Move) {
				from := xgMA.Move[j*2]
				to := xgMA.Move[j*2+1]
				if from == -1 {
					ma.Move.Submoves[j] = [2]uint8{MoveUnused, MoveUnused}
				} else {
					ma.Move.Submoves[j] = [2]uint8{convertXGPoint(from), convertXGPoint(to)}
				}
			} else {
				ma.Move.Submoves[j] = [2]uint8{MoveUnused, MoveUnused}
			}
		}

		cpa.Moves = append(cpa.Moves, ma)
	}

	// Compute equity diff relative to best move
	if len(cpa.Moves) > 0 {
		bestEquity := cpa.Moves[0].Equity
		for i := range cpa.Moves {
			cpa.Moves[i].EquityDiff = int16(cpa.Moves[i].Equity - bestEquity)
		}
	}

	return cpa
}

func convertXGCubeAnalysis(xgCA *xgparser.CubeAnalysis) *CubeDecisionAnalysis {
	cda := &CubeDecisionAnalysis{
		WinRate:           uint16(math.Round(float64(xgCA.Player1WinRate) * 10000)),
		GammonRate:        uint16(math.Round(float64(xgCA.Player1GammonRate) * 10000)),
		BackgammonRate:    uint16(math.Round(float64(xgCA.Player1BgRate) * 10000)),
		OppWinRate:        uint16(math.Round(float64(1-xgCA.Player1WinRate) * 10000)),
		OppGammonRate:     uint16(math.Round(float64(xgCA.Player2GammonRate) * 10000)),
		OppBackgammonRate: uint16(math.Round(float64(xgCA.Player2BgRate) * 10000)),
		CubelessNoDouble:  int32(math.Round(float64(xgCA.CubelessNoDouble) * 10000)),
		CubelessDouble:    int32(math.Round(float64(xgCA.CubelessDouble) * 10000)),
		CubefulNoDouble:   int32(math.Round(float64(xgCA.CubefulNoDouble) * 10000)),
		CubefulDoubleTake: int32(math.Round(float64(xgCA.CubefulDoubleTake) * 10000)),
		CubefulDoublePass: int32(math.Round(float64(xgCA.CubefulDoublePass) * 10000)),
	}

	// Determine best action from cubeful equities
	noDouble := float64(xgCA.CubefulNoDouble)
	doubleTake := float64(xgCA.CubefulDoubleTake)
	doublePass := float64(xgCA.CubefulDoublePass)

	if noDouble >= doubleTake && noDouble >= doublePass {
		cda.BestAction = CubeActionNoDouble
	} else if doublePass > doubleTake {
		cda.BestAction = CubeActionDoublePass
	} else {
		cda.BestAction = CubeActionDoubleTake
	}

	return cda
}

func convertXGPoint(p int8) uint8 {
	switch {
	case p == 25:
		return MoveFromBar // 24 = from bar
	case p == -2 || p == 0:
		return MoveToBearOff // 24 = bear off
	case p == -1:
		return MoveUnused
	default:
		// XG uses 1-based points, GBF uses 0-based
		return uint8(p - 1)
	}
}

// convertXGMoveToString converts an XG move encoding to standard notation.
func convertXGMoveToString(playedMove [8]int32, initialPos *xgparser.Position, activePlayer int32) string {
	type moveWithHit struct {
		from  int32
		to    int32
		isHit bool
	}

	// Track position changes for hit detection
	positionCopy := make([]int8, 26)
	if initialPos != nil {
		copy(positionCopy, initialPos.Checkers[:])
	}

	var items []moveWithHit
	for i := 0; i < 8; i += 2 {
		from := playedMove[i]
		to := playedMove[i+1]
		if from == -1 {
			break
		}
		// Normalize bear-off
		if from >= 1 && from <= 6 && to <= 0 && to != -2 {
			to = -2
		}

		isHit := false
		if initialPos != nil && to >= 1 && to <= 24 {
			if positionCopy[to] == -1 {
				isHit = true
				positionCopy[to] = 0
			}
		}

		// Update position tracking
		if initialPos != nil {
			if from >= 1 && from <= 24 && positionCopy[from] > 0 {
				positionCopy[from]--
			} else if from == 25 && positionCopy[25] > 0 {
				positionCopy[25]--
			}
			if to >= 1 && to <= 24 {
				positionCopy[to]++
			}
		}

		items = append(items, moveWithHit{from: from, to: to, isHit: isHit})
	}

	if len(items) == 0 {
		return "Cannot Move"
	}

	// Sort by from point descending
	sort.Slice(items, func(i, j int) bool {
		return items[i].from > items[j].from
	})

	formatPoint := func(p int32) string {
		if p == 25 {
			return "bar"
		} else if p == -2 {
			return "off"
		}
		return fmt.Sprintf("%d", p)
	}

	var moves []string
	for i := 0; i < len(items); {
		item := items[i]
		count := 1
		for j := i + 1; j < len(items); j++ {
			if items[j].from == item.from && items[j].to == item.to {
				count++
			} else {
				break
			}
		}

		hitStr := ""
		if item.isHit {
			hitStr = "*"
		}

		if count > 1 {
			moves = append(moves, fmt.Sprintf("%s/%s%s(%d)", formatPoint(item.from), formatPoint(item.to), hitStr, count))
		} else {
			moves = append(moves, fmt.Sprintf("%s/%s%s", formatPoint(item.from), formatPoint(item.to), hitStr))
		}
		i += count
	}

	return strings.Join(moves, " ")
}

// ParseXGFile parses an eXtreme Gammon file and returns a GBF Match.
func ParseXGFile(filename string) (*Match, error) {
	xgMatch, err := xgparser.ParseXGFromFile(filename)
	if err != nil {
		return nil, fmt.Errorf("parsing XG file: %w", err)
	}
	return ConvertXGMatch(xgMatch)
}
