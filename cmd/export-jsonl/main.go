// cmd/export-jsonl exports .xg files to JSONL for the mining study pipeline (S0.1).
//
// Produces three append-mode output files:
//
//	matches.jsonl   — one JSON object per match
//	games.jsonl     — one JSON object per game
//	positions.jsonl — one JSON object per checker/cube decision
//
// Usage:
//
//	export-jsonl [flags] <dir>
//
// Flags:
//
//	-outdir  output directory (default: .)
//	-limit   max files to process (0=all)
//	-workers number of parallel parsers (0=NumCPU)
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
)

func main() {
	outDir := flag.String("outdir", ".", "output directory for JSONL files")
	limit := flag.Int("limit", 0, "max files to process (0=all)")
	workers := flag.Int("workers", 0, "parallel parsers (0=NumCPU)")
	flag.Parse()

	if flag.NArg() == 0 {
		fmt.Fprintln(os.Stderr, "usage: export-jsonl [flags] <dir>")
		os.Exit(1)
	}
	target := flag.Arg(0)

	if *workers == 0 {
		*workers = runtime.NumCPU()
	}

	logger := log.New(os.Stdout, "[export-jsonl] ", log.LstdFlags)

	files, err := collectXGFiles(target, *limit)
	if err != nil {
		logger.Fatalf("collect files: %v", err)
	}
	logger.Printf("found %d .xg files in %s", len(files), target)

	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		logger.Fatalf("mkdir %s: %v", *outDir, err)
	}

	mOut, err := os.OpenFile(filepath.Join(*outDir, "matches.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		logger.Fatalf("open matches.jsonl: %v", err)
	}
	defer mOut.Close()

	gOut, err := os.OpenFile(filepath.Join(*outDir, "games.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		logger.Fatalf("open games.jsonl: %v", err)
	}
	defer gOut.Close()

	pOut, err := os.OpenFile(filepath.Join(*outDir, "positions.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		logger.Fatalf("open positions.jsonl: %v", err)
	}
	defer pOut.Close()

	mW := bufio.NewWriterSize(mOut, 1<<20)
	gW := bufio.NewWriterSize(gOut, 1<<20)
	pW := bufio.NewWriterSize(pOut, 1<<20)

	type result struct {
		matches   [][]byte
		games     [][]byte
		positions [][]byte
		err       error
		path      string
	}

	fileCh := make(chan string, *workers*2)
	resCh := make(chan result, *workers*2)

	var wg sync.WaitGroup
	for i := 0; i < *workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for path := range fileCh {
				r := processFile(path)
				resCh <- r
			}
		}()
	}

	go func() {
		for _, f := range files {
			fileCh <- f
		}
		close(fileCh)
		wg.Wait()
		close(resCh)
	}()

	var (
		nFiles, nMatches, nGames, nPositions, nErrors int
		start                                          = time.Now()
	)

	for res := range resCh {
		nFiles++
		if res.err != nil {
			nErrors++
			logger.Printf("error: %s: %v", res.path, res.err)
			continue
		}
		for _, line := range res.matches {
			mW.Write(line)
			mW.WriteByte('\n')
			nMatches++
		}
		for _, line := range res.games {
			gW.Write(line)
			gW.WriteByte('\n')
			nGames++
		}
		for _, line := range res.positions {
			pW.Write(line)
			pW.WriteByte('\n')
			nPositions++
		}
		if nFiles%1000 == 0 {
			elapsed := time.Since(start)
			logger.Printf("processed %d/%d files, %d matches, %d games, %d positions (%.0f files/s)",
				nFiles, len(files), nMatches, nGames, nPositions,
				float64(nFiles)/elapsed.Seconds())
		}
	}

	mW.Flush()
	gW.Flush()
	pW.Flush()

	elapsed := time.Since(start)
	logger.Printf("done: %d files in %s (%.0f files/s)",
		nFiles, elapsed.Round(time.Second), float64(nFiles)/elapsed.Seconds())
	logger.Printf("output: %d matches, %d games, %d positions, %d errors",
		nMatches, nGames, nPositions, nErrors)
}

