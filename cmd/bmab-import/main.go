// cmd/bmab-import imports BMAB dataset files into a GBF SQLite database.
//
// Usage:
//
//	bmab-import [flags] <dir>
//
// Flags:
//
//	-db      path to SQLite database (default: bmab.db)
//	-batch   files per transaction (default: 100)
//	-limit   max files to import (0 = all)
//	-journal path to resume journal file (default: bmab_journal.txt)
//	-errors  path to error log file (default: bmab_errors.txt)
//	-maxerr  stop after this many errors (0 = unlimited)
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
)

func main() {
	dbPath := flag.String("db", "bmab.db", "SQLite database path")
	batch := flag.Int("batch", 100, "files per transaction")
	limit := flag.Int("limit", 0, "max files to import (0=all)")
	journalPath := flag.String("journal", "bmab_journal.txt", "resume journal file")
	errLogPath := flag.String("errors", "bmab_errors.txt", "error log file")
	maxErr := flag.Int("maxerr", 0, "stop after N errors (0=unlimited)")
	flag.Parse()

	if flag.NArg() == 0 {
		fmt.Fprintln(os.Stderr, "usage: bmab-import [flags] <dir>")
		os.Exit(1)
	}
	target := flag.Arg(0)

	logger := log.New(os.Stdout, "[bmab] ", log.LstdFlags)

	store, err := sqlite.NewSQLiteStore(*dbPath)
	if err != nil {
		logger.Fatalf("open store: %v", err)
	}
	defer store.Close()

	logger.Printf("database: %s", *dbPath)
	logger.Printf("target:   %s", target)
	logger.Printf("batch:    %d files/tx", *batch)
	if *limit > 0 {
		logger.Printf("limit:    %d files", *limit)
	}

	opts := gbf.ImportOpts{
		BatchSize:        *batch,
		Limit:            *limit,
		MaxErrors:        *maxErr,
		JournalPath:      *journalPath,
		ErrorLogPath:     *errLogPath,
		ProgressInterval: 1000,
		EngineName:       "eXtreme Gammon",
		Logger:           logger,
		FileParser: func(path string) (*gbf.Match, error) {
			return convert.ParseXGFile(path)
		},
	}

	ctx := context.Background()
	start := time.Now()

	report, err := gbf.ImportDirectory(ctx, store, target, opts)
	if err != nil {
		logger.Fatalf("import: %v", err)
	}

	printReport(logger, report, *dbPath)
	_ = start
}

func printReport(logger *log.Logger, r gbf.DirectoryReport, dbPath string) {
	logger.Println("═══════════════════════════════════════")
	logger.Println("  BMAB Import Report")
	logger.Println("═══════════════════════════════════════")
	logger.Printf("  Files total:    %d", r.FilesTotal)
	logger.Printf("  Files imported: %d", r.FilesImported)
	logger.Printf("  Files skipped:  %d (journal)", r.FilesSkipped)
	logger.Printf("  Files failed:   %d", r.FilesFailed)
	logger.Printf("  Matches:        %d", r.Matches)
	logger.Printf("  Games:          %d", r.Games)
	logger.Printf("  Moves:          %d", r.Moves)
	logger.Printf("  Positions:      %d", r.Positions)
	logger.Printf("  Avg rate:       %.0f pos/s", r.AvgRate)
	logger.Printf("  Elapsed:        %s", r.Elapsed.Round(time.Second))

	if len(r.Errors) > 0 {
		logger.Printf("  Errors (%d):", len(r.Errors))
		for _, e := range r.Errors {
			logger.Printf("    %s", e)
		}
	}

	if fi, err := os.Stat(dbPath); err == nil {
		mb := float64(fi.Size()) / 1024 / 1024
		logger.Printf("  DB size:        %.1f MB", mb)
	}
	logger.Println("═══════════════════════════════════════")
}
