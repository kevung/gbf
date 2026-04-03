// Package viz provides HTTP handlers for the GBF visualization API.
// Handlers are backend-agnostic — they work with any gbf.Store implementation.
package viz

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"

	gbf "github.com/kevung/gbf"
)

// Server provides HTTP handlers for visualization endpoints.
type Server struct {
	store gbf.Store
}

// NewServer creates a new visualization API server backed by the given store.
func NewServer(store gbf.Store) *Server {
	return &Server{store: store}
}

// RegisterRoutes registers all viz API routes on the given mux.
// Requires Go 1.22+ for method/path pattern routing.
func (s *Server) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/viz/projection", s.handleProjection)
	mux.HandleFunc("GET /api/viz/clusters", s.handleClusters)
	mux.HandleFunc("GET /api/viz/position/{id}", s.handlePosition)
	mux.HandleFunc("GET /api/viz/runs", s.handleRuns)
}

// ── GET /api/viz/projection ──────────────────────────────────────────────────

type projectionResponse struct {
	Points   []gbf.ProjectionRow  `json:"points"`
	Clusters []gbf.ClusterSummary `json:"clusters,omitempty"`
	Run      *gbf.ProjectionRun   `json:"run,omitempty"`
	Total    int                  `json:"total"`
}

func (s *Server) handleProjection(w http.ResponseWriter, r *http.Request) {
	method := r.URL.Query().Get("method")
	if method == "" {
		method = "umap_2d"
	}

	ctx := r.Context()

	run, err := s.store.ActiveProjectionRun(ctx, method)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if run == nil {
		writeJSON(w, http.StatusOK, projectionResponse{Points: []gbf.ProjectionRow{}})
		return
	}

	f := gbf.ProjectionFilter{
		ClusterID: intQueryParam(r, "cluster_id"),
		AwayX:     intQueryParam(r, "away_x"),
		AwayO:     intQueryParam(r, "away_o"),
		PosClass:  intQueryParam(r, "pos_class"),
		Limit:     intQueryParamDefault(r, "limit", 10000),
		Offset:    intQueryParamDefault(r, "offset", 0),
	}

	points, err := s.store.QueryProjections(ctx, method, f)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if points == nil {
		points = []gbf.ProjectionRow{}
	}

	clusters, _ := s.store.QueryClusterSummary(ctx, method)
	if clusters == nil {
		clusters = []gbf.ClusterSummary{}
	}

	writeJSON(w, http.StatusOK, projectionResponse{
		Points:   points,
		Clusters: clusters,
		Run:      run,
		Total:    len(points),
	})
}

// ── GET /api/viz/clusters ────────────────────────────────────────────────────

func (s *Server) handleClusters(w http.ResponseWriter, r *http.Request) {
	method := r.URL.Query().Get("method")
	if method == "" {
		method = "umap_2d"
	}

	clusters, err := s.store.QueryClusterSummary(r.Context(), method)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if clusters == nil {
		clusters = []gbf.ClusterSummary{}
	}
	writeJSON(w, http.StatusOK, clusters)
}

// ── GET /api/viz/position/{id} ───────────────────────────────────────────────

type positionDetailResponse struct {
	ID        int64              `json:"id"`
	AwayX     int                `json:"away_x"`
	AwayO     int                `json:"away_o"`
	PipX      int                `json:"pip_x"`
	PipO      int                `json:"pip_o"`
	PipDiff   int                `json:"pip_diff"`
	PosClass  int                `json:"pos_class"`
	CubeLog2  int                `json:"cube_log2"`
	CubeOwner int                `json:"cube_owner"`
	BarX      int                `json:"bar_x"`
	BarO      int                `json:"bar_o"`
	BorneOffX int                `json:"borne_off_x"`
	BorneOffO int                `json:"borne_off_o"`
	Board     [24]int            `json:"board"`
	Analyses  []analysisResponse `json:"analyses"`
}

type analysisResponse struct {
	BlockType  uint8  `json:"block_type"`
	EngineName string `json:"engine_name"`
}

