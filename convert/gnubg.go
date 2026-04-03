package convert

import (
	"fmt"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gnubgparser"
)

// ParseSGFFile parses a GNU Backgammon SGF file and returns a GBF Match.
func ParseSGFFile(path string) (*gbf.Match, error) {
	gnuMatch, err := gnubgparser.ParseSGFFile(path)
	if err != nil {
		return nil, fmt.Errorf("parsing SGF file: %w", err)
	}
	return convertGnuBGMatch(gnuMatch, true)
}

// ParseMATFile parses a GNU Backgammon MAT file and returns a GBF Match.
func ParseMATFile(path string) (*gbf.Match, error) {
	gnuMatch, err := gnubgparser.ParseMATFile(path)
	if err != nil {
		return nil, fmt.Errorf("parsing MAT file: %w", err)
	}
	return convertGnuBGMatch(gnuMatch, false)
}

func convertGnuBGMatch(gnuMatch *gnubgparser.Match, isSGF bool) (*gbf.Match, error) {
	if gnuMatch == nil {
		return nil, fmt.Errorf("nil GnuBG match")
	}

	m := &gbf.Match{
		Metadata: gbf.MatchMetadata{
			Player1Name:   gnuMatch.Metadata.Player1,
			Player2Name:   gnuMatch.Metadata.Player2,
			MatchLength:   gnuMatch.Metadata.MatchLength,
			Event:         gnuMatch.Metadata.Event,
			Location:      gnuMatch.Metadata.Place,
			Round:         gnuMatch.Metadata.Round,
			Date:          gnuMatch.Metadata.Date,
			Annotator:     gnuMatch.Metadata.Annotator,
			EngineName:    "GNU Backgammon",
			EngineVersion: gnuMatch.Metadata.Application,
		},
	}

	currentBoard := initStandardGnuBGPosition()

	for _, gnuGame := range gnuMatch.Games {
		game, err := convertGnuBGGame(&gnuGame, gnuMatch.Metadata.MatchLength, isSGF, &currentBoard)
		if err != nil {
			return nil, fmt.Errorf("game %d: %w", gnuGame.GameNumber, err)
		}
		m.Games = append(m.Games, *game)
		currentBoard = initStandardGnuBGPosition()
	}

	return m, nil
}

func initStandardGnuBGPosition() gnubgparser.Position {
	var pos gnubgparser.Position
	pos.CubeValue = 1
	pos.CubeOwner = -1
	for p := 0; p < 2; p++ {
		pos.Board[p][23] = 2
		pos.Board[p][12] = 5
		pos.Board[p][7] = 3
		pos.Board[p][5] = 5
	}
	return pos
}

func convertGnuBGGame(gnuGame *gnubgparser.Game, matchLength int, isSGF bool, currentBoard *gnubgparser.Position) (*gbf.Game, error) {
	game := &gbf.Game{
		GameNumber:   gnuGame.GameNumber,
		InitialScore: [2]int{gnuGame.Score[0], gnuGame.Score[1]},
		Winner:       gnuGame.Winner,
		PointsWon:    gnuGame.Points,
		Crawford:     gnuGame.CrawfordGame,
	}

	for i, moveRec := range gnuGame.Moves {
		switch moveRec.Type {
		case "setboard":
			if moveRec.Position != nil {
				*currentBoard = *moveRec.Position
			}
			continue
		case "setdice":
			continue
		case "setcube":
			currentBoard.CubeValue = moveRec.CubeValue
			continue
		case "setcubepos":
			currentBoard.CubeOwner = moveRec.CubeOwner
			continue
		case "take", "drop", "resign":
			continue
		}

		cubeAction := ""
		if moveRec.Type == "double" {
			for j := i + 1; j < len(gnuGame.Moves); j++ {
				if gnuGame.Moves[j].Type == "take" {
					cubeAction = "Double/Take"
					break
				} else if gnuGame.Moves[j].Type == "drop" {
					cubeAction = "Double/Pass"
					break
				} else if gnuGame.Moves[j].Type != "setdice" && gnuGame.Moves[j].Type != "setboard" {
					break
				}
			}
			if cubeAction == "" {
				cubeAction = "Double"
			}
		}

		mv, err := convertGnuBGMove(&moveRec, gnuGame, matchLength, isSGF, currentBoard, cubeAction)
		if err != nil {
			continue
		}
		game.Moves = append(game.Moves, *mv)

		if moveRec.Type == "move" {
			applyGnuBGCheckerMove(currentBoard, &moveRec, isSGF)
		} else if moveRec.Type == "double" {
			currentBoard.CubeValue *= 2
			currentBoard.CubeOwner = 1 - moveRec.Player
		}
	}

	return game, nil
}

