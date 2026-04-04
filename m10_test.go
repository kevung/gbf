package gbf_test

// M10.3 — LoD system tests.

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/viz"
)

// ── M10.3a: Schema — lod and bounds_json columns exist ───────────────────────

// [U] ProjectionRun stores and retrieves lod and bounds_json.
func TestProjectionRunLoDRoundTrip(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Insert a position so projection points can reference it.
	rec := standardOpeningRecord(t)
	posID, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	// Create a LoD 0 run.
	runID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method:         "umap_2d",
		FeatureVersion: "v1.0",
		Params:         `{"n":5000}`,
		LoD:            0,
		BoundsJSON:     `{"min_x":-3.5,"max_x":4.2,"min_y":-2.1,"max_y":5.0}`,
	})
	if err != nil {
		t.Fatalf("CreateProjectionRun: %v", err)
	}
	if err := store.ActivateProjectionRun(ctx, runID); err != nil {
		t.Fatalf("ActivateProjectionRun: %v", err)
	}

	cid := 1
	if err := store.InsertProjectionBatch(ctx, runID, []gbf.ProjectionPoint{
		{PositionID: posID, X: 1.0, Y: 2.0, ClusterID: &cid},
	}); err != nil {
		t.Fatalf("InsertProjectionBatch: %v", err)
	}

	// Retrieve and verify.
	run, err := store.ActiveProjectionRun(ctx, "umap_2d", 0)
	if err != nil {
		t.Fatalf("ActiveProjectionRun: %v", err)
	}
	if run == nil {
		t.Fatal("expected active run, got nil")
	}
	if run.LoD != 0 {
		t.Errorf("LoD: got %d, want 0", run.LoD)
	}
	if run.BoundsJSON == "" {
		t.Error("BoundsJSON is empty")
	}
	var bounds struct {
		MinX float64 `json:"min_x"`
		MaxX float64 `json:"max_x"`
		MinY float64 `json:"min_y"`
		MaxY float64 `json:"max_y"`
	}
	if err := json.Unmarshal([]byte(run.BoundsJSON), &bounds); err != nil {
		t.Fatalf("parse BoundsJSON: %v", err)
	}
	if bounds.MinX != -3.5 || bounds.MaxX != 4.2 {
		t.Errorf("bounds x: got [%.1f, %.1f], want [-3.5, 4.2]", bounds.MinX, bounds.MaxX)
	}
}

// ── M10.3d: Activation per (method, lod) ─────────────────────────────────────

// [U] Two LoD levels can be active simultaneously for the same method.
func TestLoDActivationIndependent(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Create and activate LoD 0 run.
	run0ID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 0,
	})
	if err != nil {
		t.Fatalf("CreateProjectionRun lod=0: %v", err)
	}
	if err := store.ActivateProjectionRun(ctx, run0ID); err != nil {
		t.Fatalf("ActivateProjectionRun lod=0: %v", err)
	}

	// Create and activate LoD 1 run.
	run1ID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 1,
	})
	if err != nil {
		t.Fatalf("CreateProjectionRun lod=1: %v", err)
	}
	if err := store.ActivateProjectionRun(ctx, run1ID); err != nil {
		t.Fatalf("ActivateProjectionRun lod=1: %v", err)
	}

	// Both should be independently active.
	active0, err := store.ActiveProjectionRun(ctx, "umap_2d", 0)
	if err != nil {
		t.Fatalf("ActiveProjectionRun lod=0: %v", err)
	}
	if active0 == nil || active0.ID != run0ID {
		t.Errorf("lod=0 active run: got %v, want id=%d", active0, run0ID)
	}

	active1, err := store.ActiveProjectionRun(ctx, "umap_2d", 1)
	if err != nil {
		t.Fatalf("ActiveProjectionRun lod=1: %v", err)
	}
	if active1 == nil || active1.ID != run1ID {
		t.Errorf("lod=1 active run: got %v, want id=%d", active1, run1ID)
	}

	// LoD 2 has no active run.
	active2, err := store.ActiveProjectionRun(ctx, "umap_2d", 2)
	if err != nil {
		t.Fatalf("ActiveProjectionRun lod=2: %v", err)
	}
	if active2 != nil {
		t.Errorf("lod=2: expected nil, got %+v", active2)
	}
}

