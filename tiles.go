package gbf

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"math"
)

// TilePoint is the compact per-point record written into each pre-computed tile.
// Coordinates are normalised to [0,1]² within the projection's bounding box.
type TilePoint struct {
	ID int64   `json:"id"`
	X  float32 `json:"x"`  // normalised [0,1]
	Y  float32 `json:"y"`  // normalised [0,1]
	C  int     `json:"c"`  // cluster_id (-1 = noise / unassigned)
	PC int     `json:"pc"` // pos_class (0=contact, 1=race, 2=bearoff)
}

// projBounds is the parsed form of ProjectionRun.BoundsJSON.
type projBounds struct {
	MinX float64 `json:"min_x"`
	MaxX float64 `json:"max_x"`
	MinY float64 `json:"min_y"`
	MaxY float64 `json:"max_y"`
}

// LoDZoomRange returns the inclusive [minZoom, maxZoom] zoom range for a LoD level.
//
//	LoD 0 → zoom 0–2 (≤16 tiles, overview)
//	LoD 1 → zoom 3–5 (≤1024 tiles, medium)
//	LoD 2 → zoom 6–8 (≤65536 tiles, full)
func LoDZoomRange(lod int) (minZoom, maxZoom int) {
	switch lod {
	case 0:
		return 0, 2
	case 1:
		return 3, 5
	default: // LoD 2
		return 6, 8
	}
}

// BuildTiles computes pre-computed slippy-map tiles for a completed projection
// run and persists them via the store.
//
// It normalises point coordinates using boundsJSON, bins points into tile cells
// at each zoom level in the LoD's range, gzips the JSON payload, and calls
// InsertTileBatch. After insertion it calls GCProjectionTiles to purge tiles
// belonging to inactive runs.
func BuildTiles(ctx context.Context, store Store, runID int64, lod int, boundsJSON string) error {
	if boundsJSON == "" {
		return fmt.Errorf("bounds_json is empty for run %d", runID)
	}

	var b projBounds
	if err := json.Unmarshal([]byte(boundsJSON), &b); err != nil {
		return fmt.Errorf("parse bounds: %w", err)
	}
	rangeX := b.MaxX - b.MinX
	rangeY := b.MaxY - b.MinY
	if rangeX < 1e-12 {
		rangeX = 1
	}
	if rangeY < 1e-12 {
		rangeY = 1
	}

	rows, err := store.QueryProjectionsByRunID(ctx, runID)
	if err != nil {
		return fmt.Errorf("query projections: %w", err)
	}
	if len(rows) == 0 {
		return nil
	}

	// Pre-compute normalised coordinates and cluster/class data.
	type normPt struct {
		id int64
		nx float32
		ny float32
		c  int
		pc int
	}
	pts := make([]normPt, len(rows))
	for i, r := range rows {
		nx := float32((float64(r.X) - b.MinX) / rangeX)
		ny := float32((float64(r.Y) - b.MinY) / rangeY)
		nx = clampFloat32(nx)
		ny = clampFloat32(ny)
		c := -1
		if r.ClusterID != nil {
			c = *r.ClusterID
		}
		pts[i] = normPt{id: r.PositionID, nx: nx, ny: ny, c: c, pc: r.PosClass}
	}

	minZoom, maxZoom := LoDZoomRange(lod)

	// Collect all tiles across all zoom levels before inserting.
	var allTiles []Tile

	for z := minZoom; z <= maxZoom; z++ {
		size := 1 << uint(z) // number of tiles per axis at this zoom level

		bins := make(map[[2]int][]TilePoint, size)
		for _, pt := range pts {
			tx := int(math.Min(float64(size-1), math.Floor(float64(pt.nx)*float64(size))))
			ty := int(math.Min(float64(size-1), math.Floor(float64(pt.ny)*float64(size))))
			key := [2]int{tx, ty}
			bins[key] = append(bins[key], TilePoint{
				ID: pt.id,
				X:  pt.nx,
				Y:  pt.ny,
				C:  pt.c,
				PC: pt.pc,
			})
		}

		for coord, tpts := range bins {
			data, err := gzipJSON(tpts)
			if err != nil {
				return fmt.Errorf("gzip tile z=%d tx=%d ty=%d: %w", z, coord[0], coord[1], err)
			}
			allTiles = append(allTiles, Tile{
				RunID:   runID,
				Zoom:    z,
				TileX:   coord[0],
				TileY:   coord[1],
				NPoints: len(tpts),
				Data:    data,
			})
		}
	}

	if len(allTiles) == 0 {
		return nil
	}

	// Insert in batches of 500 to avoid overly large transactions.
	const batchSize = 500
	for i := 0; i < len(allTiles); i += batchSize {
		end := i + batchSize
		if end > len(allTiles) {
			end = len(allTiles)
		}
		if err := store.InsertTileBatch(ctx, allTiles[i:end]); err != nil {
			return fmt.Errorf("insert tiles [%d:%d]: %w", i, end, err)
		}
	}

	// Remove tiles that belong to runs no longer active.
	return store.GCProjectionTiles(ctx)
}

// clampFloat32 clamps v to [0,1].
func clampFloat32(v float32) float32 {
	if v < 0 {
		return 0
	}
	if v > 1 {
		return 1
	}
	return v
}

// gzipJSON serialises v to JSON and gzip-compresses the result.
func gzipJSON(v any) ([]byte, error) {
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if err := json.NewEncoder(gz).Encode(v); err != nil {
		gz.Close()
		return nil, err
	}
	if err := gz.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
