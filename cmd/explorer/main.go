// cmd/explorer is a standalone data exploration UI for the GBF database.
//
// It embeds the Svelte SPA and starts an HTTP server. All configuration
// (database path, BMAB directory, projections) can be done from the web UI.
// Double-click the executable and it opens in your browser — no CLI needed.
//
// Usage (optional flags):
//
//	gbf-explorer                          # uses defaults, opens browser
//	gbf-explorer -db bmab.db -bmab ./bmab -no-browser
package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io/fs"
	"log"
	"math/rand/v2"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
	"github.com/kevung/gbf/viz"
)

//go:embed static/*
var embeddedStatic embed.FS

func main() {
	dbPath := ""
	bmabDir := ""
	addr := ":0" // auto-pick free port by default
	staticDir := ""
	noBrowser := false

	for i := 1; i < len(os.Args); i++ {
		switch os.Args[i] {
		case "-db":
			i++
			if i < len(os.Args) {
				dbPath = os.Args[i]
			}
		case "-bmab":
			i++
			if i < len(os.Args) {
				bmabDir = os.Args[i]
			}
		case "-addr":
			i++
			if i < len(os.Args) {
				addr = os.Args[i]
			}
		case "-static":
			i++
			if i < len(os.Args) {
				staticDir = os.Args[i]
			}
		case "-no-browser":
			noBrowser = true
		}
	}

	logger := log.New(os.Stdout, "[explorer] ", log.LstdFlags)

	srv := &server{
		logger:  logger,
		bmabDir: bmabDir,
		dbPath:  dbPath,
	}

	// If a DB path was given on the CLI, open it immediately.
	if dbPath != "" {
		if err := srv.openDB(dbPath); err != nil {
			logger.Fatalf("open store: %v", err)
		}
		defer srv.store.Close()
		logger.Printf("database: %s", dbPath)
	}

	if bmabDir != "" {
		logger.Printf("BMAB dir: %s", bmabDir)
	}

	mux := http.NewServeMux()

	// Setup & config API (works even without a DB open).
	mux.HandleFunc("GET /api/config", srv.handleConfig)
	mux.HandleFunc("POST /api/config/db", srv.handleConfigDB)
	mux.HandleFunc("POST /api/config/bmab", srv.handleConfigBMAB)
	mux.HandleFunc("POST /api/config/data", srv.handleConfigData)
	mux.HandleFunc("GET /api/config/browse", srv.handleBrowseDir)

	// Theme API (requires data directory configured).
	mux.HandleFunc("GET /api/themes/stats", srv.handleThemeStats)
	mux.HandleFunc("GET /api/themes/positions", srv.handleThemePositions)

	// Data APIs (require open DB).
	mux.HandleFunc("GET /api/stats", srv.requireDB(srv.handleStats))
	mux.HandleFunc("GET /api/features/names", srv.requireDB(srv.handleFeatureNames))
	mux.HandleFunc("GET /api/features/sample", srv.requireDB(srv.handleFeatureSample))
	mux.HandleFunc("POST /api/import/start", srv.requireDB(srv.handleImportStart))
	mux.HandleFunc("GET /api/import/progress", srv.handleImportProgress)
	mux.HandleFunc("GET /api/import/status", srv.handleImportStatus)
	mux.HandleFunc("POST /api/import/cancel", srv.handleImportCancel)

	// Projection compute API.
	mux.HandleFunc("POST /api/projection/compute", srv.requireDB(srv.handleProjectionCompute))
	mux.HandleFunc("POST /api/projection/rebuild-tiles", srv.requireDB(srv.handleRebuildTiles))
	mux.HandleFunc("GET /api/projection/progress", srv.handleProjectionProgress)
	mux.HandleFunc("GET /api/projection/status", srv.handleProjectionStatus)

	// Viz routes (registered dynamically when DB opens).
	mux.HandleFunc("GET /api/viz/projection", srv.requireDB(srv.handleVizProxy("projection")))
	mux.HandleFunc("GET /api/viz/clusters", srv.requireDB(srv.handleVizProxy("clusters")))
	mux.HandleFunc("GET /api/viz/position/{id}", srv.requireDB(srv.handleVizProxy("position")))
	mux.HandleFunc("GET /api/viz/runs", srv.requireDB(srv.handleVizProxy("runs")))
	mux.HandleFunc("GET /api/viz/tile/{method}/{lod}/{z}/{x}/{y}", srv.requireDB(srv.handleVizProxy("tile")))
	mux.HandleFunc("GET /api/viz/tilemeta/{method}/{lod}", srv.requireDB(srv.handleVizProxy("tilemeta")))

	// Static files — prefer external dir, fall back to embedded.
	if staticDir == "" {
		candidates := []string{
			"explorer/dist",
			filepath.Join(filepath.Dir(os.Args[0]), "../../explorer/dist"),
		}
		for _, c := range candidates {
			if info, err := os.Stat(c); err == nil && info.IsDir() {
				staticDir = c
				break
			}
		}
	}

	if staticDir != "" {
		logger.Printf("static:   %s (filesystem)", staticDir)
		serveStaticFS(mux, http.Dir(staticDir))
	} else {
		logger.Printf("static:   embedded")
		sub, err := fs.Sub(embeddedStatic, "static")
		if err != nil {
			logger.Fatalf("embedded static: %v", err)
		}
		serveStaticFS(mux, http.FS(sub))
	}

	// Listen.
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		logger.Fatalf("listen: %v", err)
	}
	actualAddr := ln.Addr().(*net.TCPAddr)
	url := fmt.Sprintf("http://localhost:%d", actualAddr.Port)
	logger.Printf("listening on %s", url)

	if !noBrowser {
		go openBrowser(url)
	}

	logger.Fatal(http.Serve(ln, withCORS(mux)))
}

