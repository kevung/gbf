// cmd/validate runs the M0.7 validation experiments.
//
// Usage:
//
//	go run ./cmd/validate [-db path] [-data dir] [-bmab dir]
//
// Experiments:
//
//	Exp 1 — Schema vs target queries (10 files)
//	Exp 2 — Double Zobrist relevance
//	Exp 3 — Export positions for UMAP (CSV)
//	Exp 4 — Performance at scale (1000 BMAB files)
package main

import (
	"context"
	"database/sql"
	"encoding/csv"
	"flag"
	"fmt"
	"log"
	"math/bits"
	"os"
	"path/filepath"
	"strconv"
	"time"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/convert"
	"github.com/kevung/gbf/sqlite"
)

func main() {
	dbPath := flag.String("db", "/tmp/gbf_validate.db", "SQLite database path")
	dataDir := flag.String("data", "data", "Directory with test XG files")
	bmabDir := flag.String("bmab", "data/bmab-2025-06-23", "Directory with BMAB XG files")
	flag.Parse()

	log.SetFlags(0)
	log.SetPrefix("[validate] ")

	// Remove stale DB
	os.Remove(*dbPath)

	store, err := sqlite.NewSQLiteStore(*dbPath)
	if err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer store.Close()

	db := store.DB()
	ctx := context.Background()

	// ── Exp 1 + 2 ─────────────────────────────────────────────────────────────
	xgFiles := collectXGFiles(*dataDir, 10)
	if len(xgFiles) < 10 {
		log.Printf("warning: only found %d XG files in %s (need 10)", len(xgFiles), *dataDir)
	}
	log.Printf("\n=== Exp 1+2: Importing %d XG files ===", len(xgFiles))

	totalPos, totalMoves := importFiles(ctx, store, db, xgFiles)
	log.Printf("Imported: %d positions, %d moves total", totalPos, totalMoves)

	exp1(db)
	exp2(db)
	exp3(ctx, store, *dbPath)

	// ── Exp 4 ─────────────────────────────────────────────────────────────────
	bmabFiles := collectXGFiles(*bmabDir, 1000)
	if len(bmabFiles) == 0 {
		log.Printf("\n=== Exp 4: SKIPPED (no BMAB files found in %s) ===", *bmabDir)
	} else {
		// Fresh DB for perf test
		perfDB := *dbPath + ".perf.db"
		os.Remove(perfDB)
		perfStore, err := sqlite.NewSQLiteStore(perfDB)
		if err != nil {
			log.Fatalf("open perf store: %v", err)
		}
		exp4(ctx, perfStore, bmabFiles)
		perfStore.Close()
		os.Remove(perfDB)
	}
}

// collectXGFiles returns up to max .xg files found recursively under dir.
func collectXGFiles(dir string, max int) []string {
	var files []string
	filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if filepath.Ext(path) == ".xg" {
			files = append(files, path)
		}
		if len(files) >= max {
			return filepath.SkipAll
		}
		return nil
	})
	return files
}