// processFile parses one .xg file and returns serialized JSONL lines.
func processFile(path string) struct {
	matches   [][]byte
	games     [][]byte
	positions [][]byte
	err       error
	path      string
} {
	type result = struct {
		matches   [][]byte
		games     [][]byte
		positions [][]byte
		err       error
		path      string
	}

	match, err := convert.ParseXGFile(path)
	if err != nil {
		return result{err: err, path: path}
	}

	matchID := computeMatchID(match)
	var matchLines, gameLines, posLines [][]byte

	// Match record.
	matchRec := buildMatchRecord(match, matchID)
	mb, err := json.Marshal(matchRec)
	if err != nil {
		return result{err: fmt.Errorf("marshal match: %w", err), path: path}
	}
	matchLines = append(matchLines, mb)

	// Game + position records.
	for gi, game := range match.Games {
		gameID := fmt.Sprintf("%s_game_%02d", matchID, gi+1)

		gameRec := buildGameRecord(&game, gameID, matchID, match.Metadata.MatchLength)
		gb, err := json.Marshal(gameRec)
		if err != nil {
			continue
		}
		gameLines = append(gameLines, gb)

		for mi, mv := range game.Moves {
			if mv.Position == nil {
				continue
			}
			posID := fmt.Sprintf("%s_move_%03d", gameID, mi+1)
			posRec := buildPositionRecord(&mv, posID, gameID, mi+1)
			pb, err := json.Marshal(posRec)
			if err != nil {
				continue
			}
			posLines = append(posLines, pb)
		}
	}

	return result{
		matches:   matchLines,
		games:     gameLines,
		positions: posLines,
		path:      path,
	}
}

// computeMatchID returns a 16-hex-char deterministic ID for a match.
func computeMatchID(m *gbf.Match) string {
	p1 := strings.TrimSpace(strings.ToLower(m.Metadata.Player1Name))
	p2 := strings.TrimSpace(strings.ToLower(m.Metadata.Player2Name))
	key := fmt.Sprintf("%s|%s|%s|%s", p1, p2, m.Metadata.Date, m.Metadata.Event)
	h := sha256.Sum256([]byte(key))
	return hex.EncodeToString(h[:8])
}

// matchRecord is the JSON structure for matches.jsonl.
type matchRecord struct {
	MatchID      string `json:"match_id"`
	Player1      string `json:"player1"`
	Player2      string `json:"player2"`
	MatchLength  int    `json:"match_length"`
	Tournament   string `json:"tournament"`
	Date         string `json:"date"`
	NumGames     int    `json:"num_games"`
	Winner       int    `json:"winner"` // 1=player1, 2=player2, 0=unknown
	ScoreFinalP1 int    `json:"score_final_p1"`
	ScoreFinalP2 int    `json:"score_final_p2"`
}

func buildMatchRecord(m *gbf.Match, matchID string) matchRecord {
	var scoreP1, scoreP2, winner int
	for _, g := range m.Games {
		if g.Winner == gbf.PlayerX {
			scoreP1 += g.PointsWon
		} else if g.Winner == gbf.PlayerO {
			scoreP2 += g.PointsWon
		}
	}
	if m.Metadata.MatchLength > 0 {
		if scoreP1 >= m.Metadata.MatchLength {
			winner = 1
		} else if scoreP2 >= m.Metadata.MatchLength {
			winner = 2
		}
	}
	return matchRecord{
		MatchID:      matchID,
		Player1:      m.Metadata.Player1Name,
		Player2:      m.Metadata.Player2Name,
		MatchLength:  m.Metadata.MatchLength,
		Tournament:   m.Metadata.Event,
		Date:         m.Metadata.Date,
		NumGames:     len(m.Games),
		Winner:       winner,
		ScoreFinalP1: scoreP1,
		ScoreFinalP2: scoreP2,
	}
}

// gameRecord is the JSON structure for games.jsonl.
type gameRecord struct {
	GameID      string `json:"game_id"`
	MatchID     string `json:"match_id"`
	GameNumber  int    `json:"game_number"`
	ScoreAwayP1 int    `json:"score_away_p1"`
	ScoreAwayP2 int    `json:"score_away_p2"`
	Crawford    bool   `json:"crawford"`
	Winner      int    `json:"winner"`  // 1=player1, 2=player2, 0=unfinished
	PointsWon   int    `json:"points_won"`
	Gammon      bool   `json:"gammon"`
	Backgammon  bool   `json:"backgammon"`
}

func buildGameRecord(g *gbf.Game, gameID, matchID string, matchLength int) gameRecord {
	winner := 0
	if g.Winner == gbf.PlayerX {
		winner = 1
	} else if g.Winner == gbf.PlayerO {
		winner = 2
	}

	// Compute away scores: points remaining to win.
	// For money games (matchLength=0), away scores are not meaningful; use 0.
	awayP1, awayP2 := 0, 0
	if matchLength > 0 {
		awayP1 = matchLength - g.InitialScore[0]
		awayP2 = matchLength - g.InitialScore[1]
	}

	// Derive gammon/backgammon from last position's cube value.
	lastCube := lastCubeValue(g)
	gammon := lastCube > 0 && g.PointsWon == 2*lastCube
	backgammon := lastCube > 0 && g.PointsWon == 3*lastCube

	return gameRecord{
		GameID:      gameID,
		MatchID:     matchID,
		GameNumber:  g.GameNumber,
		ScoreAwayP1: awayP1,
		ScoreAwayP2: awayP2,
		Crawford:    g.Crawford,
		Winner:      winner,
		PointsWon:   g.PointsWon,
		Gammon:      gammon,
		Backgammon:  backgammon,
	}
}

