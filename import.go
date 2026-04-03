package gbf

import (
	"context"
	"fmt"
	"log"
)

// ImportResult summarises the outcome of an import operation.
type ImportResult struct {
	Matches   int
	Games     int
	Moves     int
	Positions int // distinct positions upserted
	Skipped   int // moves skipped due to conversion errors
}

// Importer converts a parsed Match into GBF records and persists them.
// It is format-agnostic: callers supply the parsed Match.
type Importer struct {
	Store      Store
	EngineName string // written into analyses.engine_name
	Logger     *log.Logger
}

// ImportMatch persists a pre-parsed Match into the store.
// Non-fatal errors (bad positions) are logged and skipped.
// Returns an ImportResult and the first fatal error, if any.
func (imp *Importer) ImportMatch(ctx context.Context, m *Match, matchHash, canonHash string) (ImportResult, error) {
	var res ImportResult

	matchID, err := imp.Store.UpsertMatch(ctx, *m, matchHash, canonHash)
	if err != nil {
		return res, fmt.Errorf("upsert match: %w", err)
	}
	res.Matches = 1

	for gi, game := range m.Games {
		gameID, err := imp.Store.InsertGame(ctx, matchID, game)
		if err != nil {
			imp.logf("game %d: insert failed: %v — skipping", gi+1, err)
			continue
		}
		res.Games++

		for mi, mv := range game.Moves {
			if mv.Position == nil {
				res.Skipped++
				continue
			}

			rec, err := PositionToBaseRecord(mv.Position)
			if err != nil {
				imp.logf("game %d move %d: position conversion: %v — skipping", gi+1, mi+1, err)
				res.Skipped++
				continue
			}

			boardHash := ComputeBoardOnlyZobrist(rec)
			posID, err := imp.Store.UpsertPosition(ctx, *rec, boardHash)
			if err != nil {
				imp.logf("game %d move %d: upsert position: %v — skipping", gi+1, mi+1, err)
				res.Skipped++
				continue
			}
			res.Positions++

			if err := imp.Store.InsertMove(ctx, gameID, mi+1, posID, mv); err != nil {
				imp.logf("game %d move %d: insert move: %v — skipping", gi+1, mi+1, err)
				res.Skipped++
				continue
			}
			res.Moves++

			engineName := imp.engineName()
			if mv.CheckerAnalysis != nil {
				payload := MarshalCheckerPlayAnalysis(mv.CheckerAnalysis)
				if err := imp.Store.AddAnalysis(ctx, posID, BlockTypeCheckerPlay, engineName, payload); err != nil {
					imp.logf("game %d move %d: add checker analysis: %v", gi+1, mi+1, err)
				}
			}
			if mv.CubeAnalysis != nil {
				payload := MarshalCubeDecisionAnalysis(mv.CubeAnalysis)
				if err := imp.Store.AddAnalysis(ctx, posID, BlockTypeCubeDecision, engineName, payload); err != nil {
					imp.logf("game %d move %d: add cube analysis: %v", gi+1, mi+1, err)
				}
			}
		}
	}

	return res, nil
}

func (imp *Importer) engineName() string {
	if imp.EngineName != "" {
		return imp.EngineName
	}
	return "unknown"
}

func (imp *Importer) logf(format string, args ...any) {
	if imp.Logger != nil {
		imp.Logger.Printf(format, args...)
	}
}