func convertGnuBGMove(moveRec *gnubgparser.MoveRecord, game *gnubgparser.Game, matchLength int, isSGF bool, currentBoard *gnubgparser.Position, cubeAction string) (*gbf.Move, error) {
	mv := &gbf.Move{
		Player: moveRec.Player,
	}

	switch moveRec.Type {
	case "move":
		mv.MoveType = gbf.MoveTypeChecker
		mv.Dice = [2]int{moveRec.Dice[0], moveRec.Dice[1]}

		if isSGF {
			mv.MoveString = convertGnuBGMoveToString(moveRec.Move, moveRec.Player)
		} else {
			mv.MoveString = moveRec.MoveString
		}

		posForConversion := currentBoard
		if moveRec.Position != nil {
			posForConversion = moveRec.Position
		}
		pos := convertGnuBGPosition(posForConversion, game, matchLength)
		pos.SideToMove = moveRec.Player
		pos.Dice = mv.Dice
		mv.Position = pos

		if moveRec.Analysis != nil && isSGF {
			mv.CheckerAnalysis = convertGnuBGCheckerAnalysis(moveRec.Analysis, moveRec.Player, isSGF)
		}
		if moveRec.CubeAnalysis != nil {
			mv.CubeAnalysis = convertGnuBGCubeAnalysis(moveRec.CubeAnalysis)
		}

	case "double":
		mv.MoveType = gbf.MoveTypeCube
		mv.Dice = [2]int{0, 0}
		mv.CubeAction = cubeAction

		posForConversion := currentBoard
		if moveRec.Position != nil {
			posForConversion = moveRec.Position
		}
		pos := convertGnuBGPosition(posForConversion, game, matchLength)
		pos.SideToMove = moveRec.Player
		mv.Position = pos

		if moveRec.CubeAnalysis != nil {
			mv.CubeAnalysis = convertGnuBGCubeAnalysis(moveRec.CubeAnalysis)
		}

	default:
		return nil, fmt.Errorf("unsupported move type: %s", string(moveRec.Type))
	}

	return mv, nil
}