type server struct {
	mu      sync.RWMutex
	store   *sqlite.SQLiteStore
	vizSrv  *viz.Server
	bmabDir string
	dbPath  string
	dataDir string // path to data/ directory (contains parquet/ and themes/)
	logger  *log.Logger

	// Theme position cache: maps theme name → JSON bytes (nil = not cached)
	themeCacheMu sync.RWMutex
	themeCache   map[string][]byte

	importMu       sync.Mutex
	importRunning  bool
	importProgress []progressEvent
	importDone     bool
	importCancel   context.CancelFunc // non-nil while running

	projMu       sync.Mutex
	projRunning  bool
	projProgress []projectionEvent
	projDone     bool
	projCancel   context.CancelFunc
}

func (s *server) openDB(path string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.store != nil {
		s.store.Close()
	}

	store, err := sqlite.NewSQLiteStore(path)
	if err != nil {
		return err
	}
	s.store = store
	s.dbPath = path
	s.vizSrv = viz.NewServer(store)
	return nil
}

// requireDB wraps a handler that needs an open database.
func (s *server) requireDB(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.RLock()
		hasDB := s.store != nil
		s.mu.RUnlock()
		if !hasDB {
			writeError(w, http.StatusServiceUnavailable, "no database open — use Setup to configure")
			return
		}
		h(w, r)
	}
}

// handleVizProxy delegates to the viz server if DB is open.
func (s *server) handleVizProxy(route string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.RLock()
		v := s.vizSrv
		s.mu.RUnlock()
		if v == nil {
			writeError(w, http.StatusServiceUnavailable, "no database open")
			return
		}
		// Re-dispatch to the viz server's mux.
		mux := http.NewServeMux()
		v.RegisterRoutes(mux)
		mux.ServeHTTP(w, r)
	}
}

type progressEvent struct {
	Time       time.Time `json:"time"`
	FilesDone  int       `json:"files_done"`
	FilesTotal int       `json:"files_total"`
	Skipped    int       `json:"skipped"`
	Positions  int       `json:"positions"`
	Rate       float64   `json:"rate"`
	Elapsed    string    `json:"elapsed"`
	Remaining  string    `json:"remaining"`
	Done       bool      `json:"done"`
	Cancelled  bool      `json:"cancelled,omitempty"`
	Error      string    `json:"error,omitempty"`
}

type projectionEvent struct {
	Time    time.Time `json:"time"`
	Stage   string    `json:"stage"`
	Percent int       `json:"percent"`
	Done    bool      `json:"done"`
	Error   string    `json:"error,omitempty"`
	Message string    `json:"message,omitempty"`
}

// ── Config API ───────────────────────────────────────────────────────────────

type configResponse struct {
	DBPath  string `json:"db_path"`
	BMABDir string `json:"bmab_dir"`
	DataDir string `json:"data_dir"`
	HasDB   bool   `json:"has_db"`
	HasBMAB bool   `json:"has_bmab"`
	HasData bool   `json:"has_data"`
}