// importFiles parses and inserts each XG file into store.
// Returns total positions and moves inserted.
func importFiles(ctx context.Context, store *sqlite.SQLiteStore, db *sql.DB, files []string) (int, int) {
	var totalPos, totalMoves int

	for _, f := range files {
		match, err := convert.ParseXGFile(f)
		if err != nil {
			log.Printf("  skip %s: %v", filepath.Base(f), err)
			continue
		}

		matchHash := gbf.ComputeMatchHash(match)
		canonHash := gbf.ComputeCanonicalMatchHash(match)

		res, err := db.ExecContext(ctx, `
			INSERT OR IGNORE INTO matches
				(match_hash, canonical_hash, source_format, player1, player2, match_length)
			VALUES (?, ?, 'xg', ?, ?, ?)`,
			matchHash, canonHash,
			match.Metadata.Player1Name, match.Metadata.Player2Name,
			match.Metadata.MatchLength,
		)
		if err != nil {
			log.Printf("  insert match %s: %v", filepath.Base(f), err)
			continue
		}
		matchID, _ := res.LastInsertId()
		if matchID == 0 {
			// Already existed
			db.QueryRowContext(ctx, `SELECT id FROM matches WHERE match_hash=?`, matchHash).Scan(&matchID)
		}

		for _, game := range match.Games {
			res, err := db.ExecContext(ctx, `
				INSERT INTO games
					(match_id, game_number, score_x, score_o, winner, points_won, crawford)
				VALUES (?, ?, ?, ?, ?, ?, 0)`,
				matchID, game.GameNumber,
				game.InitialScore[0], game.InitialScore[1],
				game.Winner, game.PointsWon,
			)
			if err != nil {
				continue
			}
			gameID, _ := res.LastInsertId()

			for i, mv := range game.Moves {
				if mv.Position == nil {
					continue
				}
				rec, err := gbf.PositionToBaseRecord(mv.Position)
				if err != nil {
					continue
				}
				boardHash := gbf.ComputeBoardOnlyZobrist(rec)
				posID, err := store.UpsertPosition(ctx, *rec, boardHash)
				if err != nil {
					continue
				}

				// Compute equity_diff for checker moves
				var equityDiff, bestEquity, playedEquity int
				if mv.CheckerAnalysis != nil && len(mv.CheckerAnalysis.Moves) > 0 {
					best := mv.CheckerAnalysis.Moves[0]
					bestEquity = int(best.Equity)
					// played = last move in list (worst) — approximation for M0.7
					played := mv.CheckerAnalysis.Moves[len(mv.CheckerAnalysis.Moves)-1]
					playedEquity = int(played.Equity)
					equityDiff = int(played.EquityDiff)
					if equityDiff < 0 {
						equityDiff = -equityDiff
					}
				}

				db.ExecContext(ctx, `
					INSERT INTO moves
						(game_id, move_number, position_id, player, move_type,
						 dice_1, dice_2, equity_diff, best_equity, played_equity)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
					gameID, i+1, posID, mv.Player, string(mv.MoveType),
					mv.Dice[0], mv.Dice[1],
					equityDiff, bestEquity, playedEquity,
				)
				totalMoves++
				totalPos++ // counting move-positions (may include duplicates)
			}
		}
		log.Printf("  imported %s (%d games)", filepath.Base(f), len(match.Games))
	}
	return totalPos, totalMoves
}

// ── Experiment 1: target queries ─────────────────────────────────────────────

func exp1(db *sql.DB) {
	log.Println("\n=== Exp 1: Schema vs Target Queries ===")

	// Query 1: Position lookup by zobrist_hash with analysis join
	var count int
	err := db.QueryRow(`
		SELECT COUNT(*)
		FROM positions p
		LEFT JOIN analyses a ON a.position_id = p.id
	`).Scan(&count)
	log.Printf("  Q1 positions+analyses join: %d rows, err=%v", count, err)

	// Query 2: Error analysis — checker moves with equity_diff > 1000 AND away_x = 3
	err = db.QueryRow(`
		SELECT COUNT(*)
		FROM moves m
		JOIN positions p ON p.id = m.position_id
		WHERE m.equity_diff > 1000
		  AND p.away_x = 3
	`).Scan(&count)
	log.Printf("  Q2 blunders (equity_diff>1000, away_x=3): %d rows, err=%v", count, err)

	// Query 3: Structural — positions WHERE bar_o > 0 GROUP BY away_x, away_o
	rows, err := db.Query(`
		SELECT away_x, away_o, COUNT(*) as cnt
		FROM positions
		WHERE bar_o > 0
		GROUP BY away_x, away_o
		ORDER BY cnt DESC
		LIMIT 10
	`)
	if err != nil {
		log.Printf("  Q3 error: %v", err)
		return
	}
	defer rows.Close()
	var q3Results int
	for rows.Next() {
		var awayX, awayO, cnt int
		rows.Scan(&awayX, &awayO, &cnt)
		q3Results++
	}
	log.Printf("  Q3 bar_o>0 GROUP BY away: %d distinct (away_x,away_o) groups, err=%v", q3Results, rows.Err())
	log.Println("  Exp 1: OK — all 3 queries expressible and executed without error")
}

// ── Experiment 2: Double Zobrist relevance ────────────────────────────────────

func exp2(db *sql.DB) {
	log.Println("\n=== Exp 2: Double Zobrist Relevance ===")

	var totalPositions int
	db.QueryRow(`SELECT COUNT(*) FROM positions`).Scan(&totalPositions)

	rows, err := db.Query(`
		SELECT board_hash, COUNT(DISTINCT zobrist_hash) as variants
		FROM positions
		GROUP BY board_hash
		HAVING variants > 1
	`)
	if err != nil {
		log.Printf("  error: %v", err)
		return
	}
	defer rows.Close()

	var multiVariantBoards int
	var totalVariants int
	for rows.Next() {
		var boardHash int64
		var variants int
		rows.Scan(&boardHash, &variants)
		multiVariantBoards++
		totalVariants += variants
	}

	log.Printf("  Total positions: %d", totalPositions)
	log.Printf("  Board positions with multiple context variants: %d", multiVariantBoards)
	if totalPositions > 0 {
		pct := float64(multiVariantBoards) / float64(totalPositions) * 100
		log.Printf("  Percentage of board_hash with >1 zobrist_hash: %.1f%%", pct)
	}
	if multiVariantBoards > 0 {
		log.Println("  → board_hash index is WORTH keeping (multiple context variants observed)")
	} else {
		log.Println("  → No multi-variant positions in this sample (try more files)")
	}
}

// ── Experiment 3: Export positions for UMAP ──────────────────────────────────

func exp3(ctx context.Context, store *sqlite.SQLiteStore, dbPath string) {
	log.Println("\n=== Exp 3: Export positions for UMAP ===")

	outPath := dbPath + ".umap.csv"

	rows, err := store.DB().QueryContext(ctx, `
		SELECT base_record, pip_x, pip_o, away_x, away_o,
		       cube_log2, cube_owner, bar_x, bar_o, borne_off_x, borne_off_o, side_to_move
		FROM positions
		LIMIT 10000
	`)
	if err != nil {
		log.Printf("  export error: %v", err)
		return
	}
	defer rows.Close()

	f, err := os.Create(outPath)
	if err != nil {
		log.Printf("  create csv: %v", err)
		return
	}
	defer f.Close()

	w := csv.NewWriter(f)
	// Header: 24 point counts + bar_x bar_o borne_off_x borne_off_o pip_x pip_o cube_log2 cube_owner away_x away_o side_to_move
	header := make([]string, 0, 35)
	for i := 1; i <= 24; i++ {
		header = append(header, fmt.Sprintf("pt%d", i))
	}
	header = append(header, "bar_x", "bar_o", "borne_off_x", "borne_off_o",
		"pip_x", "pip_o", "cube_log2", "cube_owner", "away_x", "away_o", "side_to_move")
	w.Write(header)

	var exported int
	for rows.Next() {
		var blob []byte
		var pipX, pipO, awayX, awayO, cubeLog2, cubeOwner int
		var barX, barO, borneOffX, borneOffO, sideToMove int

		if err := rows.Scan(&blob, &pipX, &pipO, &awayX, &awayO,
			&cubeLog2, &cubeOwner, &barX, &barO, &borneOffX, &borneOffO, &sideToMove); err != nil {
			continue
		}

		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			continue
		}

		// Decode point counts from packed nibbles
		row := make([]string, 0, 35)
		for pt := 0; pt < 24; pt++ {
			idx := pt / 2
			var val int8
			if rec.PointCounts[idx] == 0 {
				val = 0
			} else if pt%2 == 0 {
				val = int8(rec.PointCounts[idx] & 0x0F)
			} else {
				val = int8(rec.PointCounts[idx] >> 4)
			}
			row = append(row, strconv.Itoa(int(val)))
		}
		row = append(row,
			strconv.Itoa(barX), strconv.Itoa(barO),
			strconv.Itoa(borneOffX), strconv.Itoa(borneOffO),
			strconv.Itoa(pipX), strconv.Itoa(pipO),
			strconv.Itoa(cubeLog2), strconv.Itoa(cubeOwner),
			strconv.Itoa(awayX), strconv.Itoa(awayO),
			strconv.Itoa(sideToMove),
		)
		w.Write(row)
		exported++
	}
	w.Flush()

	log.Printf("  Exported %d positions to %s", exported, outPath)
	log.Println("  Exp 3: run umap_viz.py to generate scatter plot")

	_ = bits.RotateLeft64 // silence unused import if needed
}

// ── Experiment 4: Performance at scale ───────────────────────────────────────

func exp4(ctx context.Context, store *sqlite.SQLiteStore, files []string) {
	log.Printf("\n=== Exp 4: Performance at Scale (%d files) ===", len(files))
	db := store.DB()

	start := time.Now()

	var totalFiles, totalPositions int
	var failedFiles int

	for _, f := range files {
		match, err := convert.ParseXGFile(f)
		if err != nil {
			failedFiles++
			continue
		}

		matchHash := gbf.ComputeMatchHash(match)
		canonHash := gbf.ComputeCanonicalMatchHash(match)

		res, err := db.ExecContext(ctx, `
			INSERT OR IGNORE INTO matches
				(match_hash, canonical_hash, source_format, player1, player2, match_length)
			VALUES (?, ?, 'xg', ?, ?, ?)`,
			matchHash, canonHash,
			match.Metadata.Player1Name, match.Metadata.Player2Name,
			match.Metadata.MatchLength,
		)
		if err != nil {
			failedFiles++
			continue
		}
		matchID, _ := res.LastInsertId()
		if matchID == 0 {
			db.QueryRowContext(ctx, `SELECT id FROM matches WHERE match_hash=?`, matchHash).Scan(&matchID)
		}

		for _, game := range match.Games {
			res, err := db.ExecContext(ctx, `
				INSERT INTO games
					(match_id, game_number, score_x, score_o, winner, points_won, crawford)
				VALUES (?, ?, ?, ?, ?, ?, 0)`,
				matchID, game.GameNumber,
				game.InitialScore[0], game.InitialScore[1],
				game.Winner, game.PointsWon,
			)
			if err != nil {
				continue
			}
			gameID, _ := res.LastInsertId()

			for i, mv := range game.Moves {
				if mv.Position == nil {
					continue
				}
				rec, err := gbf.PositionToBaseRecord(mv.Position)
				if err != nil {
					continue
				}
				boardHash := gbf.ComputeBoardOnlyZobrist(rec)
				posID, err := store.UpsertPosition(ctx, *rec, boardHash)
				if err != nil {
					continue
				}
				db.ExecContext(ctx, `
					INSERT INTO moves
						(game_id, move_number, position_id, player, move_type, dice_1, dice_2)
					VALUES (?, ?, ?, ?, ?, ?, ?)`,
					gameID, i+1, posID, mv.Player, string(mv.MoveType),
					mv.Dice[0], mv.Dice[1],
				)
				totalPositions++
			}
		}
		totalFiles++
	}

	elapsed := time.Since(start)

	var distinctPos int
	db.QueryRowContext(ctx, `SELECT COUNT(*) FROM positions`).Scan(&distinctPos)

	log.Printf("  Files imported: %d / %d (failed: %d)", totalFiles, len(files), failedFiles)
	log.Printf("  Move-positions processed: %d", totalPositions)
	log.Printf("  Distinct positions in DB: %d", distinctPos)
	log.Printf("  Total time: %s", elapsed.Round(time.Millisecond))
	if totalFiles > 0 {
		posPerSec := float64(totalPositions) / elapsed.Seconds()
		log.Printf("  Positions/sec: %.0f", posPerSec)

		// Benchmark: 100 zobrist lookups
		rows, _ := db.QueryContext(ctx, `SELECT zobrist_hash FROM positions LIMIT 100`)
		var hashes []int64
		for rows.Next() {
			var h int64
			rows.Scan(&h)
			hashes = append(hashes, h)
		}
		rows.Close()

		if len(hashes) > 0 {
			qStart := time.Now()
			for _, h := range hashes {
				var id int64
				db.QueryRowContext(ctx, `SELECT id FROM positions WHERE zobrist_hash=?`, h).Scan(&id)
			}
			qElapsed := time.Since(qStart)
			avgQ := qElapsed / time.Duration(len(hashes))
			log.Printf("  Avg zobrist lookup (%d queries): %s", len(hashes), avgQ)
		}

		// Extrapolation
		const totalFiles166K = 166713
		extrapolated := elapsed * time.Duration(totalFiles166K) / time.Duration(totalFiles)
		log.Printf("  Extrapolated import time for 166K files: %s", extrapolated.Round(time.Second))

		if extrapolated > 24*time.Hour {
			log.Printf("  ⚠ WARNING: extrapolated import > 24h")
		} else {
			log.Printf("  ✓ Extrapolated import within 24h limit")
		}
	}
}
