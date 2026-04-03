// cmd/export-features imports BMAB positions into SQLite and exports feature
// data for Python visualization notebooks.
//
// Usage:
//
//	export-features [flags] <dir>
//
// Outputs (written to -outdir):
//
//	features.npy    float64 matrix (N, 44) — loadable with numpy.load()
//	metadata.csv    position metadata: id, class, pip_x, pip_o, away_x, away_o, cube, bar
//	difficulty.csv  avg equity_diff per position (from moves table, x10000)
//	players.csv     per-player position counts with name
package main

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/binary"
	"flag"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
)

func main() {
	dbPath := flag.String("db", "data/gbf_m5.db", "SQLite database path")
	outDir := flag.String("outdir", "notebooks/data", "output directory for exported files")
	batch := flag.Int("batch", 500, "files per transaction")
	limit := flag.Int("limit", 10000, "max files to import (0=all)")
	skipImport := flag.Bool("skip-import", false, "skip import step (use existing DB)")
	flag.Parse()

	if flag.NArg() == 0 && !*skipImport {
		fmt.Fprintln(os.Stderr, "usage: export-features [flags] <dir>")
		os.Exit(1)
	}

	logger := log.New(os.Stdout, "[export] ", log.LstdFlags)

	store, err := sqlite.NewSQLiteStore(*dbPath)
	if err != nil {
		logger.Fatalf("open store: %v", err)
	}
	defer store.Close()

	if !*skipImport {
		target := flag.Arg(0)
		logger.Printf("importing from %s (limit=%d, batch=%d)", target, *limit, *batch)
		opts := gbf.ImportOpts{
			BatchSize:        *batch,
			Limit:            *limit,
			MaxErrors:        100,
			ProgressInterval: 1000,
			EngineName:       "eXtreme Gammon",
			Logger:           logger,
			FileParser: func(path string) (*gbf.Match, error) {
				return convert.ParseXGFile(path)
			},
		}
		ctx := context.Background()
		report, err := gbf.ImportDirectory(ctx, store, target, opts)
		if err != nil {
			logger.Fatalf("import: %v", err)
		}
		logger.Printf("import done: %d positions in %s (%.0f pos/s)",
			report.Positions, report.Elapsed.Round(time.Second), report.AvgRate)
	}

	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		logger.Fatalf("mkdir %s: %v", *outDir, err)
	}

	db := store.DB()
	logger.Printf("exporting features...")
	n, err := exportFeatures(db, *outDir)
	if err != nil {
		logger.Fatalf("export features: %v", err)
	}
	logger.Printf("features.npy: %d positions × %d features", n, gbf.NumFeatures)

	logger.Printf("exporting metadata...")
	if err := exportMetadata(db, *outDir, n); err != nil {
		logger.Fatalf("export metadata: %v", err)
	}

	logger.Printf("exporting difficulty...")
	nd, err := exportDifficulty(db, *outDir)
	if err != nil {
		logger.Fatalf("export difficulty: %v", err)
	}
	logger.Printf("difficulty.csv: %d positions with equity_diff", nd)

	logger.Printf("exporting players...")
	np, err := exportPlayers(db, *outDir)
	if err != nil {
		logger.Fatalf("export players: %v", err)
	}
	logger.Printf("players.csv: %d player entries", np)

	logger.Println("done.")
}

// exportFeatures writes features.npy (N × 44 float64) and returns row count.
func exportFeatures(db *sql.DB, outDir string) (int, error) {
	rows, err := db.Query(`SELECT base_record FROM positions ORDER BY id`)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	// First pass: collect all records.
	var recs []gbf.BaseRecord
	for rows.Next() {
		var blob []byte
		if err := rows.Scan(&blob); err != nil {
			return 0, err
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			return 0, fmt.Errorf("unmarshal: %w", err)
		}
		recs = append(recs, *rec)
	}
	if err := rows.Err(); err != nil {
		return 0, err
	}

	npyPath := filepath.Join(outDir, "features.npy")
	if err := gbf.ExportFeaturesNpy(recs, npyPath); err != nil {
		return 0, err
	}
	return len(recs), nil
}