func (s *server) handleConfig(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	writeJSON(w, http.StatusOK, configResponse{
		DBPath:  s.dbPath,
		BMABDir: s.bmabDir,
		DataDir: s.dataDir,
		HasDB:   s.store != nil,
		HasBMAB: s.bmabDir != "",
		HasData: s.dataDir != "",
	})
}

func (s *server) handleConfigData(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Path == "" {
		writeError(w, http.StatusBadRequest, "path required")
		return
	}

	absPath, err := filepath.Abs(req.Path)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid path: %v", err))
		return
	}

	info, err := os.Stat(absPath)
	if err != nil || !info.IsDir() {
		writeError(w, http.StatusBadRequest, "directory not found: "+absPath)
		return
	}

	// Validate: expect themes/ and parquet/position_themes/ subdirs
	themeCSV := filepath.Join(absPath, "themes", "theme_frequencies.csv")
	if _, err := os.Stat(themeCSV); err != nil {
		writeError(w, http.StatusBadRequest, "themes/theme_frequencies.csv not found in "+absPath)
		return
	}

	s.mu.Lock()
	s.dataDir = absPath
	s.mu.Unlock()

	// Invalidate theme cache when data dir changes.
	s.themeCacheMu.Lock()
	s.themeCache = nil
	s.themeCacheMu.Unlock()

	s.logger.Printf("data dir changed: %s", absPath)
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "path": absPath})
}

func (s *server) handleConfigDB(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Path == "" {
		writeError(w, http.StatusBadRequest, "path required")
		return
	}

	// Resolve relative to CWD.
	absPath, err := filepath.Abs(req.Path)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid path: %v", err))
		return
	}

	if err := s.openDB(absPath); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("open database: %v", err))
		return
	}

	s.logger.Printf("database changed: %s", absPath)
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "path": absPath})
}

func (s *server) handleConfigBMAB(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Path == "" {
		writeError(w, http.StatusBadRequest, "path required")
		return
	}

	absPath, err := filepath.Abs(req.Path)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid path: %v", err))
		return
	}

	info, err := os.Stat(absPath)
	if err != nil || !info.IsDir() {
		writeError(w, http.StatusBadRequest, "directory not found: "+absPath)
		return
	}

	// Count XG files.
	count, err := countXGFiles(absPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("scan dir: %v", err))
		return
	}

	s.mu.Lock()
	s.bmabDir = absPath
	s.mu.Unlock()

	s.logger.Printf("BMAB dir changed: %s (%d .xg files)", absPath, count)
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok",
		"path":   absPath,
		"files":  count,
	})
}

func (s *server) handleBrowseDir(w http.ResponseWriter, r *http.Request) {
	dir := r.URL.Query().Get("path")
	if dir == "" {
		dir, _ = os.Getwd()
	}
	// mode: "db" = dirs + .db/.sqlite files only; "bmab" = dirs only
	mode := r.URL.Query().Get("mode")

	absDir, err := filepath.Abs(dir)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	entries, err := os.ReadDir(absDir)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("cannot read: %v", err))
		return
	}

	type dirEntry struct {
		Name  string `json:"name"`
		IsDir bool   `json:"is_dir"`
	}

	var items []dirEntry
	// Add parent link.
	parent := filepath.Dir(absDir)
	if parent != absDir {
		items = append(items, dirEntry{Name: "..", IsDir: true})
	}
	const maxEntries = 300
	shown := 0
	truncated := false
	for _, e := range entries {
		isDir := e.IsDir()
		name := e.Name()
		// Skip hidden entries.
		if len(name) > 0 && name[0] == '.' {
			continue
		}
		switch mode {
		case "bmab":
			// Only show directories.
			if !isDir {
				continue
			}
		case "db":
			// Show directories + .db / .sqlite files.
			if !isDir {
				ext := filepath.Ext(name)
				if ext != ".db" && ext != ".sqlite" && ext != ".sqlite3" {
					continue
				}
			}
		}
		if shown >= maxEntries {
			truncated = true
			break
		}
		items = append(items, dirEntry{Name: name, IsDir: isDir})
		shown++
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"path":      absDir,
		"truncated": truncated,
		"entries":   items,
	})
}

type statsResponse struct {
	PositionCount int64               `json:"position_count"`
	MatchCount    int64               `json:"match_count"`
	GameCount     int64               `json:"game_count"`
	MoveCount     int64               `json:"move_count"`
	AnalysisCount int64               `json:"analysis_count"`
	ClassDist     map[string]int      `json:"class_distribution"`
	ScoreDist     []scoreDist         `json:"score_distribution"`
	HasBMAB       bool                `json:"has_bmab"`
	Runs          []gbf.ProjectionRun `json:"projection_runs"`
}

