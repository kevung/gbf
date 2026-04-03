package convert

import (
	"fmt"
	"math"
	"sort"
	"strings"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/xgparser/xgparser"
)

// ParseXGFile parses an eXtreme Gammon file and returns a GBF Match.
func ParseXGFile(filename string) (*gbf.Match, error) {
	xgMatch, err := xgparser.ParseXGFromFile(filename)
	if err != nil {
		return nil, fmt.Errorf("parsing XG file: %w", err)
	}
	return ConvertXGMatch(xgMatch)
}

// ConvertXGMatch converts an xgparser.Match into a gbf.Match.
func ConvertXGMatch(xgMatch *xgparser.Match) (*gbf.Match, error) {
	if xgMatch == nil {
		return nil, fmt.Errorf("nil XG match")
	}

	m := &gbf.Match{
		Metadata: gbf.MatchMetadata{
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

func convertXGGame(xgGame *xgparser.Game, matchLength int32) (*gbf.Game, error) {
	game := &gbf.Game{
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

func convertXGMove(xgMove *xgparser.Move, xgGame *xgparser.Game, matchLength int32) (*gbf.Move, error) {
	mv := &gbf.Move{}

	switch xgMove.MoveType {
	case "checker":
		if xgMove.CheckerMove == nil {
			return nil, fmt.Errorf("nil checker move")
		}
		mv.MoveType = gbf.MoveTypeChecker
		mv.Player = convertXGPlayer(xgMove.CheckerMove.ActivePlayer)
		mv.Dice = [2]int{int(xgMove.CheckerMove.Dice[0]), int(xgMove.CheckerMove.Dice[1])}
		mv.MoveString = convertXGMoveToString(xgMove.CheckerMove.PlayedMove, &xgMove.CheckerMove.Position, xgMove.CheckerMove.ActivePlayer)

		pos := convertXGPosition(xgMove.CheckerMove.Position, xgGame, matchLength, xgMove.CheckerMove.ActivePlayer)
		pos.Dice = mv.Dice
		mv.Position = pos

		if len(xgMove.CheckerMove.Analysis) > 0 {
			mv.CheckerAnalysis = convertXGCheckerAnalysis(xgMove.CheckerMove.Analysis)
		}

	case "cube":
		if xgMove.CubeMove == nil {
			return nil, fmt.Errorf("nil cube move")
		}
		mv.MoveType = gbf.MoveTypeCube
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

		if xgMove.CubeMove.Analysis != nil {
			mv.CubeAnalysis = convertXGCubeAnalysis(xgMove.CubeMove.Analysis)
		}

	default:
		return nil, fmt.Errorf("unknown move type: %s", xgMove.MoveType)
	}

	return mv, nil
}

func convertXGPosition(xgPos xgparser.Position, xgGame *xgparser.Game, matchLength int32, activePlayer int32) *gbf.PositionState {
	pos := &gbf.PositionState{
		CubeValue:  int(xgPos.Cube),
		SideToMove: convertXGPlayer(activePlayer),
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	activeGBF := convertXGPlayer(activePlayer)
	opponentGBF := 1 - activeGBF

	switch xgPos.CubePos {
	case 0:
		pos.CubeOwner = gbf.CubeCenter
	case 1:
		if activeGBF == gbf.PlayerX {
			pos.CubeOwner = gbf.CubeX
		} else {
			pos.CubeOwner = gbf.CubeO
		}
	case -1:
		if opponentGBF == gbf.PlayerX {
			pos.CubeOwner = gbf.CubeX
		} else {
			pos.CubeOwner = gbf.CubeO
		}
	default:
		pos.CubeOwner = gbf.CubeCenter
	}

	if matchLength > 0 {
		pos.AwayX = int(matchLength) - int(xgGame.InitialScore[0])
		pos.AwayO = int(matchLength) - int(xgGame.InitialScore[1])
		pos.MatchLength = int(matchLength)
	}

	for i := 0; i < 24; i++ {
		checkerCount := xgPos.Checkers[i]
		if checkerCount == 0 {
			continue
		}

		var gbfIndex int
		if activeGBF == gbf.PlayerO {
			gbfIndex = 23 - i
		} else {
			gbfIndex = i
		}

		var ownerSign int
		if checkerCount > 0 {
			if activeGBF == gbf.PlayerX {
				ownerSign = 1
			} else {
				ownerSign = -1
			}
		} else {
			if opponentGBF == gbf.PlayerX {
				ownerSign = 1
			} else {
				ownerSign = -1
			}
		}

		pos.Board[gbfIndex] = ownerSign * int(absInt8(checkerCount))
	}

	activeBar := int(absInt8(xgPos.Checkers[25]))
	opponentBar := int(absInt8(xgPos.Checkers[24]))

	if activeGBF == gbf.PlayerX {
		pos.BarX = activeBar
		pos.BarO = opponentBar
	} else {
		pos.BarO = activeBar
		pos.BarX = opponentBar
	}

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
	borneOffX := gbf.MaxCheckers - totalX
	borneOffO := gbf.MaxCheckers - totalO
	if borneOffX < 0 {
		borneOffX = 0
	}
	if borneOffO < 0 {
		borneOffO = 0
	}
	pos.BorneOffX = borneOffX
	pos.BorneOffO = borneOffO

	return pos
}

func convertXGPlayer(xgPlayer int32) int {
	if xgPlayer == 1 {
		return gbf.PlayerX
	}
	return gbf.PlayerO
}

func absInt8(x int8) int8 {
	if x < 0 {
		return -x
	}
	return x
}

func convertXGCheckerAnalysis(xgMoves []xgparser.CheckerAnalysis) *gbf.CheckerPlayAnalysis {
	cpa := &gbf.CheckerPlayAnalysis{
		MoveCount: uint8(len(xgMoves)),
	}

	for _, xgMA := range xgMoves {
		ma := gbf.CheckerMoveAnalysis{
			Equity:            int32(math.Round(float64(xgMA.Equity) * 10000)),
			WinRate:           uint16(math.Round(float64(xgMA.Player1WinRate) * 10000)),
			GammonRate:        uint16(math.Round(float64(xgMA.Player1GammonRate) * 10000)),
			BackgammonRate:    uint16(math.Round(float64(xgMA.Player1BgRate) * 10000)),
			OppWinRate:        uint16(math.Round(float64(1-xgMA.Player1WinRate) * 10000)),
			OppGammonRate:     uint16(math.Round(float64(xgMA.Player2GammonRate) * 10000)),
			OppBackgammonRate: uint16(math.Round(float64(xgMA.Player2BgRate) * 10000)),
			PlyDepth:          uint8(xgMA.AnalysisDepth),
		}

		for j := 0; j < 4; j++ {
			if j*2 < len(xgMA.Move) && j*2+1 < len(xgMA.Move) {
				from := xgMA.Move[j*2]
				to := xgMA.Move[j*2+1]
				if from == -1 {
					ma.Move.Submoves[j] = [2]uint8{gbf.MoveUnused, gbf.MoveUnused}
				} else {
					ma.Move.Submoves[j] = [2]uint8{convertXGPoint(from), convertXGPoint(to)}
				}
			} else {
				ma.Move.Submoves[j] = [2]uint8{gbf.MoveUnused, gbf.MoveUnused}
			}
		}

		cpa.Moves = append(cpa.Moves, ma)
	}

	if len(cpa.Moves) > 0 {
		bestEquity := cpa.Moves[0].Equity
		for i := range cpa.Moves {
			cpa.Moves[i].EquityDiff = int16(cpa.Moves[i].Equity - bestEquity)
		}
	}

	return cpa
}

func convertXGCubeAnalysis(xgCA *xgparser.CubeAnalysis) *gbf.CubeDecisionAnalysis {
	cda := &gbf.CubeDecisionAnalysis{
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

	noDouble := float64(xgCA.CubefulNoDouble)
	doubleTake := float64(xgCA.CubefulDoubleTake)
	doublePass := float64(xgCA.CubefulDoublePass)

	if noDouble >= doubleTake && noDouble >= doublePass {
		cda.BestAction = gbf.CubeActionNoDouble
	} else if doublePass > doubleTake {
		cda.BestAction = gbf.CubeActionDoublePass
	} else {
		cda.BestAction = gbf.CubeActionDoubleTake
	}

	return cda
}

func convertXGPoint(p int8) uint8 {
	switch {
	case p == 25:
		return gbf.MoveFromBar
	case p == -2 || p == 0:
		return gbf.MoveToBearOff
	case p == -1:
		return gbf.MoveUnused
	default:
		return uint8(p - 1)
	}
}

func convertXGMoveToString(playedMove [8]int32, initialPos *xgparser.Position, activePlayer int32) string {
	type moveWithHit struct {
		from  int32
		to    int32
		isHit bool
	}

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