func (s *Server) handlePosition(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	posID, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid position id")
		return
	}

	ctx := r.Context()
	positions, err := s.store.QueryByZobrist(ctx, 0)
	_ = positions

	// We need to look up by ID. Use a direct query via the store.
	// Since Store doesn't expose QueryByID, we use QueryByFeatures with
	// a workaround: look up the zobrist hash first.
	detail, err := s.lookupPositionByID(ctx, posID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if detail == nil {
		writeError(w, http.StatusNotFound, "position not found")
		return
	}
	writeJSON(w, http.StatusOK, detail)
}

// lookupPositionByID is implemented by PositionByID on the store if available,
// otherwise returns nil. We extend Store with an optional interface.
func (s *Server) lookupPositionByID(ctx context.Context, id int64) (*positionDetailResponse, error) {
	type byIDer interface {
		PositionByID(ctx context.Context, id int64) (*gbf.PositionWithAnalyses, error)
	}
	if q, ok := s.store.(byIDer); ok {
		pwa, err := q.PositionByID(ctx, id)
		if err != nil {
			return nil, err
		}
		if pwa == nil {
			return nil, nil
		}
		return toPositionDetail(pwa), nil
	}
	return nil, nil
}

func toPositionDetail(pwa *gbf.PositionWithAnalyses) *positionDetailResponse {
	pos := BaseRecordToBoard(&pwa.BaseRecord)
	resp := &positionDetailResponse{
		ID:        pwa.ID,
		AwayX:     pwa.AwayX,
		AwayO:     pwa.AwayO,
		PipX:      pwa.PipX,
		PipO:      pwa.PipO,
		PipDiff:   pwa.PipDiff,
		PosClass:  pwa.PosClass,
		CubeLog2:  pwa.CubeLog2,
		CubeOwner: pwa.CubeOwner,
		BarX:      pwa.BarX,
		BarO:      pwa.BarO,
		BorneOffX: pwa.BorneOffX,
		BorneOffO: pwa.BorneOffO,
		Board:     pos,
	}
	for _, a := range pwa.Analyses {
		resp.Analyses = append(resp.Analyses, analysisResponse{
			BlockType:  a.BlockType,
			EngineName: a.EngineName,
		})
	}
	if resp.Analyses == nil {
		resp.Analyses = []analysisResponse{}
	}
	return resp
}

// BaseRecordToBoard extracts signed point counts from a BaseRecord.
func BaseRecordToBoard(rec *gbf.BaseRecord) [24]int {
	var board [24]int
	for i := 0; i < 24; i++ {
		count := int(rec.PointCounts[i])
		if count == 0 {
			continue
		}
		if rec.LayersX[0]&(1<<uint(i)) != 0 {
			board[i] = count
		} else if rec.LayersO[0]&(1<<uint(i)) != 0 {
			board[i] = -count
		}
	}
	return board
}

// ── GET /api/viz/runs ────────────────────────────────────────────────────────

func (s *Server) handleRuns(w http.ResponseWriter, r *http.Request) {
	// List active runs for known methods.
	methods := []string{"umap_2d", "pca_2d", "umap_3d"}
	var runs []gbf.ProjectionRun
	for _, m := range methods {
		run, err := s.store.ActiveProjectionRun(r.Context(), m)
		if err != nil {
			continue
		}
		if run != nil {
			runs = append(runs, *run)
		}
	}
	if runs == nil {
		runs = []gbf.ProjectionRun{}
	}
	writeJSON(w, http.StatusOK, runs)
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

func intQueryParam(r *http.Request, key string) *int {
	s := r.URL.Query().Get(key)
	if s == "" {
		return nil
	}
	v, err := strconv.Atoi(s)
	if err != nil {
		return nil
	}
	return &v
}

func intQueryParamDefault(r *http.Request, key string, def int) int {
	s := r.URL.Query().Get(key)
	if s == "" {
		return def
	}
	v, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return v
}
