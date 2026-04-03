package gbf_test

import (
"context"
"encoding/json"
"fmt"
"net/http"
"net/http/httptest"
"testing"

gbf "github.com/kevung/gbf"
"github.com/kevung/gbf/viz"
)

// ── M8.1: Projection storage round-trip ──────────────────────────────────────

// [U] CreateProjectionRun + InsertProjectionBatch + QueryProjections — round-trip.
func TestProjectionStorageRoundTrip(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

// Insert a position first (projections reference positions).
rec := standardOpeningRecord(t)
boardHash := gbf.ComputeBoardOnlyZobrist(&rec)
posID, err := store.UpsertPosition(ctx, rec, boardHash)
if err != nil {
t.Fatalf("UpsertPosition: %v", err)
}

// Create a projection run.
runID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method:         "umap_2d",
FeatureVersion: "v1.0",
Params:         `{"n_neighbors":15,"min_dist":0.1}`,
})
if err != nil {
t.Fatalf("CreateProjectionRun: %v", err)
}
if runID <= 0 {
t.Fatalf("expected positive runID, got %d", runID)
}

// Activate it.
if err := store.ActivateProjectionRun(ctx, runID); err != nil {
t.Fatalf("ActivateProjectionRun: %v", err)
}

// Insert projection points.
cid := 3
pts := []gbf.ProjectionPoint{
{PositionID: posID, X: 1.5, Y: -0.3, ClusterID: &cid},
}
if err := store.InsertProjectionBatch(ctx, runID, pts); err != nil {
t.Fatalf("InsertProjectionBatch: %v", err)
}

// Query back.
rows, err := store.QueryProjections(ctx, "umap_2d", gbf.ProjectionFilter{})
if err != nil {
t.Fatalf("QueryProjections: %v", err)
}
if len(rows) != 1 {
t.Fatalf("expected 1 projection, got %d", len(rows))
}
if rows[0].PositionID != posID {
t.Errorf("PositionID: got %d, want %d", rows[0].PositionID, posID)
}
if rows[0].X != 1.5 || rows[0].Y != -0.3 {
t.Errorf("coordinates: got (%v, %v), want (1.5, -0.3)", rows[0].X, rows[0].Y)
}
if rows[0].ClusterID == nil || *rows[0].ClusterID != 3 {
t.Errorf("ClusterID: got %v, want 3", rows[0].ClusterID)
}
}

// [U] ActiveProjectionRun — returns nil when no run exists.
func TestActiveProjectionRun_NoRun(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

run, err := store.ActiveProjectionRun(ctx, "umap_2d")
if err != nil {
t.Fatalf("ActiveProjectionRun: %v", err)
}
if run != nil {
t.Fatalf("expected nil, got %+v", run)
}
}

// [U] ActivateProjectionRun — deactivates previous run.
func TestActivateProjectionRun_Deactivation(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

run1ID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method: "umap_2d", FeatureVersion: "v1.0",
})
if err != nil {
t.Fatalf("CreateProjectionRun 1: %v", err)
}
if err := store.ActivateProjectionRun(ctx, run1ID); err != nil {
t.Fatalf("ActivateProjectionRun 1: %v", err)
}

run2ID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method: "umap_2d", FeatureVersion: "v2.0",
})
if err != nil {
t.Fatalf("CreateProjectionRun 2: %v", err)
}
if err := store.ActivateProjectionRun(ctx, run2ID); err != nil {
t.Fatalf("ActivateProjectionRun 2: %v", err)
}

// Only run2 should be active.
active, err := store.ActiveProjectionRun(ctx, "umap_2d")
if err != nil {
t.Fatalf("ActiveProjectionRun: %v", err)
}
if active == nil {
t.Fatal("expected active run, got nil")
}
if active.ID != run2ID {
t.Errorf("active run ID: got %d, want %d", active.ID, run2ID)
}
if active.FeatureVersion != "v2.0" {
t.Errorf("active version: got %s, want v2.0", active.FeatureVersion)
}
}

// [U] QueryClusterSummary — returns counts and centroids.
func TestQueryClusterSummary(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

// Insert 3 positions.
var posIDs []int64
for i := 0; i < 3; i++ {
rec := variantRecord(t, i+5, i, i)
boardHash := gbf.ComputeBoardOnlyZobrist(&rec)
id, err := store.UpsertPosition(ctx, rec, boardHash)
if err != nil {
t.Fatalf("UpsertPosition[%d]: %v", i, err)
}
posIDs = append(posIDs, id)
}

runID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method: "umap_2d", FeatureVersion: "v1.0",
})
store.ActivateProjectionRun(ctx, runID)

