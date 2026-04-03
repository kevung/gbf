package convert

import (
	"fmt"
	"math"
	"strings"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/bgfparser"
)

// ParseBGFFile parses a BGBlitz BGF binary file and returns a GBF Match.
func ParseBGFFile(path string) (*gbf.Match, error) {
	bgfMatch, err := bgfparser.ParseBGF(path)
	if err != nil {
		return nil, fmt.Errorf("parsing BGF file: %w", err)
	}
	return convertBGFMatch(bgfMatch)
}

func convertBGFMatch(bgfMatch *bgfparser.Match) (*gbf.Match, error) {
	if bgfMatch == nil {
		return nil, fmt.Errorf("nil BGF match")
	}

	m := &gbf.Match{
		Metadata: gbf.MatchMetadata{
			EngineName: "BGBlitz",
		},
	}

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
		if dt, ok := bgfMatch.Data["date"].(string); ok {
			m.Metadata.Date = dt
		}
	}

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

func convertBGFGame(gameData map[string]interface{}, matchLen int, gameNumber int) (*gbf.Game, error) {
	game := &gbf.Game{
		GameNumber: gameNumber,
	}

	if sg := bgfToInt(gameData["scoreGreen"]); sg >= 0 {
		game.InitialScore[0] = sg
	}
	if sr := bgfToInt(gameData["scoreRed"]); sr >= 0 {
		game.InitialScore[1] = sr
	}

	boardState := initBGFBoard()
	cubeValue := 1
	cubeOwner := -1
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

	movesData, ok := gameData["moves"].([]interface{})
	if !ok {
		return game, nil
	}

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
			fromArr := bgfGetIntArray(moveData, "from")
			if len(fromArr) > 0 && fromArr[0] == -1 && bgfHasEquityCubeDecision(moveData) {
				mv := convertBGFCubeMove(moveData, gameData, matchLen, boardState, cubeValue, cubeOwner, isCrawford, "")
				if mv != nil {
					game.Moves = append(game.Moves, *mv)
				}
				continue
			}
			mv := convertBGFCheckerMove(moveData, gameData, matchLen, boardState, cubeValue, cubeOwner, isCrawford)
			if mv != nil {
				game.Moves = append(game.Moves, *mv)
			}
			bgfApplyCheckerMove(&boardState, moveData, bgfGetPlayer(moveData))

		case "adouble":
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
				game.Moves = append(game.Moves, *mv)
			}
			if cubeAction == "Double/Take" {
				cubeValue *= 2
			}

		case "atake", "apass":
			continue
		}
	}

	return game, nil
}

func convertBGFCheckerMove(moveData, gameData map[string]interface{}, matchLen int, boardState [28]int, cubeValue, cubeOwner int, isCrawford bool) *gbf.Move {
	player := bgfGetPlayer(moveData)

	mv := &gbf.Move{
		MoveType: gbf.MoveTypeChecker,
		Player:   bgfPlayerToGBF(player),
	}

	mv.Dice = bgfGetDice(moveData, player)
	mv.MoveString = bgfConvertMoveToString(moveData)

	pos := convertBGFPosition(boardState, gameData, matchLen, cubeValue, cubeOwner, isCrawford)
	pos.SideToMove = mv.Player
	pos.Dice = mv.Dice
	mv.Position = pos

	if analysisData := bgfGetAnalysis(moveData); len(analysisData) > 0 {
		mv.CheckerAnalysis = convertBGFCheckerAnalysis(analysisData)
	}
	if cubeDecData := bgfGetCubeDecision(moveData); cubeDecData != nil {
		mv.CubeAnalysis = convertBGFCubeDecision(cubeDecData)
	}

	return mv
}

func convertBGFCubeMove(moveData, gameData map[string]interface{}, matchLen int, boardState [28]int, cubeValue, cubeOwner int, isCrawford bool, cubeAction string) *gbf.Move {
	player := bgfGetPlayer(moveData)

	mv := &gbf.Move{
		MoveType:   gbf.MoveTypeCube,
		Player:     bgfPlayerToGBF(player),
		Dice:       [2]int{0, 0},
		CubeAction: cubeAction,
	}

	pos := convertBGFPosition(boardState, gameData, matchLen, cubeValue, cubeOwner, isCrawford)
	pos.SideToMove = mv.Player
	mv.Position = pos

	if cubeDecData := bgfGetCubeDecision(moveData); cubeDecData != nil {
		mv.CubeAnalysis = convertBGFCubeDecision(cubeDecData)
	}

	return mv
}

