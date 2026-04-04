package gbf_test

import (
	"context"
	"testing"
	"time"

	gbf "github.com/kevung/gbf"
)

// BenchmarkZobristLookup measures single-row lookup by zobrist_hash.
func BenchmarkZobristLookup(b *testing.B) {
	dir := bmabDir(b)
	store := openSQLiteStore(b)
	ctx := context.Background()

	opts := gbf.ImportOpts{
		BatchSize:  200,
		Limit:      200,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		b.Fatalf("import: %v", err)
	}

	// Collect a sample of hashes to look up.
	rows, err := store.DB().QueryContext(ctx,
		`SELECT zobrist_hash FROM positions LIMIT 100`)
	if err != nil {
		b.Fatalf("collect hashes: %v", err)
	}
	var hashes []uint64
	for rows.Next() {
		var h int64
		rows.Scan(&h)
		hashes = append(hashes, uint64(h))
	}
	rows.Close()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		h := hashes[i%len(hashes)]
		_, err := store.QueryByZobrist(ctx, h)
		if err != nil {
			b.Fatalf("QueryByZobrist: %v", err)
		}
	}
}

// BenchmarkClassAwayQuery measures the composite-index class+away query.
func BenchmarkClassAwayQuery(b *testing.B) {
	dir := bmabDir(b)
	store := openSQLiteStore(b)
	ctx := context.Background()

	opts := gbf.ImportOpts{
		BatchSize:  200,
		Limit:      200,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		b.Fatalf("import: %v", err)
	}

	db := store.DB()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		rows, err := db.QueryContext(ctx,
			`SELECT id FROM positions
			 WHERE pos_class = 0 AND away_x = 1 AND away_o = 1
			 LIMIT 100`)
		if err != nil {
			b.Fatalf("query: %v", err)
		}
		for rows.Next() {
		}
		rows.Close()
	}
}

// BenchmarkPipDiffRangeQuery measures pip_diff range filter.
func BenchmarkPipDiffRangeQuery(b *testing.B) {
	dir := bmabDir(b)
	store := openSQLiteStore(b)
	ctx := context.Background()

	opts := gbf.ImportOpts{
		BatchSize:  200,
		Limit:      200,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		b.Fatalf("import: %v", err)
	}

	db := store.DB()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		rows, err := db.QueryContext(ctx,
			`SELECT id, pip_diff FROM positions
			 WHERE pip_diff BETWEEN -10 AND 10
			 LIMIT 100`)
		if err != nil {
			b.Fatalf("query: %v", err)
		}
		for rows.Next() {
		}
		rows.Close()
	}
}

// BenchmarkImportThroughput measures import speed (positions per second)
// using the default parallel pipeline (Workers = runtime.NumCPU()).
func BenchmarkImportThroughput(b *testing.B) {
	dir := bmabDir(b)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		b.StopTimer()
		store := openSQLiteStore(b)
		ctx := context.Background()
		opts := gbf.ImportOpts{
			BatchSize:  100,
			Limit:      100,
			FileParser: xgParser,
			EngineName: "eXtreme Gammon",
		}
		b.StartTimer()

		start := time.Now()
		report, err := gbf.ImportDirectory(ctx, store, dir, opts)
		if err != nil {
			b.Fatalf("import: %v", err)
		}
		elapsed := time.Since(start)

		b.ReportMetric(float64(report.Positions)/elapsed.Seconds(), "pos/s")
	}
}

// BenchmarkImportThroughputSeq measures import speed with Workers=1 (sequential)
// as a baseline to compare against the parallel pipeline.
func BenchmarkImportThroughputSeq(b *testing.B) {
	dir := bmabDir(b)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		b.StopTimer()
		store := openSQLiteStore(b)
		ctx := context.Background()
		opts := gbf.ImportOpts{
			BatchSize:  100,
			Limit:      100,
			FileParser: xgParser,
			EngineName: "eXtreme Gammon",
			Workers:    1,
		}
		b.StartTimer()

		start := time.Now()
		report, err := gbf.ImportDirectory(ctx, store, dir, opts)
		if err != nil {
			b.Fatalf("import: %v", err)
		}
		elapsed := time.Since(start)

		b.ReportMetric(float64(report.Positions)/elapsed.Seconds(), "pos/s")
	}
}
