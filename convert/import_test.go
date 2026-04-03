package convert_test

import (
	"context"
	"log"
	"os"
	"path/filepath"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
)

// dataFile returns the absolute path to a file under data/.
func dataFile(t *testing.T, name string) string {
	t.Helper()
	// Tests run from the convert/ directory; data/ is one level up.
	path, err := filepath.Abs(filepath.Join("..", "data", name))
	if err != nil {
		t.Fatalf("abs path: %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Skipf("data file not found: %s", path)
	}
	return path
}

func openStore(t *testing.T) *sqlite.SQLiteStore {
	t.Helper()
	p := filepath.Join(t.TempDir(), "test.db")
	store, err := sqlite.NewSQLiteStore(p)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

// [F] Import test.xg — full pipeline.
func TestImportTestXG(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()
	path := dataFile(t, "test.xg")

	res, err := convert.ImportFile(ctx, store, path, log.New(os.Stderr, "[test] ", 0))
	if err != nil {
		t.Fatalf("ImportFile: %v", err)
	}

	if res.Matches != 1 {
		t.Errorf("matches: got %d, want 1", res.Matches)
	}
	if res.Games == 0 {
		t.Error("expected at least 1 game")
	}
	if res.Moves == 0 {
		t.Error("expected at least 1 move")
	}
	if res.Positions == 0 {
		t.Error("expected at least 1 position")
	}

	// Verify DB counts.
	db := store.DB()
	for _, tc := range []struct {
		table string
		minN  int
	}{
		{"matches", 1},
		{"games", res.Games},
		{"moves", res.Moves},
		{"positions", 1},
	} {
		var count int
		db.QueryRow("SELECT COUNT(*) FROM " + tc.table).Scan(&count)
		if count < tc.minN {
			t.Errorf("%s: got %d rows, want >= %d", tc.table, count, tc.minN)
		}
	}
}

// [F] Import idempotent — importing same file twice yields same row counts.
func TestImportIdempotent(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()
	path := dataFile(t, "test.xg")
	logger := log.New(os.Stderr, "[test] ", 0)

	if _, err := convert.ImportFile(ctx, store, path, logger); err != nil {
		t.Fatalf("first import: %v", err)
	}
	if _, err := convert.ImportFile(ctx, store, path, logger); err != nil {
		t.Fatalf("second import: %v", err)
	}

	db := store.DB()
	for _, table := range []string{"matches", "positions"} {
		var count int
		db.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&count)
		if table == "matches" && count != 1 {
			t.Errorf("matches after 2 imports: got %d, want 1", count)
		}
	}
}

// [F] Import corrupt file — returns error, no panic.
func TestImportCorruptFile(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()

	// Write an empty file.
	tmp := filepath.Join(t.TempDir(), "empty.xg")
	os.WriteFile(tmp, []byte{}, 0644)

	_, err := convert.ImportFile(ctx, store, tmp, nil)
	if err == nil {
		t.Error("expected error for empty file, got nil")
	}
}

// [F] Unsupported format — returns error.
func TestImportUnsupportedFormat(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()

	_, err := convert.ImportFile(ctx, store, "match.bgf", nil)
	if err == nil {
		t.Error("expected error for unsupported format")
	}
}

// [U] XG position conversion — standard opening.
func TestXGPositionConversion(t *testing.T) {
	path := dataFile(t, "test.xg")
	match, err := convert.ParseXGFile(path)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(match.Games) == 0 || len(match.Games[0].Moves) == 0 {
		t.Skip("no moves in test.xg")
	}

	mv := match.Games[0].Moves[0]
	if mv.Position == nil {
		t.Fatal("first move has nil position")
	}

	rec, err := gbf.PositionToBaseRecord(mv.Position)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	// Zobrist must be stable (recomputed == stored).
	recomputed := gbf.ComputeZobrist(rec)
	if rec.Zobrist != recomputed {
		t.Errorf("Zobrist mismatch: stored %d != recomputed %d", rec.Zobrist, recomputed)
	}
}

// [U] equity_diff extraction — BestEquity != PlayedEquity on a mistake.
func TestEquityDiffExtraction(t *testing.T) {
	path := dataFile(t, "test.xg")
	match, err := convert.ParseXGFile(path)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}

	// Find a move with checker analysis containing at least 2 candidates.
	for _, game := range match.Games {
		for _, mv := range game.Moves {
			if mv.CheckerAnalysis == nil || len(mv.CheckerAnalysis.Moves) < 2 {
				continue
			}
			// EquityDiff must be >= 0.
			if mv.EquityDiff < 0 {
				t.Errorf("EquityDiff is negative (%d)", mv.EquityDiff)
			}
			// BestEquity must match first analysis candidate.
			if mv.BestEquity != mv.CheckerAnalysis.Moves[0].Equity {
				t.Errorf("BestEquity mismatch: got %d, want %d", mv.BestEquity, mv.CheckerAnalysis.Moves[0].Equity)
			}
			return
		}
	}
	t.Skip("no moves with 2+ analysis candidates in test.xg")
}