// convertGnuBGPosition converts a gnubgparser.Position into a GBF PositionState.
// GnuBG board encoding:
//
//	Board[player][0-23] = player-relative points (0=ace/home, 23=far)
//	Board[player][24] = bar
//
// GBF encoding:
//
//	Board[0-23] = points (0 = Player X 1-point)
//	Positive = Player X, Negative = Player O
func convertGnuBGPosition(gnuPos *gnubgparser.Position, game *gnubgparser.Game, matchLength int) *gbf.PositionState {
	pos := &gbf.PositionState{
		SideToMove: gnuPos.OnRoll,
		CubeValue:  gnuPos.CubeValue,
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	switch gnuPos.CubeOwner {
	case -1:
		pos.CubeOwner = gbf.CubeCenter
	case 0:
		pos.CubeOwner = gbf.CubeX
	case 1:
		pos.CubeOwner = gbf.CubeO
	default:
		pos.CubeOwner = gbf.CubeCenter
	}

	if matchLength > 0 {
		pos.AwayX = matchLength - game.Score[0]
		pos.AwayO = matchLength - game.Score[1]
		pos.MatchLength = matchLength
	}

	pos.Crawford = gnuPos.Crawford

	// Player 0 (X): Board[0][pt] — pt=0 is X's ace point = GBF point 0
	for pt := 0; pt < 24; pt++ {
		count := gnuPos.Board[0][pt]
		if count > 0 {
			pos.Board[pt] += count
		}
	}

	// Player 1 (O): Board[1][pt] — pt=0 is O's ace point = GBF point 23
	for pt := 0; pt < 24; pt++ {
		count := gnuPos.Board[1][pt]
		if count > 0 {
			gbfPt := 23 - pt
			pos.Board[gbfPt] -= count
		}
	}

	pos.BarX = gnuPos.Board[0][24]
	pos.BarO = gnuPos.Board[1][24]

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
	pos.BorneOffX = gbf.MaxCheckers - totalX
	pos.BorneOffO = gbf.MaxCheckers - totalO

	return pos
}

func applyGnuBGCheckerMove(board *gnubgparser.Position, moveRec *gnubgparser.MoveRecord, isAbsoluteCoords bool) {
	player := moveRec.Player
	opponent := 1 - player

	for i := 0; i < 8; i += 2 {
		from := moveRec.Move[i]
		to := moveRec.Move[i+1]
		if from == -1 {
			break
		}

		var fromBoard, toBoard, opponentBoard int
		var isBearOff bool

		if isAbsoluteCoords {
			fromBoard = from
			if player == 1 && from != 24 {
				fromBoard = 23 - from
			}
			isBearOff = (to == 25)
			if !isBearOff {
				toBoard = to
				if player == 1 {
					toBoard = 23 - to
				}
				if player == 0 {
					opponentBoard = 23 - to
				} else {
					opponentBoard = to
				}
			}
		} else {
			fromBoard = from
			isBearOff = (to == -1)
			if !isBearOff {
				toBoard = to
				opponentBoard = 23 - to
			}
		}

		if fromBoard >= 0 && fromBoard <= 24 {
			board.Board[player][fromBoard]--
		}

		if isBearOff {
			continue
		}

		if opponentBoard >= 0 && opponentBoard <= 23 {
			if board.Board[opponent][opponentBoard] == 1 {
				board.Board[opponent][opponentBoard] = 0
				board.Board[opponent][24]++
			}
		}

		if toBoard >= 0 && toBoard <= 24 {
			board.Board[player][toBoard]++
		}
	}
}

func convertGnuBGMoveToString(move [8]int, player int) string {
	formatPoint := func(pt int, p int) string {
		if pt == 24 {
			return "bar"
		}
		if pt == 25 {
			return "off"
		}
		if p == 0 {
			return fmt.Sprintf("%d", pt+1)
		}
		return fmt.Sprintf("%d", 24-pt)
	}

	type moveItem struct {
		from string
		to   string
	}

	var items []moveItem
	for i := 0; i < 8; i += 2 {
		from := move[i]
		to := move[i+1]
		if from == -1 {
			break
		}
		items = append(items, moveItem{
			from: formatPoint(from, player),
			to:   formatPoint(to, player),
		})
	}

	if len(items) == 0 {
		return "Cannot Move"
	}

	// Sort by from descending
	for i := 1; i < len(items); i++ {
		for j := i; j > 0 && gnuPointValue(items[j-1].from) < gnuPointValue(items[j].from); j-- {
			items[j-1], items[j] = items[j], items[j-1]
		}
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
		if count > 1 {
			moves = append(moves, fmt.Sprintf("%s/%s(%d)", item.from, item.to, count))
		} else {
			moves = append(moves, fmt.Sprintf("%s/%s", item.from, item.to))
		}
		i += count
	}

	result := ""
	for i, s := range moves {
		if i > 0 {
			result += " "
		}
		result += s
	}
	return result
}

func gnuPointValue(s string) int {
	if s == "bar" {
		return 25
	}
	if s == "off" {
		return 0
	}
	v := 0
	fmt.Sscanf(s, "%d", &v)
	return v
}

func convertGnuBGCheckerAnalysis(analysis *gnubgparser.MoveAnalysis, player int, isSGF bool) *gbf.CheckerPlayAnalysis {
	cpa := &gbf.CheckerPlayAnalysis{
		MoveCount: uint8(len(analysis.Moves)),
	}

	for _, moveOpt := range analysis.Moves {
		ma := gbf.CheckerMoveAnalysis{
			Equity:            roundToInt32(moveOpt.Equity * 10000),
			WinRate:           roundToUint16(float64(moveOpt.Player1WinRate) * 10000),
			GammonRate:        roundToUint16(float64(moveOpt.Player1GammonRate) * 10000),
			BackgammonRate:    roundToUint16(float64(moveOpt.Player1BackgammonRate) * 10000),
			OppWinRate:        roundToUint16(float64(moveOpt.Player2WinRate) * 10000),
			OppGammonRate:     roundToUint16(float64(moveOpt.Player2GammonRate) * 10000),
			OppBackgammonRate: roundToUint16(float64(moveOpt.Player2BackgammonRate) * 10000),
			PlyDepth:          uint8(moveOpt.AnalysisDepth),
		}

		for j := 0; j < 4; j++ {
			idx := j * 2
			if idx+1 < len(moveOpt.Move) && moveOpt.Move[idx] != -1 {
				from := moveOpt.Move[idx]
				to := moveOpt.Move[idx+1]

				var gbfFrom, gbfTo uint8
				if from == 24 {
					gbfFrom = gbf.MoveFromBar
				} else if from == 25 || from == -1 {
					gbfFrom = gbf.MoveUnused
				} else {
					if isSGF {
						if player == 0 {
							gbfFrom = uint8(from)
						} else {
							gbfFrom = uint8(23 - from)
						}
					} else {
						gbfFrom = uint8(from)
					}
				}

				if to == 25 || to == -1 {
					gbfTo = gbf.MoveToBearOff
				} else {
					if isSGF {
						if player == 0 {
							gbfTo = uint8(to)
						} else {
							gbfTo = uint8(23 - to)
						}
					} else {
						gbfTo = uint8(to)
					}
				}

				ma.Move.Submoves[j] = [2]uint8{gbfFrom, gbfTo}
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

func convertGnuBGCubeAnalysis(analysis *gnubgparser.CubeAnalysis) *gbf.CubeDecisionAnalysis {
	cda := &gbf.CubeDecisionAnalysis{
		WinRate:           roundToUint16(float64(analysis.Player1WinRate) * 10000),
		GammonRate:        roundToUint16(float64(analysis.Player1GammonRate) * 10000),
		BackgammonRate:    roundToUint16(float64(analysis.Player1BackgammonRate) * 10000),
		OppWinRate:        roundToUint16(float64(analysis.Player2WinRate) * 10000),
		OppGammonRate:     roundToUint16(float64(analysis.Player2GammonRate) * 10000),
		OppBackgammonRate: roundToUint16(float64(analysis.Player2BackgammonRate) * 10000),
		CubelessNoDouble:  roundToInt32(analysis.CubelessEquity * 10000),
		CubefulNoDouble:   roundToInt32(analysis.CubefulNoDouble * 10000),
		CubefulDoubleTake: roundToInt32(analysis.CubefulDoubleTake * 10000),
		CubefulDoublePass: roundToInt32(analysis.CubefulDoublePass * 10000),
	}

	switch analysis.BestAction {
	case "No double":
		cda.BestAction = gbf.CubeActionNoDouble
	case "Double, take":
		cda.BestAction = gbf.CubeActionDoubleTake
	case "Double, pass":
		cda.BestAction = gbf.CubeActionDoublePass
	default:
		noDouble := analysis.CubefulNoDouble
		doubleTake := analysis.CubefulDoubleTake
		doublePass := analysis.CubefulDoublePass
		if noDouble >= doubleTake && noDouble >= doublePass {
			cda.BestAction = gbf.CubeActionNoDouble
		} else if doublePass > doubleTake {
			cda.BestAction = gbf.CubeActionDoublePass
		} else {
			cda.BestAction = gbf.CubeActionDoubleTake
		}
	}

	return cda
}