// lastCubeValue returns the cube value from the last position in the game.
func lastCubeValue(g *gbf.Game) int {
	for i := len(g.Moves) - 1; i >= 0; i-- {
		if g.Moves[i].Position != nil {
			return g.Moves[i].Position.CubeValue
		}
	}
	return 1
}

// positionRecord is the JSON structure for positions.jsonl.
type positionRecord struct {
	PositionID      string          `json:"position_id"`
	GameID          string          `json:"game_id"`
	MoveNumber      int             `json:"move_number"`
	PlayerOnRoll    int             `json:"player_on_roll"` // 1=player1, 2=player2
	DecisionType    string          `json:"decision_type"`  // "checker" or "cube"
	Dice            []int           `json:"dice"`           // null for cube decisions
	BoardP1         [26]int         `json:"board_p1"`       // bar,1..24,off from P1 perspective
	BoardP2         [26]int         `json:"board_p2"`       // bar,1..24,off from P2 perspective
	CubeValue       int             `json:"cube_value"`
	CubeOwner       int             `json:"cube_owner"` // 0=center,1=p1,2=p2
	EvalEquity      *float64        `json:"eval_equity,omitempty"`
	EvalWin         *float64        `json:"eval_win,omitempty"`
	EvalWinG        *float64        `json:"eval_win_g,omitempty"`
	EvalWinBG       *float64        `json:"eval_win_bg,omitempty"`
	EvalLoseG       *float64        `json:"eval_lose_g,omitempty"`
	EvalLoseBG      *float64        `json:"eval_lose_bg,omitempty"`
	MovePlayed      *string         `json:"move_played,omitempty"`
	MovePlayedError *float64        `json:"move_played_error,omitempty"`
	BestMove        *string         `json:"best_move,omitempty"`
	BestMoveEquity  *float64        `json:"best_move_equity,omitempty"`
	CubeActionPlayed *string        `json:"cube_action_played,omitempty"`
	CubeActionOptimal *string       `json:"cube_action_optimal,omitempty"`
	Candidates      []candidateRec  `json:"candidates,omitempty"`
}

type candidateRec struct {
	Move   string  `json:"move"`
	Equity float64 `json:"equity"`
	Win    float64 `json:"win"`
	WinG   float64 `json:"win_g"`
	WinBG  float64 `json:"win_bg"`
	LoseG  float64 `json:"lose_g"`
	LoseBG float64 `json:"lose_bg"`
}

func buildPositionRecord(mv *gbf.Move, posID, gameID string, moveNumber int) positionRecord {
	pos := mv.Position
	p := positionRecord{
		PositionID: posID,
		GameID:     gameID,
		MoveNumber: moveNumber,
		CubeValue:  pos.CubeValue,
		CubeOwner:  pos.CubeOwner,
	}

	if pos.SideToMove == gbf.PlayerX {
		p.PlayerOnRoll = 1
	} else {
		p.PlayerOnRoll = 2
	}

	p.BoardP1 = encodeBoard(pos, gbf.PlayerX)
	p.BoardP2 = encodeBoard(pos, gbf.PlayerO)

	switch mv.MoveType {
	case gbf.MoveTypeChecker:
		p.DecisionType = "checker"
		if mv.Dice[0] > 0 || mv.Dice[1] > 0 {
			p.Dice = []int{mv.Dice[0], mv.Dice[1]}
		}
		ms := mv.MoveString
		p.MovePlayed = &ms

		if mv.CheckerAnalysis != nil && len(mv.CheckerAnalysis.Moves) > 0 {
			best := mv.CheckerAnalysis.Moves[0]
			bestEq := float64(best.Equity) / 10000
			bestWin := float64(best.WinRate) / 10000
			bestWinG := float64(best.GammonRate) / 10000
			bestWinBG := float64(best.BackgammonRate) / 10000
			bestLoseG := float64(best.OppGammonRate) / 10000
			bestLoseBG := float64(best.OppBackgammonRate) / 10000

			p.EvalEquity = &bestEq
			p.EvalWin = &bestWin
			p.EvalWinG = &bestWinG
			p.EvalWinBG = &bestWinBG
			p.EvalLoseG = &bestLoseG
			p.EvalLoseBG = &bestLoseBG

			errVal := float64(mv.EquityDiff) / 10000
			p.MovePlayedError = &errVal

			playedEq := float64(mv.PlayedEquity) / 10000
			_ = playedEq // best_move_equity is of the best move
			p.BestMoveEquity = &bestEq

			bestMoveStr := moveEncodingToString(best.Move)
			p.BestMove = &bestMoveStr

			for _, cand := range mv.CheckerAnalysis.Moves {
				p.Candidates = append(p.Candidates, candidateRec{
					Move:   moveEncodingToString(cand.Move),
					Equity: float64(cand.Equity) / 10000,
					Win:    float64(cand.WinRate) / 10000,
					WinG:   float64(cand.GammonRate) / 10000,
					WinBG:  float64(cand.BackgammonRate) / 10000,
					LoseG:  float64(cand.OppGammonRate) / 10000,
					LoseBG: float64(cand.OppBackgammonRate) / 10000,
				})
			}
		}

	case gbf.MoveTypeCube:
		p.DecisionType = "cube"
		p.Dice = nil
		action := mv.CubeAction
		p.CubeActionPlayed = &action

		if mv.CubeAnalysis != nil {
			optimalAction := cubeOptimalAction(mv.CubeAnalysis)
			p.CubeActionOptimal = &optimalAction

			eq := float64(mv.CubeAnalysis.CubefulNoDouble) / 10000
			win := float64(mv.CubeAnalysis.WinRate) / 10000
			winG := float64(mv.CubeAnalysis.GammonRate) / 10000
			winBG := float64(mv.CubeAnalysis.BackgammonRate) / 10000
			loseG := float64(mv.CubeAnalysis.OppGammonRate) / 10000
			loseBG := float64(mv.CubeAnalysis.OppBackgammonRate) / 10000

			p.EvalEquity = &eq
			p.EvalWin = &win
			p.EvalWinG = &winG
			p.EvalWinBG = &winBG
			p.EvalLoseG = &loseG
			p.EvalLoseBG = &loseBG
		}
	}

	return p
}