type scoreDist struct {
	AwayX int     `json:"away_x"`
	AwayO int     `json:"away_o"`
	Count int     `json:"count"`
	AvgEq float64 `json:"avg_equity_diff"`
}

func (s *server) handleStats(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	s.mu.RLock()
	store := s.store
	hasBMAB := s.bmabDir != ""
	s.mu.RUnlock()

	db := store.DB()

	resp := statsResponse{
		ClassDist: map[string]int{},
		HasBMAB:   hasBMAB,
	}

	for _, q := range []struct {
		name string
		dest *int64
	}{
		{"SELECT COUNT(*) FROM positions", &resp.PositionCount},
		{"SELECT COUNT(*) FROM matches", &resp.MatchCount},
		{"SELECT COUNT(*) FROM games", &resp.GameCount},
		{"SELECT COUNT(*) FROM moves", &resp.MoveCount},
		{"SELECT COUNT(*) FROM analyses", &resp.AnalysisCount},
	} {
		db.QueryRowContext(ctx, q.name).Scan(q.dest)
	}

	classDist, err := store.QueryPositionClassDistribution(ctx)
	if err == nil {
		classNames := map[int]string{0: "contact", 1: "race", 2: "bearoff"}
		for k, v := range classDist {
			resp.ClassDist[classNames[k]] = v
		}
	}

	sd, err := store.QueryScoreDistribution(ctx)
	if err == nil {
		for _, d := range sd {
			resp.ScoreDist = append(resp.ScoreDist, scoreDist{
				AwayX: d.AwayX, AwayO: d.AwayO,
				Count: d.Count, AvgEq: d.AvgEquityDiff,
			})
		}
	}
	if resp.ScoreDist == nil {
		resp.ScoreDist = []scoreDist{}
	}

	methods := []string{"umap_2d", "pca_2d", "tsne_2d", "umap_3d"}
	for _, m := range methods {
		for lod := 0; lod <= 2; lod++ {
			run, err := store.ActiveProjectionRun(ctx, m, lod)
			if err == nil && run != nil {
				resp.Runs = append(resp.Runs, *run)
			}
		}
	}
	if resp.Runs == nil {
		resp.Runs = []gbf.ProjectionRun{}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (s *server) handleFeatureNames(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, gbf.FeatureNames())
}

type featureSampleResponse struct {
	Names []string    `json:"names"`
	IDs   []int64     `json:"ids"`
	Data  [][]float64 `json:"data"`
}

func (s *server) handleFeatureSample(w http.ResponseWriter, r *http.Request) {
	n := 5000
	if ns := r.URL.Query().Get("n"); ns != "" {
		if v, err := strconv.Atoi(ns); err == nil && v > 0 && v <= 50000 {
			n = v
		}
	}

	ctx := r.Context()
	s.mu.RLock()
	store := s.store
	s.mu.RUnlock()
	db := store.DB()

	var total int64
	db.QueryRowContext(ctx, "SELECT COUNT(*) FROM positions").Scan(&total)
	if total == 0 {
		writeJSON(w, http.StatusOK, featureSampleResponse{
			Names: gbf.FeatureNames(), IDs: []int64{}, Data: [][]float64{},
		})
		return
	}

	var query string
	var args []any
	if total > 100000 {
		step := int(float64(total) / float64(n))
		if step < 1 {
			step = 1
		}
		offset := rand.IntN(step)
		query = fmt.Sprintf(
			"SELECT id, base_record FROM positions WHERE ROWID %% %d = %d LIMIT %d",
			step, offset, n,
		)
	} else {
		query = "SELECT id, base_record FROM positions ORDER BY RANDOM() LIMIT ?"
		args = []any{n}
	}

	rows, err := db.QueryContext(ctx, query, args...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	defer rows.Close()

	resp := featureSampleResponse{Names: gbf.FeatureNames()}
	for rows.Next() {
		var id int64
		var blob []byte
		if err := rows.Scan(&id, &blob); err != nil {
			continue
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			continue
		}
		resp.IDs = append(resp.IDs, id)
		resp.Data = append(resp.Data, gbf.ExtractAllFeatures(*rec))
	}
	writeJSON(w, http.StatusOK, resp)
}

type importRequest struct {
	Proportion float64 `json:"proportion"`
	BatchSize  int     `json:"batch_size"`
}

func (s *server) handleImportStart(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	bmabDir := s.bmabDir
	dbPath := s.dbPath
	s.mu.RUnlock()

	if bmabDir == "" {
		writeError(w, http.StatusBadRequest, "no BMAB directory configured — use Setup tab")
		return
	}

	s.importMu.Lock()
	if s.importRunning {
		s.importMu.Unlock()
		writeError(w, http.StatusConflict, "import already running")
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.importRunning = true
	s.importProgress = nil
	s.importDone = false
	s.importCancel = cancel
	s.importMu.Unlock()

	var req importRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		req.Proportion = 0.01
	}
	if req.Proportion <= 0 || req.Proportion > 1 {
		req.Proportion = 0.01
	}
	if req.BatchSize <= 0 {
		req.BatchSize = 100
	}

	files, err := countXGFiles(bmabDir)
	if err != nil {
		cancel()
		s.importMu.Lock()
		s.importRunning = false
		s.importCancel = nil
		s.importMu.Unlock()
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("scan dir: %v", err))
		return
	}
	limit := int(float64(files) * req.Proportion)
	if limit < 1 {
		limit = 1
	}

	// Journal file lives next to the database so progress survives restarts.
	journalPath := ""
	if dbPath != "" {
		journalPath = dbPath + ".import.journal"
	}

	s.logger.Printf("import: starting %.1f%% (%d/%d files) journal=%s", req.Proportion*100, limit, files, journalPath)

	go s.runImport(ctx, limit, req.BatchSize, files, bmabDir, journalPath)

	writeJSON(w, http.StatusAccepted, map[string]any{
		"message":      "import started",
		"files":        files,
		"limit":        limit,
		"proportion":   req.Proportion,
		"journal_path": journalPath,
	})
}

func (s *server) runImport(ctx context.Context, limit, batchSize, totalFiles int, bmabDir, journalPath string) {
	start := time.Now()

	s.mu.RLock()
	store := s.store
	s.mu.RUnlock()

	opts := gbf.ImportOpts{
		BatchSize:        batchSize,
		Limit:            limit,
		JournalPath:      journalPath,
		ProgressInterval: 50,
		EngineName:       "eXtreme Gammon",
		Logger:           s.logger,
		FileParser: func(path string) (*gbf.Match, error) {
			return convert.ParseXGFile(path)
		},
		ProgressFn: func(p gbf.ProgressEvent) {
			s.importMu.Lock()
			defer s.importMu.Unlock()
			s.importProgress = append(s.importProgress, progressEvent{
				Time:       time.Now(),
				FilesDone:  p.FilesDone,
				FilesTotal: p.FilesTotal,
				Skipped:    p.Skipped,
				Positions:  p.Positions,
				Rate:       p.Rate,
				Elapsed:    p.Elapsed.Round(time.Second).String(),
				Remaining:  p.Remaining.Round(time.Second).String(),
			})
		},
	}

	report, err := gbf.ImportDirectory(ctx, store, bmabDir, opts)

	s.importMu.Lock()
	defer s.importMu.Unlock()

	cancelled := ctx.Err() != nil
	evt := progressEvent{
		Time:       time.Now(),
		FilesDone:  report.FilesImported,
		FilesTotal: totalFiles,
		Skipped:    report.FilesSkipped,
		Positions:  report.Positions,
		Rate:       report.AvgRate,
		Elapsed:    time.Since(start).Round(time.Second).String(),
		Done:       true,
		Cancelled:  cancelled,
	}
	if err != nil && !cancelled {
		evt.Error = err.Error()
	}
	s.importProgress = append(s.importProgress, evt)
	s.importDone = true
	s.importRunning = false
	s.importCancel = nil
}

func (s *server) handleImportProgress(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	cursor := 0
	for {
		s.importMu.Lock()
		events := s.importProgress[cursor:]
		done := s.importDone && !s.importRunning
		s.importMu.Unlock()

		for _, evt := range events {
			data, _ := json.Marshal(evt)
			fmt.Fprintf(w, "data: %s\n\n", data)
			cursor++
		}
		flusher.Flush()

		if done && cursor > 0 {
			return
		}

		select {
		case <-r.Context().Done():
			return
		case <-time.After(500 * time.Millisecond):
		}
	}
}

func countXGFiles(dir string) (int, error) {
	count := 0
	err := filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if !d.IsDir() && filepath.Ext(path) == ".xg" {
			count++
		}
		return nil
	})
	return count, err
}