c0, c1 := 0, 1
pts := []gbf.ProjectionPoint{
{PositionID: posIDs[0], X: 1.0, Y: 2.0, ClusterID: &c0},
{PositionID: posIDs[1], X: 3.0, Y: 4.0, ClusterID: &c0},
{PositionID: posIDs[2], X: 10.0, Y: 20.0, ClusterID: &c1},
}
store.InsertProjectionBatch(ctx, runID, pts)

clusters, err := store.QueryClusterSummary(ctx, "umap_2d")
if err != nil {
t.Fatalf("QueryClusterSummary: %v", err)
}
if len(clusters) != 2 {
t.Fatalf("expected 2 clusters, got %d", len(clusters))
}
if clusters[0].Count != 2 {
t.Errorf("cluster 0 count: got %d, want 2", clusters[0].Count)
}
if clusters[1].Count != 1 {
t.Errorf("cluster 1 count: got %d, want 1", clusters[1].Count)
}
}

// [U] QueryProjections — filtered by cluster_id.
func TestQueryProjections_FilteredByCluster(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

var posIDs []int64
for i := 0; i < 3; i++ {
rec := variantRecord(t, i+5, i, i)
id, _ := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
posIDs = append(posIDs, id)
}

runID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method: "umap_2d", FeatureVersion: "v1.0",
})
store.ActivateProjectionRun(ctx, runID)

c0, c1 := 0, 1
pts := []gbf.ProjectionPoint{
{PositionID: posIDs[0], X: 1.0, Y: 2.0, ClusterID: &c0},
{PositionID: posIDs[1], X: 3.0, Y: 4.0, ClusterID: &c1},
{PositionID: posIDs[2], X: 5.0, Y: 6.0, ClusterID: &c0},
}
store.InsertProjectionBatch(ctx, runID, pts)

cluster0 := 0
rows, err := store.QueryProjections(ctx, "umap_2d", gbf.ProjectionFilter{ClusterID: &cluster0})
if err != nil {
t.Fatalf("QueryProjections: %v", err)
}
if len(rows) != 2 {
t.Fatalf("expected 2 points in cluster 0, got %d", len(rows))
}
}

// ── M8.2: HTTP API ───────────────────────────────────────────────────────────

func setupVizServer(t *testing.T) (*viz.Server, *httptest.Server) {
t.Helper()
store := openSQLiteStore(t)
ctx := context.Background()

// Populate with positions and projections.
var posIDs []int64
for i := 0; i < 5; i++ {
rec := variantRecord(t, i+5, i, i)
id, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
if err != nil {
t.Fatalf("UpsertPosition[%d]: %v", i, err)
}
posIDs = append(posIDs, id)
}

runID, _ := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
Method: "umap_2d", FeatureVersion: "v1.0", Params: `{"n_neighbors":15}`,
})
store.ActivateProjectionRun(ctx, runID)

c0, c1 := 0, 1
for i, pid := range posIDs {
cid := &c0
if i >= 3 {
cid = &c1
}
pts := []gbf.ProjectionPoint{
{PositionID: pid, X: float32(i) * 1.5, Y: float32(i) * -0.5, ClusterID: cid},
}
store.InsertProjectionBatch(ctx, runID, pts)
}

srv := viz.NewServer(store)
mux := http.NewServeMux()
srv.RegisterRoutes(mux)
ts := httptest.NewServer(mux)
t.Cleanup(ts.Close)
return srv, ts
}

// [U] GET /api/viz/projection — default response with points and clusters.
func TestAPIProjection_Default(t *testing.T) {
_, ts := setupVizServer(t)

resp, err := http.Get(ts.URL + "/api/viz/projection")
if err != nil {
t.Fatalf("GET /api/viz/projection: %v", err)
}
defer resp.Body.Close()

if resp.StatusCode != http.StatusOK {
t.Fatalf("status: %d", resp.StatusCode)
}
if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
t.Errorf("Content-Type: %s", ct)
}

var body struct {
Points   []json.RawMessage `json:"points"`
Clusters []json.RawMessage `json:"clusters"`
Total    int               `json:"total"`
Run      *struct {
Method string `json:"Method"`
} `json:"run"`
}
if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
t.Fatalf("decode: %v", err)
}
if body.Total != 5 {
t.Errorf("total: got %d, want 5", body.Total)
}
if len(body.Points) != 5 {
t.Errorf("points: got %d, want 5", len(body.Points))
}
if len(body.Clusters) != 2 {
t.Errorf("clusters: got %d, want 2", len(body.Clusters))
}
if body.Run == nil || body.Run.Method != "umap_2d" {
t.Errorf("run method missing or wrong")
}
}

