package gbf

import (
	"fmt"
	"io"
	"math"
	"sort"
	"strings"

	"github.com/kevung/gnubgparser"
)

// ConvertGnuBGMatch converts a gnubgparser.Match into a gbf.Match.
func ConvertGnuBGMatch(gnuMatch *gnubgparser.Match, isSGF bool) (*Match, error) {
	if gnuMatch == nil {
		return nil, fmt.Errorf("nil GnuBG match")
	}

	m := &Match{
		Metadata: MatchMetadata{
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

	// Track board state for position tracking (SGF has absolute coords)
	currentBoard := initStandardGnuBGPosition()

	for _, gnuGame := range gnuMatch.Games {
		game, err := convertGnuBGGame(&gnuGame, gnuMatch.Metadata.MatchLength, isSGF, &currentBoard)
		if err != nil {
			return nil, fmt.Errorf("game %d: %w", gnuGame.GameNumber, err)
		}
		m.Games = append(m.Games, *game)

		// Reset board for next game
		currentBoard = initStandardGnuBGPosition()
	}

	return m, nil
}

func initStandardGnuBGPosition() gnubgparser.Position {
	var pos gnubgparser.Position
	pos.CubeValue = 1
	pos.CubeOwner = -1 // center

	// Standard starting position (same for both players from their own perspective)
	for p := 0; p < 2; p++ {
		pos.Board[p][23] = 2 // 24-point: 2 checkers
		pos.Board[p][12] = 5 // 13-point: 5 checkers
		pos.Board[p][7] = 3  // 8-point: 3 checkers
		pos.Board[p][5] = 5  // 6-point: 5 checkers
	}

	return pos
}

func convertGnuBGGame(gnuGame *gnubgparser.Game, matchLength int, isSGF bool, currentBoard *gnubgparser.Position) (*Game, error) {
	game := &Game{
		GameNumber:   gnuGame.GameNumber,
		InitialScore: [2]int{gnuGame.Score[0], gnuGame.Score[1]},
		Winner:       gnuGame.Winner,
		PointsWon:    gnuGame.Points,
		Crawford:     gnuGame.CrawfordGame,
	}

	for i, moveRec := range gnuGame.Moves {
		// Handle control moves that update board state
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
			// These are responses to doubles, skip as standalone moves
			continue
		}

		// Look ahead for cube response
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

		// Update board state for checker moves
		if moveRec.Type == "move" {
			applyGnuBGCheckerMove(currentBoard, &moveRec, isSGF)
		} else if moveRec.Type == "double" {
			// Update cube state
			currentBoard.CubeValue *= 2
			currentBoard.CubeOwner = 1 - moveRec.Player // opponent owns after double/take
		}
	}

	return game, nil
}

func convertGnuBGMove(moveRec *gnubgparser.MoveRecord, game *gnubgparser.Game, matchLength int, isSGF bool, currentBoard *gnubgparser.Position, cubeAction string) (*Move, error) {
	mv := &Move{
		Player: moveRec.Player,
	}

	switch moveRec.Type {
	case "move":
		mv.MoveType = MoveTypeChecker
		mv.Dice = [2]int{moveRec.Dice[0], moveRec.Dice[1]}

		if isSGF {
			mv.MoveString = convertGnuBGMoveToString(moveRec.Move, moveRec.Player)
		} else {
			mv.MoveString = moveRec.MoveString
		}

		// Convert position
		posForConversion := currentBoard
		if moveRec.Position != nil {
			posForConversion = moveRec.Position
		}
		pos := convertGnuBGPosition(posForConversion, game, matchLength)
		pos.SideToMove = moveRec.Player
		pos.Dice = mv.Dice
		mv.Position = pos

		// Convert checker analysis (SGF only)
		if moveRec.Analysis != nil && isSGF {
			mv.CheckerAnalysis = convertGnuBGCheckerAnalysis(moveRec.Analysis, moveRec.Player, isSGF)
		}

		// Convert cube analysis
		if moveRec.CubeAnalysis != nil {
			mv.CubeAnalysis = convertGnuBGCubeAnalysis(moveRec.CubeAnalysis)
		}

	case "double":
		mv.MoveType = MoveTypeCube
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
func convertGnuBGPosition(gnuPos *gnubgparser.Position, game *gnubgparser.Game, matchLength int) *PositionState {
	pos := &PositionState{
		SideToMove: gnuPos.OnRoll,
		CubeValue:  gnuPos.CubeValue,
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	// Cube owner: gnubg uses -1=center, 0=player0, 1=player1
	// GBF uses 0=center, 1=X, 2=O
	switch gnuPos.CubeOwner {
	case -1:
		pos.CubeOwner = CubeCenter
	case 0:
		pos.CubeOwner = CubeX
	case 1:
		pos.CubeOwner = CubeO
	default:
		pos.CubeOwner = CubeCenter
	}

	// Away scores
	if matchLength > 0 {
		pos.AwayX = matchLength - game.Score[0]
		pos.AwayO = matchLength - game.Score[1]
		pos.MatchLength = matchLength
	}

	pos.Crawford = gnuPos.Crawford

	// Place Player 0 (X) checkers
	// gnubg Board[0][pt] where pt=0 is player's ace (home) point
	// In absolute terms: Player 0's pt maps to GBF point (pt)
	// Player 0's ace (pt=0) = GBF point 0 (X's 1-point) ✓
	for pt := 0; pt < 24; pt++ {
		count := gnuPos.Board[0][pt]
		if count > 0 {
			pos.Board[pt] += count // positive = Player X
		}
	}

	// Place Player 1 (O) checkers
	// gnubg Board[1][pt] where pt=0 is player 1's ace
	// Player 1 moves opposite: their pt=0 = GBF point 23, pt=23 = GBF point 0
	for pt := 0; pt < 24; pt++ {
		count := gnuPos.Board[1][pt]
		if count > 0 {
			gbfPt := 23 - pt
			pos.Board[gbfPt] -= count // negative = Player O
		}
	}

	// Bars
	pos.BarX = gnuPos.Board[0][24]
	pos.BarO = gnuPos.Board[1][24]

	// Compute borne off
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
	sort.Slice(items, func(i, j int) bool {
		fi := pointValue(items[i].from)
		fj := pointValue(items[j].from)
		return fi > fj
	})

	// Group identical
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

	return strings.Join(moves, " ")
}

func pointValue(s string) int {
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

func convertGnuBGCheckerAnalysis(analysis *gnubgparser.MoveAnalysis, player int, isSGF bool) *CheckerPlayAnalysis {
	cpa := &CheckerPlayAnalysis{
		MoveCount: uint8(len(analysis.Moves)),
	}

	for _, moveOpt := range analysis.Moves {
		ma := CheckerMoveAnalysis{
			Equity:            int32(math.Round(moveOpt.Equity * 10000)),
			WinRate:           uint16(math.Round(float64(moveOpt.Player1WinRate) * 10000)),
			GammonRate:        uint16(math.Round(float64(moveOpt.Player1GammonRate) * 10000)),
			BackgammonRate:    uint16(math.Round(float64(moveOpt.Player1BackgammonRate) * 10000)),
			OppWinRate:        uint16(math.Round(float64(moveOpt.Player2WinRate) * 10000)),
			OppGammonRate:     uint16(math.Round(float64(moveOpt.Player2GammonRate) * 10000)),
			OppBackgammonRate: uint16(math.Round(float64(moveOpt.Player2BackgammonRate) * 10000)),
			PlyDepth:          uint8(moveOpt.AnalysisDepth),
		}

		// Convert move encoding
		for j := 0; j < 4; j++ {
			idx := j * 2
			if idx+1 < len(moveOpt.Move) && moveOpt.Move[idx] != -1 {
				from := moveOpt.Move[idx]
				to := moveOpt.Move[idx+1]

				// Convert gnubg point to GBF point
				var gbfFrom, gbfTo uint8
				if from == 24 {
					gbfFrom = MoveFromBar
				} else if from == 25 || from == -1 {
					gbfFrom = MoveUnused
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
					gbfTo = MoveToBearOff
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
				ma.Move.Submoves[j] = [2]uint8{MoveUnused, MoveUnused}
			}
		}

		cpa.Moves = append(cpa.Moves, ma)
	}

	// Compute equity diffs
	if len(cpa.Moves) > 0 {
		bestEquity := cpa.Moves[0].Equity
		for i := range cpa.Moves {
			cpa.Moves[i].EquityDiff = int16(cpa.Moves[i].Equity - bestEquity)
		}
	}

	return cpa
}

func convertGnuBGCubeAnalysis(analysis *gnubgparser.CubeAnalysis) *CubeDecisionAnalysis {
	// Note: GnuBG stores win rates as fractions (0.0-1.0)
	// GBF stores them scaled ×10000
	cda := &CubeDecisionAnalysis{
		WinRate:           uint16(math.Round(float64(analysis.Player1WinRate) * 10000)),
		GammonRate:        uint16(math.Round(float64(analysis.Player1GammonRate) * 10000)),
		BackgammonRate:    uint16(math.Round(float64(analysis.Player1BackgammonRate) * 10000)),
		OppWinRate:        uint16(math.Round(float64(analysis.Player2WinRate) * 10000)),
		OppGammonRate:     uint16(math.Round(float64(analysis.Player2GammonRate) * 10000)),
		OppBackgammonRate: uint16(math.Round(float64(analysis.Player2BackgammonRate) * 10000)),
		CubelessNoDouble:  int32(math.Round(analysis.CubelessEquity * 10000)),
		CubelessDouble:    0, // GnuBG doesn't provide this separately
		CubefulNoDouble:   int32(math.Round(analysis.CubefulNoDouble * 10000)),
		CubefulDoubleTake: int32(math.Round(analysis.CubefulDoubleTake * 10000)),
		CubefulDoublePass: int32(math.Round(analysis.CubefulDoublePass * 10000)),
	}

	// Determine best action
	switch analysis.BestAction {
	case "No double":
		cda.BestAction = CubeActionNoDouble
	case "Double, take":
		cda.BestAction = CubeActionDoubleTake
	case "Double, pass":
		cda.BestAction = CubeActionDoublePass
	default:
		// Determine from equities
		noDouble := analysis.CubefulNoDouble
		doubleTake := analysis.CubefulDoubleTake
		doublePass := analysis.CubefulDoublePass

		if noDouble >= doubleTake && noDouble >= doublePass {
			cda.BestAction = CubeActionNoDouble
		} else if doublePass > doubleTake {
			cda.BestAction = CubeActionDoublePass
		} else {
			cda.BestAction = CubeActionDoubleTake
		}
	}

	return cda
}

// ParseSGFFile parses a GNU Backgammon SGF file and returns a GBF Match.
func ParseSGFFile(filename string) (*Match, error) {
	gnuMatch, err := gnubgparser.ParseSGFFile(filename)
	if err != nil {
		return nil, fmt.Errorf("parsing SGF file: %w", err)
	}
	return ConvertGnuBGMatch(gnuMatch, true)
}

// ParseSGF parses a GNU Backgammon SGF format from a reader and returns a GBF Match.
func ParseSGF(r io.Reader) (*Match, error) {
	gnuMatch, err := gnubgparser.ParseSGF(r)
	if err != nil {
		return nil, fmt.Errorf("parsing SGF: %w", err)
	}
	return ConvertGnuBGMatch(gnuMatch, true)
}

// ParseMATFile parses a GNU Backgammon MAT file and returns a GBF Match.
func ParseMATFile(filename string) (*Match, error) {
	gnuMatch, err := gnubgparser.ParseMATFile(filename)
	if err != nil {
		return nil, fmt.Errorf("parsing MAT file: %w", err)
	}
	return ConvertGnuBGMatch(gnuMatch, false)
}

// ParseMAT parses a GNU Backgammon MAT format from a reader and returns a GBF Match.
func ParseMAT(r io.Reader) (*Match, error) {
	gnuMatch, err := gnubgparser.ParseMAT(r)
	if err != nil {
		return nil, fmt.Errorf("parsing MAT: %w", err)
	}
	return ConvertGnuBGMatch(gnuMatch, false)
}