// handleImportStatus returns whether an import is running/done and the last event.
// Used by the UI to restore state after a tab switch.
func (s *server) handleImportStatus(w http.ResponseWriter, r *http.Request) {
	s.importMu.Lock()
	running := s.importRunning
	done := s.importDone
	count := len(s.importProgress)
	var last *progressEvent
	if count > 0 {
		e := s.importProgress[count-1]
		last = &e
	}
	s.importMu.Unlock()

	s.mu.RLock()
	dbPath := s.dbPath
	s.mu.RUnlock()

	journalPath := ""
	if dbPath != "" {
		journalPath = dbPath + ".import.journal"
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"running":      running,
		"done":         done,
		"event_count":  count,
		"last_event":   last,
		"journal_path": journalPath,
	})
}

// handleImportCancel cancels a running import.
func (s *server) handleImportCancel(w http.ResponseWriter, r *http.Request) {
	s.importMu.Lock()
	cancel := s.importCancel
	s.importMu.Unlock()

	if cancel != nil {
		cancel()
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "cancelled"})
}

// handleProjectionStatus returns whether a projection compute is running/done.
func (s *server) handleProjectionStatus(w http.ResponseWriter, r *http.Request) {
	s.projMu.Lock()
	running := s.projRunning
	done := s.projDone
	count := len(s.projProgress)
	var last *projectionEvent
	if count > 0 {
		e := s.projProgress[count-1]
		last = &e
	}
	s.projMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"running":     running,
		"done":        done,
		"event_count": count,
		"last_event":  last,
	})
}

