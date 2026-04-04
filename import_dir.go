package gbf

import (
	"bufio"
	"context"
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

	// Workers is the number of parallel parser goroutines (default: runtime.NumCPU()).
	// Set to 1 to disable parallelism (sequential parse + DB writes in one goroutine).
	Workers int
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
	FilesTotal    int
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
//
// Parsing is parallelised across opts.Workers goroutines (default: NumCPU).
// A single DB-writer goroutine handles all store operations and journal/error
// log writes to preserve serial ordering and avoid locking.
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
	workers := opts.Workers
	if workers <= 0 {
		workers = runtime.NumCPU()
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

	// Filter out already-imported files.
	var toImport []string
	for _, f := range files {
		if journal[f] {
			report.FilesSkipped++
			continue
		}
		toImport = append(toImport, f)
	}

	// Internal context for pipeline cancellation (early stop on MaxErrors).
	pipeCtx, pipeCancel := context.WithCancel(ctx)
	defer pipeCancel()

	type parseResult struct {
		path  string
		match *Match
		err   error
	}

	pathCh := make(chan string, workers*2)
	resultCh := make(chan parseResult, workers*2)

	// Feeder: push file paths into pathCh.
	go func() {
		defer close(pathCh)
		for _, path := range toImport {
			select {
			case <-pipeCtx.Done():
				return
			case pathCh <- path:
			}
		}
	}()

	// Parser workers: parse files concurrently.
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for path := range pathCh {
				m, parseErr := opts.FileParser(path)
				select {
				case <-pipeCtx.Done():
					return
				case resultCh <- parseResult{path: path, match: m, err: parseErr}:
				}
			}
		}()
	}

	// Close resultCh once all parsers have exited.
	go func() {
		wg.Wait()
		close(resultCh)
	}()

	// DB writer: accumulate parsed results into batches and commit.
	var pending []parseResult

	flushBatch := func() bool {
		if len(pending) == 0 {
			return true
		}
		items := pending
		pending = pending[:0]

		if hasBatcher {
			if err := batcher.BeginBatch(ctx); err != nil {
				logf(opts.Logger, "begin batch: %v — skipping batch", err)
				report.FilesFailed += len(items)
				return true
			}
		}

		batchOK := true
		for _, item := range items {
			if item.err != nil {
				report.FilesFailed++
				msg := fmt.Sprintf("%s: %v", filepath.Base(item.path), item.err)
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

			matchHash := ComputeMatchHash(item.match)
			canonHash := ComputeCanonicalMatchHash(item.match)
			res, importErr := imp.ImportMatch(ctx, item.match, matchHash, canonHash)
			if importErr != nil {
				report.FilesFailed++
				msg := fmt.Sprintf("%s: %v", filepath.Base(item.path), importErr)
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
				fmt.Fprintln(journalW, item.path)
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
			pipeCancel()
			return false
		}
		return true
	}

	for result := range resultCh {
		if ctx.Err() != nil {
			pipeCancel()
			break
		}
		pending = append(pending, result)
		if len(pending) >= opts.BatchSize {
			if !flushBatch() {
				break
			}
		}
	}

	// Flush any remaining items.
	flushBatch()

	// Drain resultCh so that blocked parser goroutines can exit cleanly.
	for range resultCh {
	}

	report.Elapsed = time.Since(start)
	if report.Elapsed.Seconds() > 0 {
		report.AvgRate = float64(report.Positions) / report.Elapsed.Seconds()
	}

	return report, nil
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
