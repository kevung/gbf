package gbf

import (
	"fmt"
	"io"
	"math"
	"sort"
	"strings"

	"github.com/kevung/bgfparser"
)

// ConvertBGFMatch converts a bgfparser.Match into a gbf.Match.
func ConvertBGFMatch(bgfMatch *bgfparser.Match) (*Match, error) {
	if bgfMatch == nil {
		return nil, fmt.Errorf("nil BGF match")
	}

	m := &Match{
		Metadata: MatchMetadata{
			EngineName: "BGBlitz",
		},
	}

	// Extract metadata from match Data map
	if bgfMatch.Data != nil {
		if p1, ok := bgfMatch.Data["player1"].(string); ok {
			m.Metadata.Player1Name = p1
		}
		if p2, ok := bgfMatch.Data["player2"].(string); ok {
			m.Metadata.Player2Name = p2
		}
		if ml, ok := bgfMatch.Data["matchLength"]; ok {
			m.Metadata.MatchLength = bgfToInt(ml)
		}
		if ev, ok := bgfMatch.Data["event"].(string); ok {
			m.Metadata.Event = ev
		}
		if loc, ok := bgfMatch.Data["location"].(string); ok {
			m.Metadata.Location = loc
		}
		if dt, ok := bgfMatch.Data["date"].(string); ok {
			m.Metadata.Date = dt
		}
	}

	// Process games from match data
	gamesData, ok := bgfMatch.Data["games"].([]interface{})
	if !ok {
		return m, nil
	}

	for gi, gd := range gamesData {
		gameData, ok := gd.(map[string]interface{})
		if !ok {
			continue
		}

		game, err := convertBGFGame(gameData, m.Metadata.MatchLength, gi+1)
		if err != nil {
			continue
		}
		m.Games = append(m.Games, *game)
	}

	return m, nil
}

func convertBGFGame(gameData map[string]interface{}, matchLen int, gameNumber int) (*Game, error) {
	game := &Game{
		GameNumber: gameNumber,
	}

	// Extract initial scores
	if sg := bgfToInt(gameData["scoreGreen"]); sg >= 0 {
		game.InitialScore[0] = sg
	}
	if sr := bgfToInt(gameData["scoreRed"]); sr >= 0 {
		game.InitialScore[1] = sr
	}

	// Initialize board state
	boardState := initBGFBoard()

	// Extract cube state
	cubeValue := 1
	cubeOwner := -1 // center
	isCrawford := false

	if cv, ok := gameData["cube"]; ok {
		cubeValue = bgfToInt(cv)
		if cubeValue <= 0 {
			cubeValue = 1
		}
	}
	if co, ok := gameData["cubeOwner"]; ok {
		cubeOwner = bgfToInt(co)
	}
	if cw, ok := gameData["crawford"]; ok {
		if cwBool, ok2 := cw.(bool); ok2 {
			isCrawford = cwBool
		}
	}

	// Process moves
	movesData, ok := gameData["moves"].([]interface{})
	if !ok {
		return game, nil
	}

	moveNumber := 0
	for i, md := range movesData {
		moveData, ok := md.(map[string]interface{})
		if !ok {
			continue
		}

		moveType := ""
		if mt, ok := moveData["type"].(string); ok {
			moveType = mt
		}

		switch moveType {
		case "amove":
			// Check for cube-disguised-as-amove (BGBlitz pattern)
			fromArr := bgfGetIntArray(moveData, "from")
			if len(fromArr) > 0 && fromArr[0] == -1 && bgfHasEquityCubeDecision(moveData) {
				// This is a cube action encoded as amove
				mv := convertBGFCubeMove(moveData, gameData, matchLen, boardState, cubeValue, cubeOwner, isCrawford, "")
				if mv != nil {
					moveNumber++
					game.Moves = append(game.Moves, *mv)
				}
				continue
			}

			mv := convertBGFCheckerMove(moveData, gameData, matchLen, boardState, cubeValue, cubeOwner, isCrawford)
			if mv != nil {
				moveNumber++
				game.Moves = append(game.Moves, *mv)
			}

			// Update board state
			bgfApplyCheckerMove(&boardState, moveData, bgfGetPlayer(moveData))

		case "adouble":
			// Look ahead for take/pass response
			cubeAction := "Double"
			for j := i + 1; j < len(movesData); j++ {
				nextMove, ok := movesData[j].(map[string]interface{})
				if !ok {
					continue
				}
				nextType, _ := nextMove["type"].(string)
				if nextType == "atake" {
					cubeAction = "Double/Take"
					break
				} else if nextType == "apass" {
					cubeAction = "Double/Pass"
					break
				}
			}

			mv := convertBGFCubeMove(moveData, gameData, matchLen, boardState, cubeValue, cubeOwner, isCrawford, cubeAction)
			if mv != nil {
				moveNumber++
				game.Moves = append(game.Moves, *mv)
			}

			// Update cube state after double
			if cubeAction == "Double/Take" {
				cubeValue *= 2
				player := bgfGetPlayer(moveData)
				if player == -1 {
					cubeOwner = 1 // Red now owns
				} else {
					cubeOwner = -1 // Green now owns... wait, this needs to be opponent
					cubeOwner = 0  // adjusted: center→ opponent actually
				}
			}

		case "atake":
			// Handled by adouble look-ahead
			continue

		case "apass":
			// Game ends
			continue
		}
	}

	return game, nil
}

