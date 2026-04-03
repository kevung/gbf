package convert

import (
	"context"
	"fmt"
	"log"
	"path/filepath"
	"strings"

	gbf "github.com/kevung/gbf"
)

// ImportFile parses a single XG file and imports it into store.
// The format is detected from the file extension (.xg only for now).
// Non-fatal conversion errors are logged; fatal errors (parse failure) are returned.
func ImportFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".xg":
		return importXGFile(ctx, store, path, logger)
	default:
		return gbf.ImportResult{}, fmt.Errorf("unsupported format %q: %s", ext, filepath.Base(path))
	}
}

func importXGFile(ctx context.Context, store gbf.Store, path string, logger *log.Logger) (gbf.ImportResult, error) {
	match, err := ParseXGFile(path)
	if err != nil {
		return gbf.ImportResult{}, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}

	matchHash := gbf.ComputeMatchHash(match)
	canonHash := gbf.ComputeCanonicalMatchHash(match)

	imp := &gbf.Importer{
		Store:      store,
		EngineName: "eXtreme Gammon",
		Logger:     logger,
	}
	return imp.ImportMatch(ctx, match, matchHash, canonHash)
}