// handleRebuildTiles rebuilds pre-computed tile data for each active projection
// run whose tiles are missing. This is needed for runs computed with an older
// binary that did not store bounds_json or did not build tiles.
func (s *server) handleRebuildTiles(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	store := s.store
	s.mu.RUnlock()
	if store == nil {
		writeError(w, http.StatusServiceUnavailable, "no database open")
		return
	}

	ctx := r.Context()
	runs, err := store.ListActiveProjectionRuns(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	rebuilt := 0
	skipped := 0
	var errs []string
	for i := range runs {
		run := &runs[i]
		// Check if tiles already exist for this run.
		meta, err := store.QueryTileMeta(ctx, run.ID)
		if err == nil && meta != nil && meta.TileCount > 0 {
			skipped++
			continue
		}
		s.logger.Printf("rebuild-tiles: rebuilding run %d (%s lod=%d, %d pts)", run.ID, run.Method, run.LoD, run.NPoints)
		if err := gbf.RebuildProjectionTiles(ctx, store, run); err != nil {
			s.logger.Printf("rebuild-tiles: run %d failed: %v", run.ID, err)
			errs = append(errs, fmt.Sprintf("run %d: %v", run.ID, err))
		} else {
			rebuilt++
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"rebuilt": rebuilt,
		"skipped": skipped,
		"errors":  errs,
	})
}

// ── Projection Compute API ──────────────────────────────────────────────────

type computeRequest struct {
	Method           string  `json:"method"`             // "pca_2d", "tsne_2d", "umap_2d"
	K                int     `json:"k"`                  // clusters for k-means (0 = use HDBSCAN)
	SampleSize       int     `json:"sample_size"`        // 0 = all positions
	ClusterMethod    string  `json:"cluster_method"`     // "kmeans" or "hdbscan"
	Perplexity       int     `json:"perplexity"`         // t-SNE perplexity (default 30)
	TSNEIter         int     `json:"tsne_iter"`          // t-SNE iterations (default 1000)
	HDBSCANMinSize   int     `json:"hdbscan_min_size"`   // HDBSCAN min cluster size
	HDBSCANMinSample int     `json:"hdbscan_min_sample"` // HDBSCAN min samples
	FeatureIndices   []int   `json:"feature_indices"`    // feature selection (nil = all)
	NNeighbors       int     `json:"n_neighbors"`        // UMAP n_neighbors (default 15)
	UMAPMinDist      float64 `json:"umap_min_dist"`      // UMAP min_dist (default 0.1)
}

func (s *server) handleProjectionCompute(w http.ResponseWriter, r *http.Request) {
	s.projMu.Lock()
	if s.projRunning {
		s.projMu.Unlock()
		writeError(w, http.StatusConflict, "projection computation already running")
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.projRunning = true
	s.projProgress = nil
	s.projDone = false
	s.projCancel = cancel
	s.projMu.Unlock()

	var req computeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		req = computeRequest{}
	}
	if req.Method == "" {
		req.Method = "pca_2d"
	}
	if req.K <= 0 {
		req.K = 8
	}

	s.logger.Printf("projection: starting %s cluster=%s k=%d sample=%d", req.Method, req.ClusterMethod, req.K, req.SampleSize)
	go s.runProjectionCompute(ctx, req)

	writeJSON(w, http.StatusAccepted, map[string]string{
		"status": "started",
		"method": req.Method,
	})
}

func (s *server) runProjectionCompute(ctx context.Context, req computeRequest) {
	defer func() {
		if r := recover(); r != nil {
			s.projMu.Lock()
			s.projProgress = append(s.projProgress, projectionEvent{
				Time:  time.Now(),
				Stage: "error",
				Done:  true,
				Error: fmt.Sprintf("panic: %v", r),
			})
			s.projDone = true
			s.projRunning = false
			s.projCancel = nil
			s.projMu.Unlock()
			s.logger.Printf("projection: panic recovered: %v", r)
		}
	}()

	s.mu.RLock()
	store := s.store
	s.mu.RUnlock()

	cfg := gbf.ProjectionConfig{
		Method:           req.Method,
		K:                req.K,
		SampleSize:       req.SampleSize,
		Seed:             42,
		FeatureVersion:   "v1.0",
		ClusterMethod:    req.ClusterMethod,
		Perplexity:       float64(req.Perplexity),
		TSNEIter:         req.TSNEIter,
		UMAPNeighbors:    req.NNeighbors,
		UMAPMinDist:      req.UMAPMinDist,
		HDBSCANMinSize:   req.HDBSCANMinSize,
		HDBSCANMinSample: req.HDBSCANMinSample,
		FeatureIndices:   req.FeatureIndices,
		ProgressFn: func(stage string, pct int) {
			s.projMu.Lock()
			defer s.projMu.Unlock()
			s.projProgress = append(s.projProgress, projectionEvent{
				Time:    time.Now(),
				Stage:   stage,
				Percent: pct,
			})
		},
	}

	result, err := gbf.ComputeProjectionFromStore(ctx, store, cfg)

	if err != nil {
		s.projMu.Lock()
		s.projProgress = append(s.projProgress, projectionEvent{
			Time:  time.Now(),
			Stage: "error",
			Done:  true,
			Error: err.Error(),
		})
		s.projDone = true
		s.projRunning = false
		s.projCancel = nil
		s.projMu.Unlock()
		return
	}

	if err := gbf.SaveProjectionResult(ctx, store, result, cfg.FeatureVersion); err != nil {
		s.projMu.Lock()
		s.projProgress = append(s.projProgress, projectionEvent{
			Time:  time.Now(),
			Stage: "error",
			Done:  true,
			Error: fmt.Sprintf("save: %v", err),
		})
		s.projDone = true
		s.projRunning = false
		s.projCancel = nil
		s.projMu.Unlock()
		return
	}

	clusterLabel := fmt.Sprintf("k-means (k=%d)", cfg.K)
	if cfg.ClusterMethod == "hdbscan" {
		clusterLabel = "HDBSCAN"
	}

	s.projMu.Lock()
	s.projProgress = append(s.projProgress, projectionEvent{
		Time:    time.Now(),
		Stage:   "done",
		Percent: 100,
		Done:    true,
		Message: fmt.Sprintf("%s + %s complete: %d points", req.Method, clusterLabel, result.NPoints),
	})
	s.projDone = true
	s.projRunning = false
	s.projCancel = nil
	s.projMu.Unlock()

	s.logger.Printf("projection: done — %d points", result.NPoints)
}

func (s *server) handleProjectionProgress(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	cursor := 0
	for {
		s.projMu.Lock()
		events := s.projProgress[cursor:]
		done := s.projDone && !s.projRunning
		s.projMu.Unlock()

		for _, evt := range events {
			data, _ := json.Marshal(evt)
			fmt.Fprintf(w, "data: %s\n\n", data)
			cursor++
		}
		flusher.Flush()

		if done && cursor > 0 {
			return
		}

		select {
		case <-r.Context().Done():
			return
		case <-time.After(500 * time.Millisecond):
		}
	}
}

// ── Static file serving ─────────────────────────────────────────────────────

func serveStaticFS(mux *http.ServeMux, fsys http.FileSystem) {
	fileServer := http.FileServer(fsys)
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		// Try to open the file. If not found, serve index.html (SPA fallback).
		f, err := fsys.Open(r.URL.Path)
		if err != nil {
			// SPA fallback.
			r.URL.Path = "/"
		} else {
			f.Close()
		}
		fileServer.ServeHTTP(w, r)
	})
}

