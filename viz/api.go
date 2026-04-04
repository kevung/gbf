// Package viz provides HTTP handlers for the GBF visualization API.
// Handlers are backend-agnostic — they work with any gbf.Store implementation.
package viz

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

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
	ID         int64              `json:"id"`
	AwayX      int                `json:"away_x"`
	AwayO      int                `json:"away_o"`
	PipX       int                `json:"pip_x"`
	PipO       int                `json:"pip_o"`
	PipDiff    int                `json:"pip_diff"`
	PosClass   int                `json:"pos_class"`
	CubeLog2   int                `json:"cube_log2"`
	CubeOwner  int                `json:"cube_owner"`
	BarX       int                `json:"bar_x"`
	BarO       int                `json:"bar_o"`
	BorneOffX  int                `json:"borne_off_x"`
	BorneOffO  int                `json:"borne_off_o"`
	SideToMove int                `json:"side_to_move"`
	Board      [24]int            `json:"board"`
	Analyses   []analysisResponse `json:"analyses"`
	// Decoded analysis data.
	CheckerAnalysis *checkerAnalysisJSON `json:"checker_analysis,omitempty"`
	CubeAnalysis    *cubeAnalysisJSON    `json:"cube_analysis,omitempty"`
	// Occurrence counts.
	ExactCount int `json:"exact_count"` // this exact position (board+cube+score)
	BoardCount int `json:"board_count"` // same board, any cube/score
	// Match metadata.
	Matches []matchMetaJSON `json:"matches"`
}

type checkerAnalysisJSON struct {
	MoveCount int               `json:"move_count"`
	Moves     []checkerMoveJSON `json:"moves"`
}

type checkerMoveJSON struct {
	Rank       int     `json:"rank"`
	MoveStr    string  `json:"move"`
	Equity     float64 `json:"equity"`
	EquityDiff float64 `json:"equity_diff"`
	WinRate    float64 `json:"win"`
	GammonRate float64 `json:"gammon"`
	BgRate     float64 `json:"bg"`
	OppWinRate float64 `json:"opp_win"`
	OppGamRate float64 `json:"opp_gammon"`
	OppBgRate  float64 `json:"opp_bg"`
	Ply        int     `json:"ply"`
}

type cubeAnalysisJSON struct {
	WinRate    float64 `json:"win"`
	GammonRate float64 `json:"gammon"`
	BgRate     float64 `json:"bg"`
	OppWinRate float64 `json:"opp_win"`
	OppGamRate float64 `json:"opp_gammon"`
	OppBgRate  float64 `json:"opp_bg"`
	CubelessND float64 `json:"cubeless_nd"`
	CubelessD  float64 `json:"cubeless_d"`
	CubefulND  float64 `json:"cubeful_nd"`
	CubefulDT  float64 `json:"cubeful_dt"`
	CubefulDP  float64 `json:"cubeful_dp"`
	BestAction int     `json:"best_action"` // 0=ND, 1=D/T, 2=D/P
	BestLabel  string  `json:"best_label"`
}

type matchMetaJSON struct {
	MatchID     int64  `json:"match_id"`
	Player1     string `json:"player1"`
	Player2     string `json:"player2"`
	MatchLength int    `json:"match_length"`
	Event       string `json:"event"`
	Date        string `json:"date"`
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
	type occurrencer interface {
		PositionOccurrences(ctx context.Context, posID int64, boardHash uint64) (int, int, error)
	}
	type matchMetaer interface {
		PositionMatchMetadata(ctx context.Context, posID int64, limit int) ([]gbf.MatchMetadataRow, error)
	}

	q, ok := s.store.(byIDer)
	if !ok {
		return nil, nil
	}
	pwa, err := q.PositionByID(ctx, id)
	if err != nil {
		return nil, err
	}
	if pwa == nil {
		return nil, nil
	}
	resp := toPositionDetail(pwa)

	// Fetch occurrence counts.
	if occ, ok := s.store.(occurrencer); ok {
		exact, board, err := occ.PositionOccurrences(ctx, id, pwa.BoardHash)
		if err == nil {
			resp.ExactCount = exact
			resp.BoardCount = board
		}
	}

	// Fetch match metadata.
	if mm, ok := s.store.(matchMetaer); ok {
		rows, err := mm.PositionMatchMetadata(ctx, id, 20)
		if err == nil {
			for _, r := range rows {
				resp.Matches = append(resp.Matches, matchMetaJSON{
					MatchID:     r.MatchID,
					Player1:     r.Player1,
					Player2:     r.Player2,
					MatchLength: r.MatchLength,
					Event:       r.Event,
					Date:        r.Date,
				})
			}
		}
	}
	if resp.Matches == nil {
		resp.Matches = []matchMetaJSON{}
	}

	return resp, nil
}

