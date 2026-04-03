package gbf_test

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
)

func openSQLiteStore(t *testing.T) *sqlite.SQLiteStore {
	t.Helper()
	p := filepath.Join(t.TempDir(), "test.db")
	store, err := sqlite.NewSQLiteStore(p)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func xgParser(path string) (*gbf.Match, error) {
	return convert.ParseXGFile(path)
}

func bmabDir(t *testing.T) string {
	t.Helper()
	dir := filepath.Join("data", "bmab-2025-06-23")
	if _, err := os.Stat(dir); err != nil {
		t.Skipf("BMAB dataset not found: %s", dir)
	}
	return dir
}

// [U] Batch transaction — commit: 10 files in batches of 5, all committed.
func TestBatchCommit(t *testing.T) {
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	opts := gbf.ImportOpts{
		BatchSize:  5,
		Limit:      10,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	report, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("ImportDirectory: %v", err)
	}

	if report.FilesImported+report.FilesFailed != 10 {
		t.Errorf("expected 10 files processed, got %d imported + %d failed",
			report.FilesImported, report.FilesFailed)
	}
	if report.Positions == 0 {
		t.Error("expected positions > 0")
	}

	// Verify data is actually in DB.
	db := store.DB()
	var count int
	db.QueryRow("SELECT COUNT(*) FROM positions").Scan(&count)
	if count == 0 {
		t.Error("no positions in DB after import")
	}
}

// [U] Journal — skip already imported files.
func TestJournalSkip(t *testing.T) {
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	journalPath := filepath.Join(t.TempDir(), "journal.txt")

	// First run: import 5 files, write journal.
	opts := gbf.ImportOpts{
		BatchSize:   5,
		Limit:       5,
		JournalPath: journalPath,
		FileParser:  xgParser,
		EngineName:  "eXtreme Gammon",
	}
	r1, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("first import: %v", err)
	}

	// Second run: import 10 files — first 5 should be skipped via journal.
	opts.Limit = 10
	r2, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("second import: %v", err)
	}

	if r2.FilesSkipped != r1.FilesImported {
		t.Errorf("expected %d skipped on second run, got %d", r1.FilesImported, r2.FilesSkipped)
	}
	if r2.FilesImported > 10-r1.FilesImported {
		t.Errorf("second run imported more files than expected")
	}
}

// [U] Batch transaction — rollback on error.
// Injects a corrupt file into the batch; verifies error is counted and
// that other files in the batch are still committed (per-file errors are
// non-fatal; the batch continues).
func TestBatchErrorHandling(t *testing.T) {
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	errLogPath := filepath.Join(t.TempDir(), "errors.txt")

	// Use a parser that fails on the 3rd call.
	callCount := 0
	parser := func(path string) (*gbf.Match, error) {
		callCount++
		if callCount == 3 {
			return nil, fmt.Errorf("injected error")
		}
		return convert.ParseXGFile(path)
	}

	opts := gbf.ImportOpts{
		BatchSize:    10,
		Limit:        10,
		ErrorLogPath: errLogPath,
		FileParser:   parser,
		EngineName:   "eXtreme Gammon",
	}
	report, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("ImportDirectory: %v", err)
	}

	if report.FilesFailed != 1 {
		t.Errorf("expected 1 failed file, got %d", report.FilesFailed)
	}
	if report.FilesImported != 9 {
		t.Errorf("expected 9 imported files, got %d", report.FilesImported)
	}

	// Error log should have 1 line.
	content, err := os.ReadFile(errLogPath)
	if err != nil {
		t.Fatalf("read error log: %v", err)
	}
	lines := 0
	for _, b := range content {
		if b == '\n' {
			lines++
		}
	}
	if lines != 1 {
		t.Errorf("expected 1 line in error log, got %d", lines)
	}
}