// ── Browser launch ──────────────────────────────────────────────────────────

func openBrowser(url string) {
	time.Sleep(300 * time.Millisecond) // give server a moment to start
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "windows":
		cmd = exec.Command("cmd", "/c", "start", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	cmd.Start()
}

// ── Helpers ──────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// ── Theme API ────────────────────────────────────────────────────────────────

type themeFreqRow struct {
	Theme      string  `json:"theme"`
	Count      int64   `json:"count"`
	Proportion float64 `json:"proportion"`
}

// handleThemeStats reads data/themes/theme_frequencies.csv and returns the rows.
func (s *server) handleThemeStats(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	dataDir := s.dataDir
	s.mu.RUnlock()

	if dataDir == "" {
		writeError(w, http.StatusServiceUnavailable, "data directory not configured — use Setup")
		return
	}

	csvPath := filepath.Join(dataDir, "themes", "theme_frequencies.csv")
	f, err := os.Open(csvPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "cannot open theme_frequencies.csv: "+err.Error())
		return
	}
	defer f.Close()

	rdr := csv.NewReader(f)
	records, err := rdr.ReadAll()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "csv parse error: "+err.Error())
		return
	}

	var rows []themeFreqRow
	for i, rec := range records {
		if i == 0 {
			continue // header
		}
		if len(rec) < 3 {
			continue
		}
		count, _ := strconv.ParseInt(rec[1], 10, 64)
		prop, _ := strconv.ParseFloat(rec[2], 64)
		rows = append(rows, themeFreqRow{Theme: rec[0], Count: count, Proportion: prop})
	}
	if rows == nil {
		rows = []themeFreqRow{}
	}
	writeJSON(w, http.StatusOK, rows)
}