func toPositionDetail(pwa *gbf.PositionWithAnalyses) *positionDetailResponse {
	pos := BaseRecordToBoard(&pwa.BaseRecord)
	resp := &positionDetailResponse{
		ID:         pwa.ID,
		AwayX:      pwa.AwayX,
		AwayO:      pwa.AwayO,
		PipX:       pwa.PipX,
		PipO:       pwa.PipO,
		PipDiff:    pwa.PipDiff,
		PosClass:   pwa.PosClass,
		CubeLog2:   pwa.CubeLog2,
		CubeOwner:  pwa.CubeOwner,
		BarX:       pwa.BarX,
		BarO:       pwa.BarO,
		BorneOffX:  pwa.BorneOffX,
		BorneOffO:  pwa.BorneOffO,
		SideToMove: pwa.SideToMove,
		Board:      pos,
	}
	for _, a := range pwa.Analyses {
		resp.Analyses = append(resp.Analyses, analysisResponse{
			BlockType:  a.BlockType,
			EngineName: a.EngineName,
		})

		switch a.BlockType {
		case gbf.BlockTypeCheckerPlay:
			cpa, err := gbf.UnmarshalCheckerPlayAnalysis(a.Payload)
			if err == nil {
				cj := &checkerAnalysisJSON{MoveCount: int(cpa.MoveCount)}
				for i, m := range cpa.Moves {
					cj.Moves = append(cj.Moves, checkerMoveJSON{
						Rank:       i + 1,
						MoveStr:    formatMoveEncoding(m.Move),
						Equity:     float64(m.Equity) / 10000,
						EquityDiff: float64(m.EquityDiff) / 10000,
						WinRate:    float64(m.WinRate) / 10000,
						GammonRate: float64(m.GammonRate) / 10000,
						BgRate:     float64(m.BackgammonRate) / 10000,
						OppWinRate: float64(m.OppWinRate) / 10000,
						OppGamRate: float64(m.OppGammonRate) / 10000,
						OppBgRate:  float64(m.OppBackgammonRate) / 10000,
						Ply:        int(m.PlyDepth),
					})
				}
				resp.CheckerAnalysis = cj
			}
		case gbf.BlockTypeCubeDecision:
			cda, err := gbf.UnmarshalCubeDecisionAnalysis(a.Payload)
			if err == nil {
				label := "No Double"
				switch cda.BestAction {
				case 1:
					label = "Double / Take"
				case 2:
					label = "Double / Pass"
				}
				resp.CubeAnalysis = &cubeAnalysisJSON{
					WinRate:    float64(cda.WinRate) / 10000,
					GammonRate: float64(cda.GammonRate) / 10000,
					BgRate:     float64(cda.BackgammonRate) / 10000,
					OppWinRate: float64(cda.OppWinRate) / 10000,
					OppGamRate: float64(cda.OppGammonRate) / 10000,
					OppBgRate:  float64(cda.OppBackgammonRate) / 10000,
					CubelessND: float64(cda.CubelessNoDouble) / 10000,
					CubelessD:  float64(cda.CubelessDouble) / 10000,
					CubefulND:  float64(cda.CubefulNoDouble) / 10000,
					CubefulDT:  float64(cda.CubefulDoubleTake) / 10000,
					CubefulDP:  float64(cda.CubefulDoublePass) / 10000,
					BestAction: int(cda.BestAction),
					BestLabel:  label,
				}
			}
		}
	}
	if resp.Analyses == nil {
		resp.Analyses = []analysisResponse{}
	}
	return resp
}

// formatMoveEncoding converts a MoveEncoding to human-readable notation.
func formatMoveEncoding(m gbf.MoveEncoding) string {
	var parts []string
	for _, sub := range m.Submoves {
		if sub[0] == gbf.MoveUnused {
			break
		}
		from := formatPoint(sub[0])
		to := formatPoint(sub[1])
		parts = append(parts, from+"/"+to)
	}
	if len(parts) == 0 {
		return "—"
	}
	return strings.Join(parts, " ")
}

func formatPoint(p uint8) string {
	if p == gbf.MoveFromBar {
		return "bar"
	}
	if p == gbf.MoveToBearOff {
		return "off"
	}
	return strconv.Itoa(int(p) + 1)
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