// exportMetadata writes metadata.csv with per-position features for coloring.
func exportMetadata(db *sql.DB, outDir string, _ int) error {
	rows, err := db.Query(`SELECT id, base_record FROM positions ORDER BY id`)
	if err != nil {
		return err
	}
	defer rows.Close()

	path := filepath.Join(outDir, "metadata.csv")
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	w.WriteString("position_id,pos_class,pip_x,pip_o,pip_diff,away_x,away_o,cube_log2,cube_owner,bar_x,bar_o\n")

	for rows.Next() {
		var id int64
		var blob []byte
		if err := rows.Scan(&id, &blob); err != nil {
			return err
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			return err
		}
		cls := gbf.ClassifyPosition(*rec)
		pipDiff := int(rec.PipX) - int(rec.PipO)
		fmt.Fprintf(w, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
			id, cls,
			rec.PipX, rec.PipO, pipDiff,
			rec.AwayX, rec.AwayO,
			rec.CubeLog2, rec.CubeOwner,
			rec.BarX, rec.BarO,
		)
	}
	return w.Flush()
}

// exportDifficulty writes difficulty.csv: position_id, avg_equity_diff (x10000), count.
func exportDifficulty(db *sql.DB, outDir string) (int, error) {
	rows, err := db.Query(`
		SELECT position_id,
		       AVG(CAST(equity_diff AS REAL)) AS avg_diff,
		       COUNT(*) AS cnt
		FROM moves
		WHERE equity_diff IS NOT NULL
		GROUP BY position_id
		ORDER BY position_id`)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	path := filepath.Join(outDir, "difficulty.csv")
	f, err := os.Create(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	w.WriteString("position_id,avg_equity_diff,count\n")

	n := 0
	for rows.Next() {
		var posID int64
		var avgDiff float64
		var cnt int
		if err := rows.Scan(&posID, &avgDiff, &cnt); err != nil {
			return n, err
		}
		fmt.Fprintf(w, "%d,%.4f,%d\n", posID, avgDiff, cnt)
		n++
	}
	return n, w.Flush()
}

// exportPlayers writes players.csv: player, position_count, match_count.
func exportPlayers(db *sql.DB, outDir string) (int, error) {
	// Collect player-level stats by joining matches → games → moves → positions.
	rows, err := db.Query(`
		SELECT m.player1 AS player, COUNT(DISTINCT mv.position_id) AS pos_count,
		       COUNT(DISTINCT m.id) AS match_count
		FROM matches m
		JOIN games g ON g.match_id = m.id
		JOIN moves mv ON mv.game_id = g.id
		WHERE mv.position_id IS NOT NULL AND m.player1 IS NOT NULL
		GROUP BY m.player1
		UNION ALL
		SELECT m.player2 AS player, COUNT(DISTINCT mv.position_id) AS pos_count,
		       COUNT(DISTINCT m.id) AS match_count
		FROM matches m
		JOIN games g ON g.match_id = m.id
		JOIN moves mv ON mv.game_id = g.id
		WHERE mv.position_id IS NOT NULL AND m.player2 IS NOT NULL
		GROUP BY m.player2
		ORDER BY pos_count DESC`)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	path := filepath.Join(outDir, "players.csv")
	f, err := os.Create(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	w.WriteString("player,position_count,match_count\n")

	n := 0
	for rows.Next() {
		var player string
		var posCnt, matchCnt int
		if err := rows.Scan(&player, &posCnt, &matchCnt); err != nil {
			return n, err
		}
		// Escape player name for CSV (replace commas, newlines).
		player = strings.ReplaceAll(player, ",", " ")
		player = strings.ReplaceAll(player, "\n", " ")
		fmt.Fprintf(w, "%s,%d,%d\n", player, posCnt, matchCnt)
		n++
	}
	return n, w.Flush()
}

// writeNpyFloat64 is a helper used only for verifying the format; not called in main path.
func writeNpyFloat64(path string, data []float64) error {
	header := fmt.Sprintf("{'descr': '<f8', 'fortran_order': False, 'shape': (%d,), }", len(data))
	const prefix = 10
	used := prefix + len(header) + 1
	padNeeded := (64 - used%64) % 64
	header += strings.Repeat(" ", padNeeded) + "\n"

	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	w.Write([]byte{0x93, 'N', 'U', 'M', 'P', 'Y', 1, 0})
	var hl [2]byte
	binary.LittleEndian.PutUint16(hl[:], uint16(len(header)))
	w.Write(hl[:])
	w.WriteString(header)
	var buf [8]byte
	for _, v := range data {
		binary.LittleEndian.PutUint64(buf[:], math.Float64bits(v))
		w.Write(buf[:])
	}
	return w.Flush()
}