// [U] Re-activating same lod replaces previous run for that lod only.
func TestLoDActivationReplacesSameLod(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Two runs for lod=0.
	run0aID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 0,
	})
	store.ActivateProjectionRun(ctx, run0aID)

	run0bID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.1", LoD: 0,
	})
	store.ActivateProjectionRun(ctx, run0bID)

	// Also a lod=1 run.
	run1ID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 1,
	})
	store.ActivateProjectionRun(ctx, run1ID)

	// lod=0 should now point to run0b.
	active0, err := store.ActiveProjectionRun(ctx, "umap_2d", 0)
	if err != nil {
		t.Fatalf("ActiveProjectionRun lod=0: %v", err)
	}
	if active0 == nil || active0.ID != run0bID {
		t.Errorf("lod=0 active: got %v, want id=%d", active0, run0bID)
	}

	// lod=1 should be untouched.
	active1, err := store.ActiveProjectionRun(ctx, "umap_2d", 1)
	if err != nil {
		t.Fatalf("ActiveProjectionRun lod=1: %v", err)
	}
	if active1 == nil || active1.ID != run1ID {
		t.Errorf("lod=1 active: got %v, want id=%d", active1, run1ID)
	}
}

// [U] ListActiveProjectionRuns returns all active runs ordered by method, lod.
func TestListActiveProjectionRuns(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	for _, cfg := range []struct {
		method string
		lod    int
	}{
		{"pca_2d", 0},
		{"umap_2d", 0},
		{"umap_2d", 1},
	} {
		id, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
			Method: cfg.method, FeatureVersion: "v1.0", LoD: cfg.lod,
		})
		if err != nil {
			t.Fatalf("CreateProjectionRun (%s, lod=%d): %v", cfg.method, cfg.lod, err)
		}
		if err := store.ActivateProjectionRun(ctx, id); err != nil {
			t.Fatalf("ActivateProjectionRun: %v", err)
		}
	}

	runs, err := store.ListActiveProjectionRuns(ctx)
	if err != nil {
		t.Fatalf("ListActiveProjectionRuns: %v", err)
	}
	if len(runs) != 3 {
		t.Fatalf("expected 3 active runs, got %d", len(runs))
	}
	// Ordered by method, lod.
	if runs[0].Method != "pca_2d" || runs[0].LoD != 0 {
		t.Errorf("run[0]: got (%s, lod=%d), want (pca_2d, 0)", runs[0].Method, runs[0].LoD)
	}
	if runs[1].Method != "umap_2d" || runs[1].LoD != 0 {
		t.Errorf("run[1]: got (%s, lod=%d), want (umap_2d, 0)", runs[1].Method, runs[1].LoD)
	}
	if runs[2].Method != "umap_2d" || runs[2].LoD != 2 {
		// LoD 1 was activated, expect lod=1.
		if runs[2].LoD != 1 {
			t.Errorf("run[2]: got (%s, lod=%d), want (umap_2d, 1)", runs[2].Method, runs[2].LoD)
		}
	}
}

// ── M10.3b: Stratified sampling ──────────────────────────────────────────────

// [U] ExportStratifiedFeatures — returns proportional sample when sampleSize < total.
func TestExportStratifiedFeatures(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Insert 9 distinct positions.
	for i := 0; i < 9; i++ {
		rec := variantRecord(t, i+1, i%3, (i+1)%3)
		if _, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec)); err != nil {
			t.Fatalf("UpsertPosition[%d]: %v", i, err)
		}
	}

	// Request 6 samples from 9 total.
	ids, features, err := store.ExportStratifiedFeatures(ctx, 6, 42)
	if err != nil {
		t.Fatalf("ExportStratifiedFeatures: %v", err)
	}
	if len(ids) == 0 {
		t.Fatal("expected samples, got 0")
	}
	if len(ids) != len(features) {
		t.Errorf("ids/features length mismatch: %d vs %d", len(ids), len(features))
	}
	// Should have sampled fewer than total (9).
	if len(ids) >= 9 {
		t.Errorf("sampling did not reduce count: got %d, want < 9", len(ids))
	}
	// Each feature vector should be 44-dimensional.
	if len(features[0]) != 44 {
		t.Errorf("feature dimension: got %d, want 44", len(features[0]))
	}
}

// [U] ExportStratifiedFeatures with sampleSize=0 returns all positions.
func TestExportStratifiedFeatures_AllWhenZeroSize(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		rec := variantRecord(t, i+5, i, i)
		store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
	}

	ids, features, err := store.ExportStratifiedFeatures(ctx, 0, 42)
	if err != nil {
		t.Fatalf("ExportStratifiedFeatures: %v", err)
	}
	if len(ids) != 5 {
		t.Errorf("expected 5 positions, got %d", len(ids))
	}
	if len(features) != 5 {
		t.Errorf("expected 5 feature vectors, got %d", len(features))
	}
}

// ── M10.3e: API — lod query param ────────────────────────────────────────────

