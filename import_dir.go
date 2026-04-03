package gbf

import (
	"bufio"
	"context"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// ImportOpts configures the ImportDirectory operation.
type ImportOpts struct {
	// BatchSize is the number of files per transaction (default: 100).
	BatchSize int

	// Limit caps the number of files imported (0 = no limit).
	Limit int

	// MaxErrors stops the import after this many errors (0 = unlimited).
	MaxErrors int

	// JournalPath is the path to the resume journal file.
	// Lines in this file are skipped on import. Successfully imported
	// files are appended to this file.
	// If empty, no journal is maintained.
	JournalPath string

	// ErrorLogPath is the path where failed file paths + errors are logged.
	// If empty, errors are only sent to Logger.
	ErrorLogPath string

	// ProgressInterval is how often to emit progress (default: 1000 files).
	ProgressInterval int

	// FileParser converts a file at path into a Match.
	// This makes ImportDirectory format-agnostic.
	FileParser func(path string) (*Match, error)

	// EngineName is written into analysis rows.
	EngineName string

	// Logger receives progress and error messages. Nil suppresses output.
	Logger *log.Logger

	// ProgressFn is called after each file (or batch) with the current stats.
	// It may be nil.
	ProgressFn func(p ProgressEvent)
}

// ProgressEvent carries the current import state during a directory import.
type ProgressEvent struct {
	FilesDone  int
	FilesTotal int
	Matches    int
	Positions  int
	Skipped    int
	Errors     int
	Rate       float64 // positions per second
	Elapsed    time.Duration
	Remaining  time.Duration
}

// DirectoryReport summarises a completed directory import.
type DirectoryReport struct {
	FilesTotal   int
	FilesImported int
	FilesSkipped  int // already in journal
	FilesFailed   int
	Matches       int
	Games         int
	Moves         int
	Positions     int
	AnalysisAdded int
	Errors        []string // first MaxErrors error messages
	Elapsed       time.Duration
	AvgRate       float64 // positions per second
}

// Batcher is an optional interface for stores that support explicit transactions.
// If a Store implements Batcher, ImportDirectory groups files into batch transactions.
type Batcher interface {
	BeginBatch(ctx context.Context) error
	CommitBatch() error
	RollbackBatch()
}

// ImportDirectory walks dir recursively, collecting files with supported
// extensions, and imports them using opts.FileParser.
func ImportDirectory(ctx context.Context, store Store, dir string, opts ImportOpts) (DirectoryReport, error) {
	if opts.BatchSize <= 0 {
		opts.BatchSize = 100
	}
	if opts.ProgressInterval <= 0 {
		opts.ProgressInterval = 1000
	}
	if opts.EngineName == "" {
		opts.EngineName = "unknown"
	}

	files, err := collectFiles(dir)
	if err != nil {
		return DirectoryReport{}, fmt.Errorf("collect files: %w", err)
	}
	if opts.Limit > 0 && len(files) > opts.Limit {
		files = files[:opts.Limit]
	}

	journal, err := loadJournal(opts.JournalPath)
	if err != nil {
		return DirectoryReport{}, fmt.Errorf("load journal: %w", err)
	}

	var journalW *bufio.Writer
	var journalF *os.File
	if opts.JournalPath != "" {
		journalF, err = os.OpenFile(opts.JournalPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			return DirectoryReport{}, fmt.Errorf("open journal: %w", err)
		}
		defer journalF.Close()
		journalW = bufio.NewWriter(journalF)
	}

	var errLogW *bufio.Writer
	var errLogF *os.File
	if opts.ErrorLogPath != "" {
		errLogF, err = os.OpenFile(opts.ErrorLogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			return DirectoryReport{}, fmt.Errorf("open error log: %w", err)
		}
		defer errLogF.Close()
		errLogW = bufio.NewWriter(errLogF)
	}

	batcher, hasBatcher := store.(Batcher)

	report := DirectoryReport{FilesTotal: len(files)}
	start := time.Now()

	imp := &Importer{
		Store:      store,
		EngineName: opts.EngineName,
		Logger:     opts.Logger,
	}

	// Collect files not in journal.
	var toImport []string
	for _, f := range files {
		if journal[f] {
			report.FilesSkipped++
			continue
		}
		toImport = append(toImport, f)
	}

	// Process in batches.
	for batchStart := 0; batchStart < len(toImport); batchStart += opts.BatchSize {
		if ctx.Err() != nil {
			break
		}

		end := batchStart + opts.BatchSize
		if end > len(toImport) {
			end = len(toImport)
		}
		batch := toImport[batchStart:end]

		if hasBatcher {
			if err := batcher.BeginBatch(ctx); err != nil {
				logf(opts.Logger, "begin batch: %v — skipping batch", err)
				report.FilesFailed += len(batch)
				continue
			}
		}

		batchOK := true
		for _, path := range batch {
			if ctx.Err() != nil {
				batchOK = false
				break
			}

			res, err := importOnefile(ctx, imp, path, opts.FileParser)
			if err != nil {
				report.FilesFailed++
				msg := fmt.Sprintf("%s: %v", filepath.Base(path), err)
				report.Errors = append(report.Errors, msg)
				logf(opts.Logger, "error: %s", msg)
				if errLogW != nil {
					fmt.Fprintln(errLogW, msg)
				}
				if opts.MaxErrors > 0 && report.FilesFailed >= opts.MaxErrors {
					batchOK = false
					break
				}
				continue
			}

			report.FilesImported++
			report.Matches += res.Matches
			report.Games += res.Games
			report.Moves += res.Moves
			report.Positions += res.Positions

			if journalW != nil {
				fmt.Fprintln(journalW, path)
			}
		}

		if hasBatcher {
			if batchOK {
				if err := batcher.CommitBatch(); err != nil {
					logf(opts.Logger, "commit batch: %v", err)
					batcher.RollbackBatch()
				}
			} else {
				batcher.RollbackBatch()
			}
		}

		if journalW != nil {
			journalW.Flush()
		}
		if errLogW != nil {
			errLogW.Flush()
		}

		// Progress reporting.
		done := report.FilesSkipped + report.FilesImported + report.FilesFailed
		if done%opts.ProgressInterval == 0 || done == report.FilesTotal {
			elapsed := time.Since(start)
			rate := 0.0
			if elapsed.Seconds() > 0 {
				rate = float64(report.Positions) / elapsed.Seconds()
			}
			var remaining time.Duration
			if rate > 0 && done < report.FilesTotal {
				estPos := float64(report.FilesTotal-done) * float64(report.Positions) / float64(done)
				remaining = time.Duration(estPos/rate) * time.Second
			}

			evt := ProgressEvent{
				FilesDone:  done,
				FilesTotal: report.FilesTotal,
				Matches:    report.Matches,
				Positions:  report.Positions,
				Skipped:    report.FilesSkipped,
				Errors:     report.FilesFailed,
				Rate:       rate,
				Elapsed:    elapsed,
				Remaining:  remaining,
			}
			if opts.ProgressFn != nil {
				opts.ProgressFn(evt)
			}
			logf(opts.Logger, "progress: %d/%d files | %d positions | %.0f pos/s | ~%s remaining",
				done, report.FilesTotal, report.Positions, rate, formatDuration(remaining))
		}

		if opts.MaxErrors > 0 && report.FilesFailed >= opts.MaxErrors {
			logf(opts.Logger, "max errors (%d) reached — stopping", opts.MaxErrors)
			break
		}
	}

	report.Elapsed = time.Since(start)
	if report.Elapsed.Seconds() > 0 {
		report.AvgRate = float64(report.Positions) / report.Elapsed.Seconds()
	}

	return report, nil
}

func importOnefile(ctx context.Context, imp *Importer, path string, parser func(string) (*Match, error)) (ImportResult, error) {
	match, err := parser(path)
	if err != nil {
		return ImportResult{}, err
	}
	matchHash := ComputeMatchHash(match)
	canonHash := ComputeCanonicalMatchHash(match)
	return imp.ImportMatch(ctx, match, matchHash, canonHash)
}

// collectFiles walks dir and returns all files with supported extensions,
// sorted for deterministic order.
func collectFiles(dir string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(path))
		if ext == ".xg" || ext == ".sgf" || ext == ".mat" || ext == ".bgf" {
			files = append(files, path)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	return files, nil
}

// LoadJournal reads a journal file and returns a set of already-imported paths.
// Exported for use by external tools.
func LoadJournal(path string) (map[string]bool, error) {
	return loadJournal(path)
}

// loadJournal reads a journal file and returns a set of already-imported paths.
func loadJournal(path string) (map[string]bool, error) {
	journal := make(map[string]bool)
	if path == "" {
		return journal, nil
	}
	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return journal, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()

	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line != "" {
			journal[line] = true
		}
	}
	return journal, sc.Err()
}

func logf(logger *log.Logger, format string, args ...any) {
	if logger != nil {
		logger.Printf(format, args...)
	}
}

func formatDuration(d time.Duration) string {
	if d <= 0 {
		return "unknown"
	}
	h := int(d.Hours())
	m := int(d.Minutes()) % 60
	s := int(d.Seconds()) % 60
	if h > 0 {
		return fmt.Sprintf("%dh%02dm%02ds", h, m, s)
	}
	if m > 0 {
		return fmt.Sprintf("%dm%02ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}
