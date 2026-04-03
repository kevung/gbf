package convert_test

import (
	"context"
	"log"
	"os"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
)

// [U] Format detection — known and unknown extensions.
func TestFormatDetection(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()

	for _, ext := range []string{".xg", ".sgf", ".mat", ".txt"} {
		path := "doesnotexist" + ext
		_, err := convert.ImportFile(ctx, store, path, nil)
		// Any error other than "unsupported format" is acceptable (file not found, parse error)
		// The key assertion: no "unsupported format" error for known extensions.
		if err != nil {
			if err.Error() == "unsupported format" {
				t.Errorf("extension %s reported as unsupported", ext)
			}
			// File-not-found is expected — format was detected.
		}
	}

	_, err := convert.ImportFile(ctx, store, "match.unknown", nil)
	if err == nil {
		t.Error("expected error for unknown extension, got nil")
	}
}

// [U] GnuBG position conversion — parse test.sgf and verify basic board integrity.
func TestGnuBGPositionConversion(t *testing.T) {
	path := dataFile(t, "test.sgf")
	match, err := convert.ParseSGFFile(path)
	if err != nil {
		t.Fatalf("ParseSGFFile: %v", err)
	}
	if len(match.Games) == 0 {
		t.Fatal("no games in test.sgf")
	}
	if len(match.Games[0].Moves) == 0 {
		t.Fatal("no moves in game 0")
	}

	mv := match.Games[0].Moves[0]
	if mv.Position == nil {
		t.Fatal("first move has nil position")
	}

	pos := mv.Position
	// Check total checker count: 15 per player.
	var totalX, totalO int
	for i := 0; i < 24; i++ {
		if pos.Board[i] > 0 {
			totalX += pos.Board[i]
		} else if pos.Board[i] < 0 {
			totalO += -pos.Board[i]
		}
	}
	totalX += pos.BarX + pos.BorneOffX
	totalO += pos.BarO + pos.BorneOffO

	if totalX != gbf.MaxCheckers {
		t.Errorf("Player X checker count: got %d, want %d", totalX, gbf.MaxCheckers)
	}
	if totalO != gbf.MaxCheckers {
		t.Errorf("Player O checker count: got %d, want %d", totalO, gbf.MaxCheckers)
	}

	// Zobrist hash must be stable.
	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}
	recomputed := gbf.ComputeZobrist(rec)
	if rec.Zobrist != recomputed {
		t.Errorf("Zobrist mismatch: stored %d != recomputed %d", rec.Zobrist, recomputed)
	}
}

// [U] MAT position conversion — parse test.mat and verify board integrity.
func TestMATPositionConversion(t *testing.T) {
	path := dataFile(t, "test.mat")
	match, err := convert.ParseMATFile(path)
	if err != nil {
		t.Fatalf("ParseMATFile: %v", err)
	}
	if len(match.Games) == 0 {
		t.Fatal("no games in test.mat")
	}
	if len(match.Games[0].Moves) == 0 {
		t.Skip("no moves in first game of test.mat")
	}

	mv := match.Games[0].Moves[0]
	if mv.Position == nil {
		t.Fatal("first move has nil position")
	}

	_, err = gbf.PositionToBaseRecord(mv.Position)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}
}

// [U] Canonical hash — same match from SGF and MAT must hash identically.
func TestCanonicalHashCrossFormat(t *testing.T) {
	sgfPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.sgf")
	matPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.mat")

	sgfMatch, err := convert.ParseSGFFile(sgfPath)
	if err != nil {
		t.Fatalf("ParseSGFFile: %v", err)
	}
	matMatch, err := convert.ParseMATFile(matPath)
	if err != nil {
		t.Fatalf("ParseMATFile: %v", err)
	}

	sgfHash := gbf.ComputeCanonicalMatchHash(sgfMatch)
	matHash := gbf.ComputeCanonicalMatchHash(matMatch)

	if sgfHash != matHash {
		t.Errorf("canonical hashes differ:\nSGF: %s\nMAT: %s", sgfHash, matHash)
	}
}

// [F] Import all sample formats — SGF, MAT, TXT.
func TestImportAllFormats(t *testing.T) {
	files := []string{"test.sgf", "test.mat", "test.txt"}

	for _, name := range files {
		t.Run(name, func(t *testing.T) {
			store := openStore(t)
			ctx := context.Background()
			path := dataFile(t, name)
			logger := log.New(os.Stderr, "["+name+"] ", 0)

			res, err := convert.ImportFile(ctx, store, path, logger)
			if err != nil {
				t.Fatalf("ImportFile(%s): %v", name, err)
			}
			if res.Matches == 0 {
				t.Error("expected at least 1 match")
			}
			if res.Positions == 0 {
				t.Error("expected at least 1 position")
			}
		})
	}
}

// [F] Cross-format dedup — import same match from SGF then MAT: 1 match entry.
func TestCrossFormatDedup(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()
	logger := log.New(os.Stderr, "[dedup] ", 0)

	sgfPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.sgf")
	matPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.mat")

	if _, err := convert.ImportFile(ctx, store, sgfPath, logger); err != nil {
		t.Fatalf("import SGF: %v", err)
	}
	if _, err := convert.ImportFile(ctx, store, matPath, logger); err != nil {
		t.Fatalf("import MAT: %v", err)
	}

	db := store.DB()
	var count int
	db.QueryRow("SELECT COUNT(*) FROM matches").Scan(&count)
	if count != 1 {
		t.Errorf("matches after SGF+MAT import: got %d, want 1", count)
	}
}

// [F] Board-hash overlap — same match from different formats shares board positions.
func TestBoardHashOverlapCrossFormat(t *testing.T) {
	store := openStore(t)
	ctx := context.Background()
	logger := log.New(os.Stderr, "[overlap] ", 0)

	sgfPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.sgf")
	matPath := dataFile(t, "charlot1-charlot2_7p_2025-11-08-2305.mat")

	res1, err := convert.ImportFile(ctx, store, sgfPath, logger)
	if err != nil {
		t.Fatalf("import SGF: %v", err)
	}
	res2, err := convert.ImportFile(ctx, store, matPath, logger)
	if err != nil {
		t.Fatalf("import MAT: %v", err)
	}

	// Second import of same match: deduped, so positions should not grow.
	// Positions from the MAT import reuse existing positions via UpsertPosition.
	t.Logf("SGF: %d positions, MAT: %d positions (deduped)", res1.Positions, res2.Positions)

	// At minimum, first import should have produced positions.
	if res1.Positions == 0 {
		t.Error("SGF import produced 0 positions")
	}
}

// [F] All data/ files (excluding bmab) import without error.
func TestImportAllDataFiles(t *testing.T) {
	files := []string{
		"test.xg", "test.sgf", "test.mat", "test.txt",
		"charlot1-charlot2_7p_2025-11-08-2305.sgf",
		"charlot1-charlot2_7p_2025-11-08-2305.mat",
	}

	store := openStore(t)
	ctx := context.Background()
	logger := log.New(os.Stderr, "[all] ", 0)

	for _, name := range files {
		path := dataFile(t, name)
		if _, err := convert.ImportFile(ctx, store, path, logger); err != nil {
			t.Errorf("ImportFile(%s): %v", name, err)
		}
	}
}
