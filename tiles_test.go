package gbf_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/sqlite"
)

// ── Helpers ──────────────────────────────────────────────────────────────────

// openTileStore opens an in-memory SQLite store pre-populated with a small
// projection run that has bounds set appropriately for tile building.
func openTileStore(t *testing.T) (*sqlite.SQLiteStore, int64) {
	t.Helper()
	store, err := sqlite.NewSQLiteStore(":memory:")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })

	ctx := context.Background()

	// Insert a minimal position so projections can have a valid FK.
	var rec gbf.BaseRecord
	rec.Zobrist = 0xdeadbeef
	posID, err := store.UpsertPosition(ctx, rec, 0xaabbccdd)
	if err != nil {
		t.Fatalf("upsert position: %v", err)
	}

	// Create a projection run with explicit bounds.
	run := gbf.ProjectionRun{
		Method:         "umap_2d",
		FeatureVersion: "v1.0",
		Params:         `{}`,
		NPoints:        1,
		LoD:            0,
		BoundsJSON:     `{"min_x":-1.0,"max_x":1.0,"min_y":-1.0,"max_y":1.0}`,
	}
	runID, err := store.CreateProjectionRun(ctx, run)
	if err != nil {
		t.Fatalf("create run: %v", err)
	}

	// Insert a single projection point at (0, 0) → normalised (0.5, 0.5).
	c := 1
	err = store.InsertProjectionBatch(ctx, runID, []gbf.ProjectionPoint{
		{PositionID: posID, X: 0, Y: 0, ClusterID: &c},
	})
	if err != nil {
		t.Fatalf("insert projection: %v", err)
	}

	if err := store.ActivateProjectionRun(ctx, runID); err != nil {
		t.Fatalf("activate run: %v", err)
	}

	return store, runID
}

// ── LoDZoomRange ─────────────────────────────────────────────────────────────

func TestLoDZoomRange(t *testing.T) {
	cases := []struct{ lod, min, max int }{
		{0, 0, 2},
		{1, 3, 5},
		{2, 6, 8},
		{99, 6, 8}, // fallback to LoD 2
	}
	for _, c := range cases {
		min, max := gbf.LoDZoomRange(c.lod)
		if min != c.min || max != c.max {
			t.Errorf("LoDZoomRange(%d) = (%d,%d), want (%d,%d)", c.lod, min, max, c.min, c.max)
		}
	}
}

// ── BuildTiles ───────────────────────────────────────────────────────────────

func TestBuildTiles_Basic(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	const lod = 0
	boundsJSON := `{"min_x":-1.0,"max_x":1.0,"min_y":-1.0,"max_y":1.0}`

	if err := gbf.BuildTiles(ctx, store, runID, lod, boundsJSON); err != nil {
		t.Fatalf("BuildTiles: %v", err)
	}

	meta, err := store.QueryTileMeta(ctx, runID)
	if err != nil {
		t.Fatalf("QueryTileMeta: %v", err)
	}
	if meta == nil {
		t.Fatal("QueryTileMeta returned nil, expected tiles")
	}
	if meta.TileCount == 0 {
		t.Error("expected at least 1 tile")
	}
	if meta.MinZoom != 0 || meta.MaxZoom != 2 {
		t.Errorf("zoom range = [%d,%d], want [0,2]", meta.MinZoom, meta.MaxZoom)
	}
	if meta.NPoints == 0 {
		t.Error("expected n_points > 0 in tile meta")
	}
}

func TestBuildTiles_TileContent(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	boundsJSON := `{"min_x":-1.0,"max_x":1.0,"min_y":-1.0,"max_y":1.0}`
	if err := gbf.BuildTiles(ctx, store, runID, 0, boundsJSON); err != nil {
		t.Fatalf("BuildTiles: %v", err)
	}

	// At zoom=0 there is exactly 1 tile: (0, 0, 0).
	// The single point at normalised (0.5, 0.5) must land there.
	data, err := store.QueryTile(ctx, runID, 0, 0, 0)
	if err != nil {
		t.Fatalf("QueryTile: %v", err)
	}
	if data == nil {
		t.Fatal("expected tile data at zoom=0,x=0,y=0")
	}

	// Decompress and decode.
	gr, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		t.Fatalf("gzip open: %v", err)
	}
	defer gr.Close()

	var pts []gbf.TilePoint
	if err := json.NewDecoder(gr).Decode(&pts); err != nil {
		t.Fatalf("json decode: %v", err)
	}
	if len(pts) != 1 {
		t.Errorf("expected 1 point in tile, got %d", len(pts))
	}
	pt := pts[0]
	if pt.X < 0 || pt.X > 1 || pt.Y < 0 || pt.Y > 1 {
		t.Errorf("tile point coords out of [0,1]: x=%f y=%f", pt.X, pt.Y)
	}
	if pt.C != 1 {
		t.Errorf("cluster_id = %d, want 1", pt.C)
	}
}

func TestBuildTiles_EmptyBounds(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	// Empty bounds_json should return an error.
	err := gbf.BuildTiles(ctx, store, runID, 0, "")
	if err == nil {
		t.Error("expected error for empty bounds_json")
	}
}

func TestQueryTile_NonExistent(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	// No tiles built yet — should return nil, nil.
	data, err := store.QueryTile(ctx, runID, 0, 99, 99)
	if err != nil {
		t.Fatalf("QueryTile: %v", err)
	}
	if data != nil {
		t.Error("expected nil for non-existent tile")
	}
}

func TestQueryTileMeta_NoTiles(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	// No tiles built yet — should return nil, nil.
	meta, err := store.QueryTileMeta(ctx, runID)
	if err != nil {
		t.Fatalf("QueryTileMeta: %v", err)
	}
	if meta != nil {
		t.Errorf("expected nil meta, got %+v", meta)
	}
}

func TestGCProjectionTiles(t *testing.T) {
	store, runID := openTileStore(t)
	ctx := context.Background()

	boundsJSON := `{"min_x":-1.0,"max_x":1.0,"min_y":-1.0,"max_y":1.0}`
	if err := gbf.BuildTiles(ctx, store, runID, 0, boundsJSON); err != nil {
		t.Fatalf("BuildTiles: %v", err)
	}

	// Deactivate the run manually — GC should then remove the tiles.
	db := store.DB()
	if _, err := db.ExecContext(ctx, `UPDATE projection_runs SET is_active=0 WHERE id=?`, runID); err != nil {
		t.Fatalf("deactivate run: %v", err)
	}

	if err := store.GCProjectionTiles(ctx); err != nil {
		t.Fatalf("GCProjectionTiles: %v", err)
	}

	meta, err := store.QueryTileMeta(ctx, runID)
	if err != nil {
		t.Fatalf("QueryTileMeta: %v", err)
	}
	if meta != nil {
		t.Errorf("expected nil meta after GC, got %+v", meta)
	}
}
