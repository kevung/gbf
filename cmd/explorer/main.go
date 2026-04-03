// cmd/explorer is a minimal data exploration UI for the GBF database.
//
// It starts an HTTP server that serves:
//   - A Svelte single-page application (from explorer/dist/)
//   - API endpoints for stats, features, projections, and BMAB import
//
// Usage:
//
//	go run ./cmd/explorer -db bmab.db -bmab data/bmab-2025-06-23
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand/v2"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
	"github.com/kevung/gbf/viz"
)

func main() {
	dbPath := "bmab.db"
	bmabDir := ""
	addr := ":8080"
	staticDir := ""

	for i := 1; i < len(os.Args); i++ {
		switch os.Args[i] {
		case "-db":
			i++
			dbPath = os.Args[i]
		case "-bmab":
			i++
			bmabDir = os.Args[i]
		case "-addr":
			i++
			addr = os.Args[i]
		case "-static":
			i++
			staticDir = os.Args[i]
		}
	}

	logger := log.New(os.Stdout, "[explorer] ", log.LstdFlags)

	store, err := sqlite.NewSQLiteStore(dbPath)
	if err != nil {
		logger.Fatalf("open store: %v", err)
	}
	defer store.Close()

	logger.Printf("database: %s", dbPath)
	if bmabDir != "" {
		logger.Printf("BMAB dir: %s", bmabDir)
	}

	srv := &server{
		store:   store,
		bmabDir: bmabDir,
		logger:  logger,
	}

	mux := http.NewServeMux()

	vizSrv := viz.NewServer(store)
	vizSrv.RegisterRoutes(mux)

	mux.HandleFunc("GET /api/stats", srv.handleStats)
	mux.HandleFunc("GET /api/features/names", srv.handleFeatureNames)
	mux.HandleFunc("GET /api/features/sample", srv.handleFeatureSample)
	mux.HandleFunc("POST /api/import/start", srv.handleImportStart)
	mux.HandleFunc("GET /api/import/progress", srv.handleImportProgress)

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
		logger.Printf("static:   %s", staticDir)
		fileServer := http.FileServer(http.Dir(staticDir))
		mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
			path := filepath.Join(staticDir, r.URL.Path)
			if _, err := os.Stat(path); os.IsNotExist(err) && r.URL.Path != "/" {
				http.ServeFile(w, r, filepath.Join(staticDir, "index.html"))
				return
			}
			fileServer.ServeHTTP(w, r)
		})
	}

	logger.Printf("listening on %s", addr)
	logger.Fatal(http.ListenAndServe(addr, withCORS(mux)))
}

type server struct {
	store   *sqlite.SQLiteStore
	bmabDir string
	logger  *log.Logger

	importMu       sync.Mutex
	importRunning  bool
	importProgress []progressEvent
	importDone     bool
}

type progressEvent struct {
	Time       time.Time `json:"time"`
	FilesDone  int       `json:"files_done"`
	FilesTotal int       `json:"files_total"`
	Positions  int       `json:"positions"`
	Rate       float64   `json:"rate"`
	Elapsed    string    `json:"elapsed"`
	Remaining  string    `json:"remaining"`
	Done       bool      `json:"done"`
	Error      string    `json:"error,omitempty"`
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
	db := s.store.DB()

	resp := statsResponse{
		ClassDist: map[string]int{},
		HasBMAB:   s.bmabDir != "",
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

	classDist, err := s.store.QueryPositionClassDistribution(ctx)
	if err == nil {
		classNames := map[int]string{0: "contact", 1: "race", 2: "bearoff"}
		for k, v := range classDist {
			resp.ClassDist[classNames[k]] = v
		}
	}

	sd, err := s.store.QueryScoreDistribution(ctx)
	if err == nil {
		limit := 20
		if len(sd) < limit {
			limit = len(sd)
		}
		for _, d := range sd[:limit] {
			resp.ScoreDist = append(resp.ScoreDist, scoreDist{
				AwayX: d.AwayX, AwayO: d.AwayO,
				Count: d.Count, AvgEq: d.AvgEquityDiff,
			})
		}
	}
	if resp.ScoreDist == nil {
		resp.ScoreDist = []scoreDist{}
	}

	methods := []string{"umap_2d", "pca_2d", "umap_3d"}
	for _, m := range methods {
		run, err := s.store.ActiveProjectionRun(ctx, m)
		if err == nil && run != nil {
			resp.Runs = append(resp.Runs, *run)
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
	db := s.store.DB()

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
	if s.bmabDir == "" {
		writeError(w, http.StatusBadRequest, "no BMAB directory configured (use -bmab flag)")
		return
	}

	s.importMu.Lock()
	if s.importRunning {
		s.importMu.Unlock()
		writeError(w, http.StatusConflict, "import already running")
		return
	}
	s.importRunning = true
	s.importProgress = nil
	s.importDone = false
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

	files, err := countXGFiles(s.bmabDir)
	if err != nil {
		s.importMu.Lock()
		s.importRunning = false
		s.importMu.Unlock()
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("scan dir: %v", err))
		return
	}
	limit := int(float64(files) * req.Proportion)
	if limit < 1 {
		limit = 1
	}

	s.logger.Printf("import: starting %.1f%% (%d/%d files)", req.Proportion*100, limit, files)

	go s.runImport(limit, req.BatchSize, files)

	writeJSON(w, http.StatusAccepted, map[string]any{
		"message":    "import started",
		"files":      files,
		"limit":      limit,
		"proportion": req.Proportion,
	})
}

func (s *server) runImport(limit, batchSize, totalFiles int) {
	ctx := context.Background()
	start := time.Now()

	opts := gbf.ImportOpts{
		BatchSize:        batchSize,
		Limit:            limit,
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
				Positions:  p.Positions,
				Rate:       p.Rate,
				Elapsed:    p.Elapsed.Round(time.Second).String(),
				Remaining:  p.Remaining.Round(time.Second).String(),
			})
		},
	}

	report, err := gbf.ImportDirectory(ctx, s.store, s.bmabDir, opts)

	s.importMu.Lock()
	defer s.importMu.Unlock()

	evt := progressEvent{
		Time:       time.Now(),
		FilesDone:  report.FilesImported,
		FilesTotal: totalFiles,
		Positions:  report.Positions,
		Rate:       report.AvgRate,
		Elapsed:    time.Since(start).Round(time.Second).String(),
		Done:       true,
	}
	if err != nil {
		evt.Error = err.Error()
	}
	s.importProgress = append(s.importProgress, evt)
	s.importDone = true
	s.importRunning = false
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

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
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