// convertBGFPosition converts a BGF board state into a GBF PositionState.
// BGF board encoding:
//
//	[0-23]: board points (0=Green's 24-point → 23=Green's 1-point)
//	[24]: Green's bar, [25]: Red's bar
//	Positive = Green (Player X), Negative = Red (Player O)
//
// GBF encoding:
//
//	Board[0-23]: points (0 = 1-point, 23 = 24-point from X's perspective)
func convertBGFPosition(boardState [28]int, gameData map[string]interface{}, matchLen, cubeValue, cubeOwner int, isCrawford bool) *gbf.PositionState {
	pos := &gbf.PositionState{
		CubeValue: cubeValue,
	}
	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	switch cubeOwner {
	case -1:
		pos.CubeOwner = gbf.CubeCenter
	case 0:
		pos.CubeOwner = gbf.CubeX
	case 1:
		pos.CubeOwner = gbf.CubeO
	default:
		pos.CubeOwner = gbf.CubeCenter
	}

	scoreGreen := bgfToInt(gameData["scoreGreen"])
	scoreRed := bgfToInt(gameData["scoreRed"])
	if matchLen > 0 {
		pos.AwayX = matchLen - scoreGreen
		pos.AwayO = matchLen - scoreRed
		pos.MatchLength = matchLen
	}

	pos.Crawford = isCrawford

	// BGF[i] → GBF point (23-i)
	// BGF[0] = Green's 24-point → GBF point 23
	// BGF[23] = Green's 1-point → GBF point 0
	for i := 0; i < 24; i++ {
		count := boardState[i]
		gbfPt := 23 - i
		pos.Board[gbfPt] = count
	}

	pos.BarX = boardState[24]
	if boardState[25] < 0 {
		pos.BarO = -boardState[25]
	} else {
		pos.BarO = boardState[25]
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
	pos.BorneOffX = gbf.MaxCheckers - totalX
	pos.BorneOffO = gbf.MaxCheckers - totalO

	return pos
}

func initBGFBoard() [28]int {
	var board [28]int
	board[0] = 2   // Green's 24-point: 2 Green checkers
	board[5] = -5  // Green's 19-point: 5 Red checkers
	board[7] = -3  // Green's 17-point: 3 Red checkers
	board[11] = 5  // Green's 13-point: 5 Green checkers
	board[12] = -5 // Green's 12-point: 5 Red checkers
	board[16] = 3  // Green's 8-point: 3 Green checkers
	board[18] = 5  // Green's 6-point: 5 Green checkers
	board[23] = -2 // Green's 1-point: 2 Red checkers
	return board
}

func bgfGetPlayer(moveData map[string]interface{}) int {
	if p, ok := moveData["player"]; ok {
		return bgfToInt(p)
	}
	return -1
}

func bgfPlayerToGBF(bgfPlayer int) int {
	if bgfPlayer == -1 {
		return gbf.PlayerX
	}
	return gbf.PlayerO
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

	// Sort by from descending
	for i := 1; i < len(moves); i++ {
		for j := i; j > 0 && moves[j-1].from < moves[j].from; j-- {
			moves[j-1], moves[j] = moves[j], moves[j-1]
		}
	}

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
			fromIdx := 24 - from
			if from == 25 {
				fromIdx = 24
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
			fromIdx := from - 1
			if from == 25 {
				fromIdx = 25
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
	arr, _ := analysis.([]interface{})
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
	cdMap, _ := cd.(map[string]interface{})
	return cdMap
}

func convertBGFCheckerAnalysis(analysisData []interface{}) *gbf.CheckerPlayAnalysis {
	cpa := &gbf.CheckerPlayAnalysis{
		MoveCount: uint8(len(analysisData)),
	}

	for _, item := range analysisData {
		itemMap, ok := item.(map[string]interface{})
		if !ok {
			continue
		}

		ma := gbf.CheckerMoveAnalysis{}

		if eq, ok := itemMap["equity"]; ok {
			ma.Equity = roundToInt32(bgfToFloat(eq) * 10000)
		}
		if d, ok := itemMap["diff"]; ok {
			ma.EquityDiff = int16(math.Round(bgfToFloat(d) * 10000))
		}
		if w, ok := itemMap["win"]; ok {
			ma.WinRate = roundToUint16(bgfToFloat(w) * 100)
		}
		if wg, ok := itemMap["winG"]; ok {
			ma.GammonRate = roundToUint16(bgfToFloat(wg) * 100)
		}
		if wbg, ok := itemMap["winBG"]; ok {
			ma.BackgammonRate = roundToUint16(bgfToFloat(wbg) * 100)
		}
		ma.OppWinRate = 10000 - ma.WinRate
		if lg, ok := itemMap["loseG"]; ok {
			ma.OppGammonRate = roundToUint16(bgfToFloat(lg) * 100)
		}
		if lbg, ok := itemMap["loseBG"]; ok {
			ma.OppBackgammonRate = roundToUint16(bgfToFloat(lbg) * 100)
		}

		for j := 0; j < 4; j++ {
			ma.Move.Submoves[j] = [2]uint8{gbf.MoveUnused, gbf.MoveUnused}
		}

		cpa.Moves = append(cpa.Moves, ma)
	}

	return cpa
}

func convertBGFCubeDecision(cdMap map[string]interface{}) *gbf.CubeDecisionAnalysis {
	cda := &gbf.CubeDecisionAnalysis{}

	if w, ok := cdMap["win"]; ok {
		cda.WinRate = roundToUint16(bgfToFloat(w) * 100)
	}
	if wg, ok := cdMap["winG"]; ok {
		cda.GammonRate = roundToUint16(bgfToFloat(wg) * 100)
	}
	if wbg, ok := cdMap["winBG"]; ok {
		cda.BackgammonRate = roundToUint16(bgfToFloat(wbg) * 100)
	}
	cda.OppWinRate = 10000 - cda.WinRate
	if lg, ok := cdMap["loseG"]; ok {
		cda.OppGammonRate = roundToUint16(bgfToFloat(lg) * 100)
	}
	if lbg, ok := cdMap["loseBG"]; ok {
		cda.OppBackgammonRate = roundToUint16(bgfToFloat(lbg) * 100)
	}
	if nd, ok := cdMap["noDouble"]; ok {
		cda.CubefulNoDouble = roundToInt32(bgfToFloat(nd) * 10000)
	}
	if dt, ok := cdMap["doubleTake"]; ok {
		cda.CubefulDoubleTake = roundToInt32(bgfToFloat(dt) * 10000)
	}
	if dp, ok := cdMap["doublePass"]; ok {
		cda.CubefulDoublePass = roundToInt32(bgfToFloat(dp) * 10000)
	}

	if ba, ok := cdMap["bestAction"]; ok {
		baStr, _ := ba.(string)
		switch strings.ToLower(baStr) {
		case "no double", "no redouble":
			cda.BestAction = gbf.CubeActionNoDouble
		case "double/pass", "redouble/pass":
			cda.BestAction = gbf.CubeActionDoublePass
		default:
			cda.BestAction = gbf.CubeActionDoubleTake
		}
	}

	return cda
}

// parseBGFTextFile parses a BGBlitz text export (.txt) and returns position + analyses.
func parseBGFTextFile(path string) (*gbf.PositionState, *gbf.CheckerPlayAnalysis, *gbf.CubeDecisionAnalysis, error) {
	bgfPos, err := bgfparser.ParseTXT(path)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("parsing BGF text file: %w", err)
	}
	pos, err := convertBGFTextPosition(bgfPos)
	if err != nil {
		return nil, nil, nil, err
	}
	cpa, cda := convertBGFTextAnalysis(bgfPos)
	return pos, cpa, cda, nil
}

func convertBGFTextPosition(bgfPos *bgfparser.Position) (*gbf.PositionState, error) {
	if bgfPos == nil {
		return nil, fmt.Errorf("nil BGF text position")
	}

	pos := &gbf.PositionState{
		CubeValue: bgfPos.CubeValue,
	}
	if pos.CubeValue <= 0 {
		pos.CubeValue = 1
	}

	// bgfparser Board[1-24]: points 1-24, positive=X, negative=O
	// GBF Board[0-23]: Board[i-1] = bgfParser.Board[i]
	for i := 1; i <= 24; i++ {
		pos.Board[i-1] = bgfPos.Board[i]
	}

	if bgfPos.OnBar != nil {
		if xBar, ok := bgfPos.OnBar["X"]; ok {
			pos.BarX = xBar
		}
		if oBar, ok := bgfPos.OnBar["O"]; ok {
			pos.BarO = oBar
		}
	}

	if bgfPos.OnRoll == "O" {
		pos.SideToMove = gbf.PlayerO
	} else {
		pos.SideToMove = gbf.PlayerX
	}

	pos.Dice = [2]int{bgfPos.Dice[0], bgfPos.Dice[1]}

	switch bgfPos.CubeOwner {
	case "X":
		pos.CubeOwner = gbf.CubeX
	case "O":
		pos.CubeOwner = gbf.CubeO
	default:
		pos.CubeOwner = gbf.CubeCenter
	}

	if bgfPos.MatchLength > 0 {
		pos.AwayX = bgfPos.MatchLength - bgfPos.ScoreX
		pos.AwayO = bgfPos.MatchLength - bgfPos.ScoreO
		pos.MatchLength = bgfPos.MatchLength
	}

	pos.Player1Name = bgfPos.PlayerX
	pos.Player2Name = bgfPos.PlayerO
	pos.XGID = bgfPos.XGID
	pos.Crawford = bgfPos.Crawford

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

	return pos, nil
}

func convertBGFTextAnalysis(bgfPos *bgfparser.Position) (*gbf.CheckerPlayAnalysis, *gbf.CubeDecisionAnalysis) {
	var cpa *gbf.CheckerPlayAnalysis
	var cda *gbf.CubeDecisionAnalysis

	if len(bgfPos.Evaluations) > 0 {
		cpa = &gbf.CheckerPlayAnalysis{
			MoveCount: uint8(len(bgfPos.Evaluations)),
		}
		for _, eval := range bgfPos.Evaluations {
			ma := gbf.CheckerMoveAnalysis{
				Equity:            roundToInt32(eval.Equity * 10000),
				WinRate:           roundToUint16(eval.Win * 100),
				GammonRate:        roundToUint16(eval.WinG * 100),
				BackgammonRate:    roundToUint16(eval.WinBG * 100),
				OppWinRate:        roundToUint16((100 - eval.Win) * 100),
				OppGammonRate:     roundToUint16(eval.LoseG * 100),
				OppBackgammonRate: roundToUint16(eval.LoseBG * 100),
				EquityDiff:        int16(math.Round(eval.Diff * 10000)),
			}
			for j := 0; j < 4; j++ {
				ma.Move.Submoves[j] = [2]uint8{gbf.MoveUnused, gbf.MoveUnused}
			}
			cpa.Moves = append(cpa.Moves, ma)
		}
	}

	if len(bgfPos.CubeDecisions) > 0 {
		cda = convertBGFTextCubeAnalysis(bgfPos)
	}

	return cpa, cda
}

func convertBGFTextCubeAnalysis(bgfPos *bgfparser.Position) *gbf.CubeDecisionAnalysis {
	cda := &gbf.CubeDecisionAnalysis{}

	for _, cd := range bgfPos.CubeDecisions {
		if cd.IsBest {
			action := strings.ToLower(cd.Action)
			switch {
			case strings.Contains(action, "no double") || strings.Contains(action, "no redouble"):
				cda.BestAction = gbf.CubeActionNoDouble
			case strings.Contains(action, "pass"):
				cda.BestAction = gbf.CubeActionDoublePass
			default:
				cda.BestAction = gbf.CubeActionDoubleTake
			}
		}
	}

	for _, cd := range bgfPos.CubeDecisions {
		action := strings.ToLower(cd.Action)
		equity := roundToInt32(cd.EMG * 10000)
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