// encodeBoard encodes the board as a 26-element array from the given player's perspective.
// Indices: 0=bar, 1..24=points (player's 1-point to 24-point), 25=borne off.
func encodeBoard(pos *gbf.PositionState, player int) [26]int {
	var arr [26]int
	if player == gbf.PlayerX {
		arr[0] = pos.BarX
		arr[25] = pos.BorneOffX
		for i := 0; i < 24; i++ {
			if pos.Board[i] > 0 {
				arr[i+1] = pos.Board[i]
			}
		}
	} else {
		arr[0] = pos.BarO
		arr[25] = pos.BorneOffO
		// O's 1-point = GBF index 23, O's 24-point = GBF index 0
		for i := 0; i < 24; i++ {
			gbfIdx := 23 - i
			if pos.Board[gbfIdx] < 0 {
				arr[i+1] = -pos.Board[gbfIdx]
			}
		}
	}
	return arr
}

// cubeOptimalAction returns the optimal cube action string.
func cubeOptimalAction(cda *gbf.CubeDecisionAnalysis) string {
	switch cda.BestAction {
	case gbf.CubeActionNoDouble:
		return "No Double"
	case gbf.CubeActionDoubleTake:
		return "Double/Take"
	case gbf.CubeActionDoublePass:
		return "Double/Pass"
	default:
		return "No Double"
	}
}

// moveEncodingToString converts a MoveEncoding to a human-readable string.
func moveEncodingToString(me gbf.MoveEncoding) string {
	type sub struct {
		from, to int
	}
	var subs []sub
	for _, sm := range me.Submoves {
		if sm[0] == gbf.MoveUnused {
			break
		}
		subs = append(subs, sub{int(sm[0]), int(sm[1])})
	}
	if len(subs) == 0 {
		return "Cannot Move"
	}
	sort.Slice(subs, func(i, j int) bool {
		return subs[i].from > subs[j].from
	})

	formatPt := func(p int) string {
		if p == gbf.MoveFromBar {
			return "bar"
		}
		if p == gbf.MoveToBearOff {
			return "off"
		}
		return fmt.Sprintf("%d", p+1) // GBF is 0-indexed, display is 1-indexed
	}

	// Merge identical sub-moves.
	type merged struct {
		from, to, count int
	}
	var parts []merged
	for _, s := range subs {
		if len(parts) > 0 && parts[len(parts)-1].from == s.from && parts[len(parts)-1].to == s.to {
			parts[len(parts)-1].count++
		} else {
			parts = append(parts, merged{s.from, s.to, 1})
		}
	}

	var tokens []string
	for _, m := range parts {
		if m.count > 1 {
			tokens = append(tokens, fmt.Sprintf("%s/%s(%d)", formatPt(m.from), formatPt(m.to), m.count))
		} else {
			tokens = append(tokens, fmt.Sprintf("%s/%s", formatPt(m.from), formatPt(m.to)))
		}
	}
	return strings.Join(tokens, " ")
}

// collectXGFiles returns a sorted list of .xg file paths under root.
func collectXGFiles(root string, limit int) ([]string, error) {
	var files []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && strings.EqualFold(filepath.Ext(path), ".xg") {
			files = append(files, path)
			if limit > 0 && len(files) >= limit {
				return fs.SkipAll
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	return files, nil
}