// [F] Import 1000 BMAB files — completes, report is plausible.
// Run with: go test -run TestImport1000BMab -timeout 120s
func TestImport1000BMab(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping large import test in short mode")
	}
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	logger := log.New(os.Stderr, "[m3-1000] ", 0)
	opts := gbf.ImportOpts{
		BatchSize:        100,
		Limit:            1000,
		ProgressInterval: 200,
		FileParser:       xgParser,
		EngineName:       "eXtreme Gammon",
		Logger:           logger,
	}

	report, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("ImportDirectory: %v", err)
	}

	t.Logf("1000-file report: imported=%d failed=%d matches=%d positions=%d rate=%.0f pos/s elapsed=%s",
		report.FilesImported, report.FilesFailed, report.Matches, report.Positions,
		report.AvgRate, report.Elapsed.Round(0))

	if report.FilesImported == 0 {
		t.Error("expected files imported > 0")
	}
	if report.Positions == 0 {
		t.Error("expected positions > 0")
	}
	// Plausibility: at least ~50 positions per file on average.
	if report.Positions < report.FilesImported*50 {
		t.Errorf("too few positions: %d for %d files", report.Positions, report.FilesImported)
	}
}

// [F] Resume after interruption — no duplicates.
// Run with: go test -run TestResumeAfterInterruption -timeout 120s
func TestResumeAfterInterruption(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping large import test in short mode")
	}
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	journalPath := filepath.Join(t.TempDir(), "journal.txt")

	// First run: import 500 files.
	opts := gbf.ImportOpts{
		BatchSize:   100,
		Limit:       500,
		JournalPath: journalPath,
		FileParser:  xgParser,
		EngineName:  "eXtreme Gammon",
	}
	r1, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("first run: %v", err)
	}

	// Query actual DB count (r1.Positions counts upsert calls, not distinct rows).
	db := store.DB()
	var posAfterFirst int
	db.QueryRow("SELECT COUNT(*) FROM positions").Scan(&posAfterFirst)

	t.Logf("first run: imported=%d positions_report=%d positions_db=%d",
		r1.FilesImported, r1.Positions, posAfterFirst)

	// Second run: same limit 500, should all be in journal.
	r2, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("second run: %v", err)
	}

	if r2.FilesImported != 0 {
		t.Errorf("second run re-imported %d files (expected 0)", r2.FilesImported)
	}
	if r2.FilesSkipped != r1.FilesImported {
		t.Errorf("second run: skipped %d, expected %d", r2.FilesSkipped, r1.FilesImported)
	}

	// DB positions should not have grown.
	var dbCount int
	db.QueryRow("SELECT COUNT(*) FROM positions").Scan(&dbCount)
	if dbCount != posAfterFirst {
		t.Errorf("DB positions changed: %d → %d (expected no change)", posAfterFirst, dbCount)
	}
}

// [F] Import report accuracy — report totals match SQL counts.
// Run with: go test -run TestImportReportAccuracy -timeout 60s
func TestImportReportAccuracy(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping large import test in short mode")
	}
	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	opts := gbf.ImportOpts{
		BatchSize:  100,
		Limit:      200,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}

	report, err := gbf.ImportDirectory(ctx, store, dir, opts)
	if err != nil {
		t.Fatalf("ImportDirectory: %v", err)
	}

	db := store.DB()

	var posCount, matchCount, gameCount, moveCount int
	db.QueryRow("SELECT COUNT(*) FROM positions").Scan(&posCount)
	db.QueryRow("SELECT COUNT(*) FROM matches").Scan(&matchCount)
	db.QueryRow("SELECT COUNT(*) FROM games").Scan(&gameCount)
	db.QueryRow("SELECT COUNT(*) FROM moves").Scan(&moveCount)

	// The report tracks distinct new positions upserted; the DB may have more
	// due to dedup (same position across files). The report Positions count
	// includes all UpsertPosition calls (even if they return existing IDs).
	// So report.Positions >= posCount is not guaranteed either direction.
	// The key check: match/game/move counts should be consistent.
	if matchCount != report.Matches {
		t.Errorf("matches: report=%d DB=%d", report.Matches, matchCount)
	}
	if gameCount != report.Games {
		t.Errorf("games: report=%d DB=%d", report.Games, gameCount)
	}
	if moveCount != report.Moves {
		t.Errorf("moves: report=%d DB=%d", report.Moves, moveCount)
	}

	t.Logf("DB: matches=%d games=%d moves=%d positions=%d",
		matchCount, gameCount, moveCount, posCount)
}