// [U] GET /api/viz/projection?lod=0 — returns LoD 0 run points.
func TestAPIProjection_LoDParam(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Insert positions and create two runs: lod=0 (3 pts) and lod=1 (2 pts).
	var posIDs []int64
	for i := 0; i < 5; i++ {
		rec := variantRecord(t, i+1, i, i)
		id, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
		if err != nil {
			t.Fatalf("UpsertPosition[%d]: %v", i, err)
		}
		posIDs = append(posIDs, id)
	}

	// LoD 0 run — 3 points.
	run0ID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 0,
		BoundsJSON: `{"min_x":-1,"max_x":1,"min_y":-1,"max_y":1}`,
	})
	store.ActivateProjectionRun(ctx, run0ID)
	cid0 := 0
	store.InsertProjectionBatch(ctx, run0ID, []gbf.ProjectionPoint{
		{PositionID: posIDs[0], X: 0.1, Y: 0.2, ClusterID: &cid0},
		{PositionID: posIDs[1], X: 0.3, Y: 0.4, ClusterID: &cid0},
		{PositionID: posIDs[2], X: 0.5, Y: 0.6, ClusterID: &cid0},
	})

	// LoD 1 run — 2 points.
	run1ID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method: "umap_2d", FeatureVersion: "v1.0", LoD: 1,
	})
	store.ActivateProjectionRun(ctx, run1ID)
	cid1 := 1
	store.InsertProjectionBatch(ctx, run1ID, []gbf.ProjectionPoint{
		{PositionID: posIDs[3], X: 1.0, Y: 2.0, ClusterID: &cid1},
		{PositionID: posIDs[4], X: 3.0, Y: 4.0, ClusterID: &cid1},
	})

	srv := viz.NewServer(store)
	mux := http.NewServeMux()
	srv.RegisterRoutes(mux)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)

	// Query lod=0: expect 3 points.
	resp0, err := http.Get(ts.URL + "/api/viz/projection?lod=0")
	if err != nil {
		t.Fatalf("GET lod=0: %v", err)
	}
	defer resp0.Body.Close()
	var body0 struct {
		Points []interface{} `json:"points"`
		Total  int           `json:"total"`
		Run    *struct {
			LoD int `json:"lod"`
		} `json:"run"`
	}
	if err := json.NewDecoder(resp0.Body).Decode(&body0); err != nil {
		t.Fatalf("decode lod=0: %v", err)
	}
	if body0.Total != 3 {
		t.Errorf("lod=0 total: got %d, want 3", body0.Total)
	}
	if body0.Run == nil || body0.Run.LoD != 0 {
		t.Errorf("lod=0 run.lod: got %v, want 0", body0.Run)
	}

	// Query lod=1: expect 2 points.
	resp1, err := http.Get(ts.URL + "/api/viz/projection?lod=1")
	if err != nil {
		t.Fatalf("GET lod=1: %v", err)
	}
	defer resp1.Body.Close()
	var body1 struct {
		Points []interface{} `json:"points"`
		Total  int           `json:"total"`
	}
	if err := json.NewDecoder(resp1.Body).Decode(&body1); err != nil {
		t.Fatalf("decode lod=1: %v", err)
	}
	if body1.Total != 2 {
		t.Errorf("lod=1 total: got %d, want 2", body1.Total)
	}

	// Query lod=2: no active run → empty result.
	resp2, err := http.Get(ts.URL + "/api/viz/projection?lod=2")
	if err != nil {
		t.Fatalf("GET lod=2: %v", err)
	}
	defer resp2.Body.Close()
	var body2 struct {
		Points []interface{} `json:"points"`
		Total  int           `json:"total"`
	}
	if err := json.NewDecoder(resp2.Body).Decode(&body2); err != nil {
		t.Fatalf("decode lod=2: %v", err)
	}
	if body2.Total != 0 {
		t.Errorf("lod=2 total: got %d, want 0", body2.Total)
	}
}

// [U] GET /api/viz/runs — returns all active runs with lod field.
func TestAPIRuns_LoDField(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	for _, cfg := range []struct {
		method string
		lod    int
	}{
		{"umap_2d", 0},
		{"umap_2d", 1},
		{"pca_2d", 0},
	} {
		id, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
			Method: cfg.method, FeatureVersion: "v1.0", LoD: cfg.lod,
		})
		store.ActivateProjectionRun(ctx, id)
	}

	srv := viz.NewServer(store)
	mux := http.NewServeMux()
	srv.RegisterRoutes(mux)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)

	resp, err := http.Get(ts.URL + "/api/viz/runs")
	if err != nil {
		t.Fatalf("GET /api/viz/runs: %v", err)
	}
	defer resp.Body.Close()

	var runs []struct {
		Method string `json:"Method"` // exported field names from ProjectionRun
		LoD    int    `json:"lod"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&runs); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(runs) != 3 {
		t.Fatalf("expected 3 runs, got %d", len(runs))
	}

	// Ensure lod field is present.
	lodSeen := map[int]int{}
	for _, r := range runs {
		lodSeen[r.LoD]++
	}
	if lodSeen[0] != 2 {
		t.Errorf("expected 2 lod=0 runs, got %d", lodSeen[0])
	}
	if lodSeen[1] != 1 {
		t.Errorf("expected 1 lod=1 run, got %d", lodSeen[1])
	}
}
