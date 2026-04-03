// Command import-projections reads a CSV file of pre-computed projection
// coordinates and imports them into a GBF database as a new projection run.
//
// CSV format (header required):
//
//	position_id,x,y[,z][,cluster_id]
//
// Usage:
//
//	import-projections -db gbf.db -method umap_2d -version v1.0 \
//	    -params '{"n_neighbors":15,"min_dist":0.1}' projections.csv
package main

import (
	"context"
	"encoding/csv"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"strconv"
	"strings"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/sqlite"
)

func main() {
	dbPath := flag.String("db", "gbf.db", "path to SQLite database")
	method := flag.String("method", "umap_2d", "projection method name")
	version := flag.String("version", "v1.0", "feature version string")
	params := flag.String("params", "{}", "JSON parameters of the projection")
	activate := flag.Bool("activate", true, "activate this run after import")
	batchSize := flag.Int("batch", 5000, "insert batch size")
	flag.Parse()

	if flag.NArg() < 1 {
		fmt.Fprintf(os.Stderr, "usage: import-projections [flags] <projections.csv>\n")
		os.Exit(1)
	}
	csvPath := flag.Arg(0)

	store, err := sqlite.NewSQLiteStore(*dbPath)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer store.Close()

	f, err := os.Open(csvPath)
	if err != nil {
		log.Fatalf("open csv: %v", err)
	}
	defer f.Close()

	reader := csv.NewReader(f)
	header, err := reader.Read()
	if err != nil {
		log.Fatalf("read csv header: %v", err)
	}
	colIdx := parseHeader(header)

	ctx := context.Background()

	runID, err := store.CreateProjectionRun(ctx, gbf.ProjectionRun{
		Method:         *method,
		FeatureVersion: *version,
		Params:         *params,
	})
	if err != nil {
		log.Fatalf("create projection run: %v", err)
	}

	var batch []gbf.ProjectionPoint
	total := 0

	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			log.Fatalf("read csv row %d: %v", total+1, err)
		}

		pt, err := parseRow(record, colIdx)
		if err != nil {
			log.Printf("skip row %d: %v", total+1, err)
			continue
		}

		batch = append(batch, pt)
		total++

		if len(batch) >= *batchSize {
			if err := store.BeginBatch(ctx); err != nil {
				log.Fatalf("begin batch: %v", err)
			}
			if err := store.InsertProjectionBatch(ctx, runID, batch); err != nil {
				store.RollbackBatch()
				log.Fatalf("insert batch: %v", err)
			}
			if err := store.CommitBatch(); err != nil {
				log.Fatalf("commit batch: %v", err)
			}
			batch = batch[:0]
		}
	}

	if len(batch) > 0 {
		if err := store.BeginBatch(ctx); err != nil {
			log.Fatalf("begin batch: %v", err)
		}
		if err := store.InsertProjectionBatch(ctx, runID, batch); err != nil {
			store.RollbackBatch()
			log.Fatalf("insert batch: %v", err)
		}
		if err := store.CommitBatch(); err != nil {
			log.Fatalf("commit batch: %v", err)
		}
	}

	db := store.DB()
	if _, err := db.ExecContext(ctx,
		`UPDATE projection_runs SET n_points = ? WHERE id = ?`, total, runID); err != nil {
		log.Printf("warning: update n_points: %v", err)
	}

	if *activate {
		if err := store.ActivateProjectionRun(ctx, runID); err != nil {
			log.Fatalf("activate run: %v", err)
		}
	}

	fmt.Printf("imported %d projection points as run %d (method=%s, version=%s)\n",
		total, runID, *method, *version)
}

type columnIndex struct {
	positionID int
	x          int
	y          int
	z          int // -1 if absent
	clusterID  int // -1 if absent
}

func parseHeader(header []string) columnIndex {
	idx := columnIndex{positionID: -1, x: -1, y: -1, z: -1, clusterID: -1}
	for i, h := range header {
		switch strings.TrimSpace(strings.ToLower(h)) {
		case "position_id":
			idx.positionID = i
		case "x":
			idx.x = i
		case "y":
			idx.y = i
		case "z":
			idx.z = i
		case "cluster_id":
			idx.clusterID = i
		}
	}
	if idx.positionID < 0 || idx.x < 0 || idx.y < 0 {
		log.Fatalf("CSV must have columns: position_id, x, y")
	}
	return idx
}

func parseRow(record []string, idx columnIndex) (gbf.ProjectionPoint, error) {
	var pt gbf.ProjectionPoint

	posID, err := strconv.ParseInt(strings.TrimSpace(record[idx.positionID]), 10, 64)
	if err != nil {
		return pt, fmt.Errorf("position_id: %w", err)
	}
	pt.PositionID = posID

	x, err := strconv.ParseFloat(strings.TrimSpace(record[idx.x]), 32)
	if err != nil {
		return pt, fmt.Errorf("x: %w", err)
	}
	pt.X = float32(x)

	y, err := strconv.ParseFloat(strings.TrimSpace(record[idx.y]), 32)
	if err != nil {
		return pt, fmt.Errorf("y: %w", err)
	}
	pt.Y = float32(y)

	if idx.z >= 0 && idx.z < len(record) && strings.TrimSpace(record[idx.z]) != "" {
		z, err := strconv.ParseFloat(strings.TrimSpace(record[idx.z]), 32)
		if err == nil {
			f32 := float32(z)
			pt.Z = &f32
		}
	}

	if idx.clusterID >= 0 && idx.clusterID < len(record) && strings.TrimSpace(record[idx.clusterID]) != "" {
		cid, err := strconv.Atoi(strings.TrimSpace(record[idx.clusterID]))
		if err == nil {
			pt.ClusterID = &cid
		}
	}

	return pt, nil
}
