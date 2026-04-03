// cmd/migrate-v1 applies the M9 schema changes to an existing GBF SQLite
// database and backfills the four derived columns.
//
// Safe to run multiple times: ALTER TABLE is skipped if the column already
// exists, and BackfillDerivedColumns skips already-populated rows.
//
// Usage:
//
//	migrate-v1 -db path/to/gbf.db
package main

import (
	"context"
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	gbf "github.com/kevung/gbf"
	_ "modernc.org/sqlite"
)

func main() {
	dbPath := flag.String("db", "", "path to SQLite database (required)")
	batch := flag.Int("batch", 5000, "rows per backfill transaction")
	flag.Parse()

	if *dbPath == "" {
		fmt.Fprintln(os.Stderr, "usage: migrate-v1 -db <path>")
		os.Exit(1)
	}

	logger := log.New(os.Stdout, "[migrate] ", log.LstdFlags)
	logger.Printf("database: %s", *dbPath)

	db, err := sql.Open("sqlite", *dbPath)
	if err != nil {
		logger.Fatalf("open: %v", err)
	}
	defer db.Close()

	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		logger.Fatalf("WAL: %v", err)
	}

	// ── Step 1: Add columns if missing ───────────────────────────────────────
	logger.Println("adding derived columns (if missing)...")
	additions := []struct{ col, typ string }{
		{"pos_class",   "INTEGER"},
		{"pip_diff",    "INTEGER"},
		{"prime_len_x", "INTEGER"},
		{"prime_len_o", "INTEGER"},
	}
	for _, a := range additions {
		_, err := db.Exec(fmt.Sprintf(
			"ALTER TABLE positions ADD COLUMN %s %s", a.col, a.typ))
		if err != nil {
			// SQLite returns an error if the column already exists; that's fine.
			if isAlreadyExists(err) {
				logger.Printf("  %s: already exists, skipping", a.col)
			} else {
				logger.Fatalf("ALTER TABLE ADD %s: %v", a.col, err)
			}
		} else {
			logger.Printf("  %s: added", a.col)
		}
	}

	// ── Step 2: Add indexes ───────────────────────────────────────────────────
	logger.Println("creating indexes (if missing)...")
	indexes := []string{
		`CREATE INDEX IF NOT EXISTS idx_positions_class      ON positions(pos_class)`,
		`CREATE INDEX IF NOT EXISTS idx_positions_pip_diff   ON positions(pip_diff)`,
		`CREATE INDEX IF NOT EXISTS idx_positions_class_away ON positions(pos_class, away_x, away_o)`,
		`CREATE INDEX IF NOT EXISTS idx_moves_error          ON moves(equity_diff) WHERE equity_diff > 500`,
	}
	for _, idx := range indexes {
		if _, err := db.Exec(idx); err != nil {
			logger.Fatalf("CREATE INDEX: %v", err)
		}
	}
	logger.Println("  indexes ok")

	// ── Step 3: Backfill ─────────────────────────────────────────────────────
	logger.Printf("backfilling derived columns (batch=%d)...", *batch)
	t0 := time.Now()
	res, err := gbf.BackfillDerivedColumns(context.Background(), db, *batch)
	if err != nil {
		logger.Fatalf("backfill: %v", err)
	}
	elapsed := time.Since(t0).Round(time.Second)

	logger.Println("═══════════════════════════════════")
	logger.Printf("  Rows updated:  %d", res.Updated)
	logger.Printf("  Rows skipped:  %d (already populated)", res.Skipped)
	logger.Printf("  Rows errored:  %d", res.Errors)
	logger.Printf("  Elapsed:       %s", elapsed)
	if res.Updated > 0 && elapsed > 0 {
		rps := float64(res.Updated) / elapsed.Seconds()
		logger.Printf("  Throughput:    %.0f rows/s", rps)
	}
	logger.Println("═══════════════════════════════════")
	logger.Println("migration complete.")
}

// isAlreadyExists returns true if the error message indicates the column
// already exists (SQLite does not use error codes for this).
func isAlreadyExists(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	return contains(msg, "duplicate column") || contains(msg, "already exists")
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(s) > 0 &&
		func() bool {
			for i := 0; i <= len(s)-len(sub); i++ {
				if s[i:i+len(sub)] == sub {
					return true
				}
			}
			return false
		}())
}