func convertBGFCheckerMove(moveData map[string]interface{}, gameData map[string]interface{}, matchLen int, boardState [28]int, cubeValue int, cubeOwner int, isCrawford bool) *Move {
	player := bgfGetPlayer(moveData)

	mv := &Move{
		MoveType: MoveTypeChecker,
		Player:   bgfPlayerToGBF(player),
	}

	// Get dice
	dice := bgfGetDice(moveData, player)
	mv.Dice = dice

	// Get move string
	mv.MoveString = bgfConvertMoveToString(moveData)

	// Convert position
	pos := convertBGFPosition(boardState, gameData, matchLen, cubeValue, cubeOwner, isCrawford)
	pos.SideToMove = mv.Player
	pos.Dice = mv.Dice
	mv.Position = pos

	// Convert checker analysis
	analysisData := bgfGetAnalysis(moveData)
	if len(analysisData) > 0 {
		mv.CheckerAnalysis = convertBGFCheckerAnalysis(analysisData)
	}

	// Convert cube analysis from equity.cubeDecision
	cubeDecData := bgfGetCubeDecision(moveData)
	if cubeDecData != nil {
		mv.CubeAnalysis = convertBGFCubeDecision(cubeDecData)
	}

	return mv
}

func convertBGFCubeMove(moveData map[string]interface{}, gameData map[string]interface{}, matchLen int, boardState [28]int, cubeValue int, cubeOwner int, isCrawford bool, cubeAction string) *Move {
	player := bgfGetPlayer(moveData)

	mv := &Move{
		MoveType:   MoveTypeCube,
		Player:     bgfPlayerToGBF(player),
		Dice:       [2]int{0, 0},
		CubeAction: cubeAction,
	}

	pos := convertBGFPosition(boardState, gameData, matchLen, cubeValue, cubeOwner, isCrawford)
	pos.SideToMove = mv.Player
	pos.Dice = [2]int{0, 0}
	mv.Position = pos

	cubeDecData := bgfGetCubeDecision(moveData)
	if cubeDecData != nil {
		mv.CubeAnalysis = convertBGFCubeDecision(cubeDecData)
	}

	return mv
}

