package convert

import (
	"context"
	"fmt"
	"log"
	"path/filepath"
	"strings"

	gbf "github.com/kevung/gbf"
)

// ImportFile parses a single file and imports it into store.
// Format is detected from the file extension (.xg, .sgf, .mat, .bgf, .txt).
// Non-fatal conversion errors are logged; fatal errors (parse failure) are returned.
func ImportFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".xg":
		return importXGFile(ctx, store, path, logger)
	case ".sgf":
		return importSGFFile(ctx, store, path, logger)
	case ".mat":
		return importMATFile(ctx, store, path, logger)
	case ".bgf":
		return importBGFFile(ctx, store, path, logger)
	case ".txt":
		return importTXTFile(ctx, store, path, logger)
	default:
		return gbf.ImportResult{}, fmt.Errorf("unsupported format %q: %s", ext, filepath.Base(path))
	}
}

func importXGFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	match, err := ParseXGFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	return importMatch(ctx, store, path, match, "eXtreme Gammon", logger)
}

func importSGFFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	match, err := ParseSGFFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	return importMatch(ctx, store, path, match, "GNU Backgammon", logger)
}

func importMATFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	match, err := ParseMATFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	return importMatch(ctx, store, path, match, "GNU Backgammon", logger)
}

func importBGFFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	match, err := ParseBGFFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	return importMatch(ctx, store, path, match, "BGBlitz", logger)
}

// importTXTFile handles BGBlitz text export (.txt), which contains a single
// position + analysis rather than a full match. It wraps it in a synthetic match.
func importTXTFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	pos, cpa, cda, err := parseBGFTextFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}

	mv := gbf.Move{
		MoveType:        gbf.MoveTypeChecker,
		Player:          pos.SideToMove,
		Dice:            pos.Dice,
		Position:        pos,
		CheckerAnalysis: cpa,
		CubeAnalysis:    cda,
	}

	match := &gbf.Match{
		Metadata: gbf.MatchMetadata{
			Player1Name: pos.Player1Name,
			Player2Name: pos.Player2Name,
			MatchLength: pos.MatchLength,
			EngineName:  "BGBlitz",
		},
		Games: []gbf.Game{
			{
				GameNumber: 1,
				Moves:      []gbf.Move{mv},
			},
		},
	}

	return importMatch(ctx, store, path, match, "BGBlitz", logger)
}

func importMatch(ctx context.Context, store gbf.Store, path string, match *gbf.Match, engineName string, logger *log.Logger) (gbf.ImportResult, error) {
	matchHash := gbf.ComputeMatchHash(match)
	canonHash := gbf.ComputeCanonicalMatchHash(match)

	imp := &gbf.Importer{
		Store:      store,
		EngineName: engineName,
		Logger:     logger,
	}
	return imp.ImportMatch(ctx, match, matchHash, canonHash)
}