// handleThemePositions returns a sample of board positions for the requested theme.
// It spawns the Python helper script and caches the result per theme.
func (s *server) handleThemePositions(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	dataDir := s.dataDir
	s.mu.RUnlock()

	if dataDir == "" {
		writeError(w, http.StatusServiceUnavailable, "data directory not configured — use Setup")
		return
	}

	theme := r.URL.Query().Get("theme")
	if theme == "" {
		writeError(w, http.StatusBadRequest, "theme query parameter required")
		return
	}

	nStr := r.URL.Query().Get("n")
	n := 24 // default sample size
	if nStr != "" {
		if v, err := strconv.Atoi(nStr); err == nil && v > 0 && v <= 200 {
			n = v
		}
	}

	cacheKey := fmt.Sprintf("%s:%d", theme, n)

	// Check cache first.
	s.themeCacheMu.RLock()
	cached := s.themeCache[cacheKey]
	s.themeCacheMu.RUnlock()

	if cached != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write(cached)
		return
	}

	// Locate the Python helper script relative to the executable or source tree.
	scriptPath := ""
	candidates := []string{
		"scripts/explorer_theme_query.py",
		filepath.Join(filepath.Dir(os.Args[0]), "../../scripts/explorer_theme_query.py"),
		filepath.Join(dataDir, "../scripts/explorer_theme_query.py"),
	}
	for _, c := range candidates {
		if _, err := os.Stat(c); err == nil {
			scriptPath = c
			break
		}
	}
	if scriptPath == "" {
		writeError(w, http.StatusInternalServerError, "explorer_theme_query.py not found")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 120*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "python3", scriptPath, theme, strconv.Itoa(n), dataDir)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		s.logger.Printf("theme query failed (theme=%s): %v — stderr: %s", theme, err, stderr.String())
		writeError(w, http.StatusInternalServerError, "theme query failed: "+err.Error())
		return
	}

	result := stdout.Bytes()

	// Validate JSON before caching.
	if !json.Valid(result) {
		writeError(w, http.StatusInternalServerError, "invalid JSON from theme query: "+string(result))
		return
	}

	// Store in cache.
	s.themeCacheMu.Lock()
	if s.themeCache == nil {
		s.themeCache = make(map[string][]byte)
	}
	s.themeCache[cacheKey] = result
	s.themeCacheMu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(result)
}

func withCORS(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		h.ServeHTTP(w, r)
	})
}