// convertBGFPosition converts a BGF board state into a GBF PositionState.
// BGF board encoding:
//
//	[0-23]: board points (0=Green's 24-point → 23=Green's 1-point)
//	[24]: Green's bar, [25]: Red's bar
//	[26]: Green's borne off, [27]: Red's borne off
//	Positive = Green (Player X), Negative = Red (Player O)
//
// GBF encoding:
//
//	Board[0-23]: points (0 = 1-point, 23 = 24-point from X's perspective)
//	Positive = Player X, Negative = Player O
func convertBGFPosition(boardState [28]int, gameData map[string]interface{}, matchLen int, cubeValue int, cubeOwner int, isCrawford bool) *PositionState {
	pos := &PositionState{
		CubeValue: cubeValue,
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	// Cube owner: BGF uses -1=Green(P1), 0=center, 1=Red(P2) ... actually from blunderDB:
	// cubeOwner is already absolute: -1=center, 0=Player1, 1=Player2
	// Map to GBF: 0=center, 1=X, 2=O
	switch cubeOwner {
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
	scoreGreen := bgfToInt(gameData["scoreGreen"])
	scoreRed := bgfToInt(gameData["scoreRed"])

	if matchLen > 0 {
		pos.AwayX = matchLen - scoreGreen
		pos.AwayO = matchLen - scoreRed
		pos.MatchLength = matchLen
	}

	pos.Crawford = isCrawford

	// Convert board: BGF index i → GBF point (23-i)
	// BGF[0] = Green's 24-point → GBF point 23
	// BGF[23] = Green's 1-point → GBF point 0
	for i := 0; i < 24; i++ {
		count := boardState[i]
		gbfPt := 23 - i
		if count > 0 {
			pos.Board[gbfPt] = count // Positive = Player X (Green)
		} else if count < 0 {
			pos.Board[gbfPt] = count // Negative = Player O (Red)
		}
	}

	// Bar: BGF[24] = Green's bar → BarX, BGF[25] = Red's bar → BarO
	pos.BarX = boardState[24]
	if boardState[25] < 0 {
		pos.BarO = -boardState[25]
	} else {
		pos.BarO = boardState[25]
	}

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

// ConvertBGFTextPosition converts a bgfparser.Position (from TXT format) into a GBF PositionState.
func ConvertBGFTextPosition(bgfPos *bgfparser.Position) (*PositionState, error) {
	if bgfPos == nil {
		return nil, fmt.Errorf("nil BGF text position")
	}

	pos := &PositionState{
		CubeValue: bgfPos.CubeValue,
	}

	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	// Map points 1-24 from bgfparser
	// bgfparser Board[1-24]: points 1-24, positive=X/Green, negative=O/Red
	// GBF Board[0-23]: 0=1-point, so Board[i-1] = bgfParser.Board[i]
	for i := 1; i <= 24; i++ {
		count := bgfPos.Board[i]
		if count != 0 {
			pos.Board[i-1] = count // sign preserved: positive=X, negative=O
		}
	}

	// Map bars
	if bgfPos.OnBar != nil {
		if xBar, ok := bgfPos.OnBar["X"]; ok {
			pos.BarX = xBar
		}
		if oBar, ok := bgfPos.OnBar["O"]; ok {
			pos.BarO = oBar
		}
	}

	// Side to move
	if bgfPos.OnRoll == "O" {
		pos.SideToMove = PlayerO
	} else {
		pos.SideToMove = PlayerX
	}

	// Dice
	pos.Dice = [2]int{bgfPos.Dice[0], bgfPos.Dice[1]}

	// Cube owner
	switch bgfPos.CubeOwner {
	case "X":
		pos.CubeOwner = CubeX
	case "O":
		pos.CubeOwner = CubeO
	default:
		pos.CubeOwner = CubeCenter
	}

	// Scores
	if bgfPos.MatchLength > 0 {
		pos.AwayX = bgfPos.MatchLength - bgfPos.ScoreX
		pos.AwayO = bgfPos.MatchLength - bgfPos.ScoreO
		pos.MatchLength = bgfPos.MatchLength
	}

	pos.Player1Name = bgfPos.PlayerX
	pos.Player2Name = bgfPos.PlayerO
	pos.XGID = bgfPos.XGID

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

	// Convert analysis
	pos.Crawford = bgfPos.Crawford

	return pos, nil
}

// ConvertBGFTextAnalysis extracts analysis from a bgfparser.Position.
func ConvertBGFTextAnalysis(bgfPos *bgfparser.Position) (*CheckerPlayAnalysis, *CubeDecisionAnalysis) {
	var cpa *CheckerPlayAnalysis
	var cda *CubeDecisionAnalysis

	if len(bgfPos.Evaluations) > 0 {
		cpa = &CheckerPlayAnalysis{
			MoveCount: uint8(len(bgfPos.Evaluations)),
		}
		for _, eval := range bgfPos.Evaluations {
			ma := CheckerMoveAnalysis{
				Equity:            int32(math.Round(eval.Equity * 10000)),
				WinRate:           uint16(math.Round(eval.Win * 100)), // already percentage → scale to 10000
				GammonRate:        uint16(math.Round(eval.WinG * 100)),
				BackgammonRate:    uint16(math.Round(eval.WinBG * 100)),
				OppWinRate:        uint16(math.Round((100 - eval.Win) * 100)),
				OppGammonRate:     uint16(math.Round(eval.LoseG * 100)),
				OppBackgammonRate: uint16(math.Round(eval.LoseBG * 100)),
				EquityDiff:        int16(math.Round(eval.Diff * 10000)),
			}
			// Move encoding from string (we leave submoves empty for text format)
			for j := 0; j < 4; j++ {
				ma.Move.Submoves[j] = [2]uint8{MoveUnused, MoveUnused}
			}
			cpa.Moves = append(cpa.Moves, ma)
		}
	}

	if len(bgfPos.CubeDecisions) > 0 {
		// Extract cube analysis from best cube decision
		cda = convertBGFTextCubeAnalysis(bgfPos)
	}

	return cpa, cda
}

func convertBGFTextCubeAnalysis(bgfPos *bgfparser.Position) *CubeDecisionAnalysis {
	cda := &CubeDecisionAnalysis{}

	// Find best/worst actions
	for _, cd := range bgfPos.CubeDecisions {
		if cd.IsBest {
			switch {
			case strings.Contains(strings.ToLower(cd.Action), "no double"):
				cda.BestAction = CubeActionNoDouble
			case strings.Contains(strings.ToLower(cd.Action), "pass"):
				cda.BestAction = CubeActionDoublePass
			default:
				cda.BestAction = CubeActionDoubleTake
			}
		}
	}

	// Store cubeful equities from cube decisions
	for _, cd := range bgfPos.CubeDecisions {
		action := strings.ToLower(cd.Action)
		equity := int32(math.Round(cd.EMG * 10000))

		switch {
		case strings.Contains(action, "no double") || strings.Contains(action, "no redouble"):
			cda.CubefulNoDouble = equity
		case strings.Contains(action, "pass"):
			cda.CubefulDoublePass = equity
		case strings.Contains(action, "take") || strings.Contains(action, "beaver"):
			cda.CubefulDoubleTake = equity
		}
	}

	return cda
}

// Helper functions for BGF data extraction

func initBGFBoard() [28]int {
	var board [28]int
	// Standard starting position from Green's perspective
	// BGF index 0 = Green's 24-point → 2 checkers (positive=Green)
	// BGF index 5 = Green's 19-point → nothing... actually:
	// Green's perspective: index 0=24pt, index 23=1pt
	board[0] = 2   // Green's 24-point: 2 Green checkers
	board[5] = -5  // Green's 19-point: 5 Red checkers
	board[7] = -3  // Green's 17-point: 3 Red checkers
	board[11] = 5  // Green's 13-point: 5 Green checkers
	board[12] = -5 // Green's 12-point: 5 Red checkers (= Red's 13-point)
	board[16] = 3  // Green's 8-point: 3 Green checkers
	board[18] = 5  // Green's 6-point: 5 Green checkers
	board[23] = -2 // Green's 1-point: 2 Red checkers (= Red's 24-point)
	return board
}

func bgfGetPlayer(moveData map[string]interface{}) int {
	if p, ok := moveData["player"]; ok {
		return bgfToInt(p)
	}
	return -1
}

func bgfPlayerToGBF(bgfPlayer int) int {
	// BGF: -1=Green=Player1=X, 1=Red=Player2=O
	if bgfPlayer == -1 {
		return PlayerX
	}
	return PlayerO
}

func bgfGetDice(moveData map[string]interface{}, player int) [2]int {
	var dice [2]int
	if player == -1 {
		if g, ok := moveData["green"]; ok {
			arr := bgfToIntArray(g)
			if len(arr) >= 2 {
				dice = [2]int{arr[0], arr[1]}
			}
		}
	} else {
		if r, ok := moveData["red"]; ok {
			arr := bgfToIntArray(r)
			if len(arr) >= 2 {
				dice = [2]int{arr[0], arr[1]}
			}
		}
	}
	return dice
}

func bgfConvertMoveToString(moveData map[string]interface{}) string {
	fromArr := bgfGetIntArray(moveData, "from")
	toArr := bgfGetIntArray(moveData, "to")

	if len(fromArr) == 0 || fromArr[0] == -1 {
		return "Cannot Move"
	}

	type submove struct {
		from int
		to   int
	}

	var moves []submove
	for i := 0; i < len(fromArr) && i < len(toArr) && i < 4; i++ {
		if fromArr[i] == -1 {
			break
		}
		moves = append(moves, submove{fromArr[i], toArr[i]})
	}

	if len(moves) == 0 {
		return "Cannot Move"
	}

	sort.Slice(moves, func(i, j int) bool {
		return moves[i].from > moves[j].from
	})

	var parts []string
	for i := 0; i < len(moves); {
		count := 1
		for i+count < len(moves) && moves[i+count].from == moves[i].from && moves[i+count].to == moves[i].to {
			count++
		}

		fromStr := fmt.Sprintf("%d", moves[i].from)
		if moves[i].from == 25 {
			fromStr = "bar"
		}
		toStr := fmt.Sprintf("%d", moves[i].to)
		if moves[i].to == 0 {
			toStr = "off"
		}

		if count > 1 {
			parts = append(parts, fmt.Sprintf("%s/%s(%d)", fromStr, toStr, count))
		} else {
			parts = append(parts, fmt.Sprintf("%s/%s", fromStr, toStr))
		}
		i += count
	}

	return strings.Join(parts, " ")
}

func bgfApplyCheckerMove(boardState *[28]int, moveData map[string]interface{}, player int) {
	fromArr := bgfGetIntArray(moveData, "from")
	toArr := bgfGetIntArray(moveData, "to")

	for i := 0; i < len(fromArr) && i < len(toArr) && i < 4; i++ {
		from := fromArr[i]
		to := toArr[i]
		if from == -1 {
			break
		}

		if player == -1 {
			// Green (positive)
			var fromIdx int
			if from == 25 {
				fromIdx = 24
			} else {
				fromIdx = 24 - from
			}
			boardState[fromIdx]--

			if to == 0 {
				boardState[26]++
			} else {
				toIdx := 24 - to
				if boardState[toIdx] < 0 {
					boardState[25] += boardState[toIdx]
					boardState[toIdx] = 0
				}
				boardState[toIdx]++
			}
		} else {
			// Red (negative)
			var fromIdx int
			if from == 25 {
				fromIdx = 25
			} else {
				fromIdx = from - 1
			}
			boardState[fromIdx]++

			if to == 0 {
				boardState[27]--
			} else {
				toIdx := to - 1
				if boardState[toIdx] > 0 {
					boardState[24] += boardState[toIdx]
					boardState[toIdx] = 0
				}
				boardState[toIdx]--
			}
		}
	}
}

func bgfGetIntArray(moveData map[string]interface{}, key string) []int {
	val, ok := moveData[key]
	if !ok {
		return nil
	}
	return bgfToIntArray(val)
}

func bgfToIntArray(val interface{}) []int {
	switch v := val.(type) {
	case []interface{}:
		result := make([]int, len(v))
		for i, item := range v {
			result[i] = bgfToInt(item)
		}
		return result
	case []int:
		return v
	case []float64:
		result := make([]int, len(v))
		for i, f := range v {
			result[i] = int(f)
		}
		return result
	default:
		return nil
	}
}

func bgfToInt(val interface{}) int {
	switch v := val.(type) {
	case int:
		return v
	case int32:
		return int(v)
	case int64:
		return int(v)
	case float64:
		return int(v)
	case float32:
		return int(v)
	default:
		return 0
	}
}

func bgfHasEquityCubeDecision(moveData map[string]interface{}) bool {
	equity, ok := moveData["equity"]
	if !ok {
		return false
	}
	eqMap, ok := equity.(map[string]interface{})
	if !ok {
		return false
	}
	_, ok = eqMap["cubeDecision"]
	return ok
}

func bgfGetAnalysis(moveData map[string]interface{}) []interface{} {
	equity, ok := moveData["equity"]
	if !ok {
		return nil
	}
	eqMap, ok := equity.(map[string]interface{})
	if !ok {
		return nil
	}
	analysis, ok := eqMap["moveAnalysis"]
	if !ok {
		return nil
	}
	arr, ok := analysis.([]interface{})
	if !ok {
		return nil
	}
	return arr
}

func bgfGetCubeDecision(moveData map[string]interface{}) map[string]interface{} {
	equity, ok := moveData["equity"]
	if !ok {
		return nil
	}
	eqMap, ok := equity.(map[string]interface{})
	if !ok {
		return nil
	}
	cd, ok := eqMap["cubeDecision"]
	if !ok {
		return nil
	}
	cdMap, ok := cd.(map[string]interface{})
	if !ok {
		return nil
	}
	return cdMap
}

func convertBGFCheckerAnalysis(analysisData []interface{}) *CheckerPlayAnalysis {
	cpa := &CheckerPlayAnalysis{
		MoveCount: uint8(len(analysisData)),
	}

	for _, item := range analysisData {
		itemMap, ok := item.(map[string]interface{})
		if !ok {
			continue
		}

		ma := CheckerMoveAnalysis{}

		if eq, ok := itemMap["equity"]; ok {
			ma.Equity = int32(math.Round(bgfToFloat(eq) * 10000))
		}
		if d, ok := itemMap["diff"]; ok {
			ma.EquityDiff = int16(math.Round(bgfToFloat(d) * 10000))
		}
		if w, ok := itemMap["win"]; ok {
			ma.WinRate = uint16(math.Round(bgfToFloat(w) * 100))
		}
		if wg, ok := itemMap["winG"]; ok {
			ma.GammonRate = uint16(math.Round(bgfToFloat(wg) * 100))
		}
		if wbg, ok := itemMap["winBG"]; ok {
			ma.BackgammonRate = uint16(math.Round(bgfToFloat(wbg) * 100))
		}
		if lw, ok := itemMap["loseW"]; ok {
			_ = lw
			// OppWinRate = 100% - WinRate
		}
		ma.OppWinRate = 10000 - ma.WinRate
		if lg, ok := itemMap["loseG"]; ok {
			ma.OppGammonRate = uint16(math.Round(bgfToFloat(lg) * 100))
		}
		if lbg, ok := itemMap["loseBG"]; ok {
			ma.OppBackgammonRate = uint16(math.Round(bgfToFloat(lbg) * 100))
		}

		for j := 0; j < 4; j++ {
			ma.Move.Submoves[j] = [2]uint8{MoveUnused, MoveUnused}
		}

		cpa.Moves = append(cpa.Moves, ma)
	}

	return cpa
}

func convertBGFCubeDecision(cdMap map[string]interface{}) *CubeDecisionAnalysis {
	cda := &CubeDecisionAnalysis{}

	if w, ok := cdMap["win"]; ok {
		cda.WinRate = uint16(math.Round(bgfToFloat(w) * 100))
	}
	if wg, ok := cdMap["winG"]; ok {
		cda.GammonRate = uint16(math.Round(bgfToFloat(wg) * 100))
	}
	if wbg, ok := cdMap["winBG"]; ok {
		cda.BackgammonRate = uint16(math.Round(bgfToFloat(wbg) * 100))
	}
	cda.OppWinRate = 10000 - cda.WinRate
	if lg, ok := cdMap["loseG"]; ok {
		cda.OppGammonRate = uint16(math.Round(bgfToFloat(lg) * 100))
	}
	if lbg, ok := cdMap["loseBG"]; ok {
		cda.OppBackgammonRate = uint16(math.Round(bgfToFloat(lbg) * 100))
	}

	if nd, ok := cdMap["noDouble"]; ok {
		cda.CubefulNoDouble = int32(math.Round(bgfToFloat(nd) * 10000))
	}
	if dt, ok := cdMap["doubleTake"]; ok {
		cda.CubefulDoubleTake = int32(math.Round(bgfToFloat(dt) * 10000))
	}
	if dp, ok := cdMap["doublePass"]; ok {
		cda.CubefulDoublePass = int32(math.Round(bgfToFloat(dp) * 10000))
	}

	// Determine best action
	if ba, ok := cdMap["bestAction"]; ok {
		baStr, _ := ba.(string)
		switch strings.ToLower(baStr) {
		case "no double", "no redouble":
			cda.BestAction = CubeActionNoDouble
		case "double/pass", "redouble/pass":
			cda.BestAction = CubeActionDoublePass
		default:
			cda.BestAction = CubeActionDoubleTake
		}
	}

	return cda
}

func bgfToFloat(val interface{}) float64 {
	switch v := val.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	default:
		return 0
	}
}

// ParseBGFFile parses a BGBlitz BGF binary file and returns a GBF Match.
func ParseBGFFile(filename string) (*Match, error) {
	bgfMatch, err := bgfparser.ParseBGF(filename)
	if err != nil {
		return nil, fmt.Errorf("parsing BGF file: %w", err)
	}
	return ConvertBGFMatch(bgfMatch)
}

// ParseBGFTextFile parses a BGBlitz text export file and returns a GBF PositionState.
func ParseBGFTextFile(filename string) (*PositionState, *CheckerPlayAnalysis, *CubeDecisionAnalysis, error) {
	bgfPos, err := bgfparser.ParseTXT(filename)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("parsing BGF text file: %w", err)
	}
	pos, err := ConvertBGFTextPosition(bgfPos)
	if err != nil {
		return nil, nil, nil, err
	}
	cpa, cda := ConvertBGFTextAnalysis(bgfPos)
	return pos, cpa, cda, nil
}

// ParseBGFTextReader parses a BGBlitz text export from a reader.
func ParseBGFTextReader(r io.Reader) (*PositionState, *CheckerPlayAnalysis, *CubeDecisionAnalysis, error) {
	bgfPos, err := bgfparser.ParseTXTFromReader(r)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("parsing BGF text: %w", err)
	}
	pos, err := ConvertBGFTextPosition(bgfPos)
	if err != nil {
		return nil, nil, nil, err
	}
	cpa, cda := ConvertBGFTextAnalysis(bgfPos)
	return pos, cpa, cda, nil
}