// [U] GET /api/viz/projection?cluster_id=0 — filtered by cluster.
func TestAPIProjection_FilteredByCluster(t *testing.T) {
_, ts := setupVizServer(t)

resp, err := http.Get(ts.URL + "/api/viz/projection?cluster_id=0")
if err != nil {
t.Fatalf("GET: %v", err)
}
defer resp.Body.Close()

var body struct {
Total int `json:"total"`
}
json.NewDecoder(resp.Body).Decode(&body)
if body.Total != 3 {
t.Errorf("expected 3 points for cluster 0, got %d", body.Total)
}
}

// [U] GET /api/viz/projection with no active run — returns empty.
func TestAPIProjection_NoActiveRun(t *testing.T) {
store := openSQLiteStore(t)
srv := viz.NewServer(store)
mux := http.NewServeMux()
srv.RegisterRoutes(mux)
ts := httptest.NewServer(mux)
defer ts.Close()

resp, err := http.Get(ts.URL + "/api/viz/projection")
if err != nil {
t.Fatalf("GET: %v", err)
}
defer resp.Body.Close()

var body struct {
Total int `json:"total"`
}
json.NewDecoder(resp.Body).Decode(&body)
if body.Total != 0 {
t.Errorf("expected 0 points, got %d", body.Total)
}
}

// [U] GET /api/viz/clusters — returns cluster summaries.
func TestAPIClusters(t *testing.T) {
_, ts := setupVizServer(t)

resp, err := http.Get(ts.URL + "/api/viz/clusters")
if err != nil {
t.Fatalf("GET: %v", err)
}
defer resp.Body.Close()

var clusters []gbf.ClusterSummary
json.NewDecoder(resp.Body).Decode(&clusters)
if len(clusters) != 2 {
t.Errorf("expected 2 clusters, got %d", len(clusters))
}
}

// [U] GET /api/viz/position/{id} — drill-down to position detail.
func TestAPIPositionDetail(t *testing.T) {
store := openSQLiteStore(t)
ctx := context.Background()

rec := standardOpeningRecord(t)
posID, _ := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
store.AddAnalysis(ctx, posID, 1, "gnubg", []byte{0x42})

srv := viz.NewServer(store)
mux := http.NewServeMux()
srv.RegisterRoutes(mux)
ts := httptest.NewServer(mux)
defer ts.Close()

resp, err := http.Get(fmt.Sprintf("%s/api/viz/position/%d", ts.URL, posID))
if err != nil {
t.Fatalf("GET: %v", err)
}
defer resp.Body.Close()

if resp.StatusCode != http.StatusOK {
t.Fatalf("status: %d", resp.StatusCode)
}

var detail map[string]any
json.NewDecoder(resp.Body).Decode(&detail)
if int64(detail["id"].(float64)) != posID {
t.Errorf("position id mismatch")
}
if analyses, ok := detail["analyses"].([]any); !ok || len(analyses) != 1 {
t.Errorf("expected 1 analysis, got %v", detail["analyses"])
}
}

// [U] GET /api/viz/runs — lists active projection runs.
func TestAPIRuns(t *testing.T) {
_, ts := setupVizServer(t)

resp, err := http.Get(ts.URL + "/api/viz/runs")
if err != nil {
t.Fatalf("GET: %v", err)
}
defer resp.Body.Close()

var runs []gbf.ProjectionRun
json.NewDecoder(resp.Body).Decode(&runs)
if len(runs) != 1 {
t.Fatalf("expected 1 active run, got %d", len(runs))
}
if runs[0].Method != "umap_2d" {
t.Errorf("method: got %s, want umap_2d", runs[0].Method)
}
}

// ── Helper ──────────────────────────────────────────────────────────────────

func variantRecord(t testing.TB, matchLength, awayX, awayO int) gbf.BaseRecord {
t.Helper()
pos := &gbf.PositionState{
CubeValue:   1,
CubeOwner:   gbf.CubeCenter,
MatchLength: matchLength,
AwayX:       awayX,
AwayO:       awayO,
}
pos.Board[23] = 2
pos.Board[12] = 5
pos.Board[7] = 3
pos.Board[5] = 5
pos.Board[0] = -2
pos.Board[11] = -5
pos.Board[16] = -3
pos.Board[18] = -5

rec, err := gbf.PositionToBaseRecord(pos)
if err != nil {
t.Fatalf("PositionToBaseRecord: %v", err)
}
return *rec
}
