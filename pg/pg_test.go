// Package pg_test contains integration tests for the PostgreSQL backend.
// Tests require a running PostgreSQL instance. Set PG_DSN environment variable
// or ensure the default DSN (postgresql://gbf:gbf@localhost:5432/gbf_test) is reachable.
// Start with: docker compose up -d
package pg_test

import (
	"context"
	"os"
	"path/filepath"
	"sync"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/pg"
	"github.com/kevung/gbf/sqlite"
)

const defaultDSN = "postgresql://gbf:gbf@localhost:5432/gbf_test"

// openPGStore connects to PostgreSQL for integration tests. Skips if unavailable.
func openPGStore(t testing.TB) *pg.PGStore {
	t.Helper()
	dsn := os.Getenv("PG_DSN")
	if dsn == "" {
		dsn = defaultDSN
	}
	ctx := context.Background()
	store, err := pg.NewPGStore(ctx, dsn)
	if err != nil {
		t.Skipf("PostgreSQL not available (%v) — run: docker compose up -d", err)
	}
	t.Cleanup(func() {
		// Truncate all tables to isolate tests.
		// TRUNCATE … RESTART IDENTITY CASCADE handles FK dependencies.
		store.TruncateAll(ctx)
		store.Close()
	})
	return store
}

// standardOpeningRecord returns the BaseRecord for the standard backgammon opening.
// X: 2@23, 5@12, 3@7, 5@5   O: 2@0, 5@11, 3@16, 5@18
func standardOpeningRecord(t testing.TB) gbf.BaseRecord {
	t.Helper()
	pos := &gbf.PositionState{
		CubeValue:   1,
		CubeOwner:   gbf.CubeCenter,
		MatchLength: 0,
		AwayX:       0,
		AwayO:       0,
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

// openSQLiteStore returns a temporary SQLite store for use as a migration source.
func openSQLiteStore(t testing.TB) *sqlite.SQLiteStore {
	t.Helper()
	p := filepath.Join(t.TempDir(), "src.db")
	store, err := sqlite.NewSQLiteStore(p)
	if err != nil {
		t.Fatalf("sqlite.NewSQLiteStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

// ── M7.1: Schema creation ────────────────────────────────────────────────────

// [I] NewPGStore — tables and indexes are created idempotently.
func TestNewPGStore_Schema(t *testing.T) {
	_ = openPGStore(t)

	// A second NewPGStore on the same DB must succeed (all DDL uses IF NOT EXISTS).
	dsn := os.Getenv("PG_DSN")
	if dsn == "" {
		dsn = defaultDSN
	}
	ctx := context.Background()
	store2, err := pg.NewPGStore(ctx, dsn)
	if err != nil {
		t.Fatalf("second NewPGStore: %v", err)
	}
	store2.Close()
}

// ── M7.2: Basic round-trip ───────────────────────────────────────────────────

// [I] UpsertPosition + QueryByZobrist — position stored and retrieved correctly.
func TestUpsertAndQueryByZobrist(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)

	id, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}
	if id <= 0 {
		t.Fatalf("expected positive id, got %d", id)
	}

	// Idempotent: second upsert must return the same id.
	id2, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("UpsertPosition (2nd): %v", err)
	}
	if id2 != id {
		t.Errorf("idempotent upsert: id=%d id2=%d, want equal", id, id2)
	}

	results, err := store.QueryByZobrist(ctx, rec.Zobrist)
	if err != nil {
		t.Fatalf("QueryByZobrist: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	got := results[0].Position
	if got.ID != id {
		t.Errorf("id: got %d, want %d", got.ID, id)
	}
	if got.ZobristHash != rec.Zobrist {
		t.Errorf("zobrist: got %d, want %d", got.ZobristHash, rec.Zobrist)
	}
	if got.PosClass != int(gbf.ClassContact) {
		t.Errorf("pos_class: got %d, want %d (contact)", got.PosClass, gbf.ClassContact)
	}
	if got.PipDiff != 0 {
		t.Errorf("pip_diff: got %d, want 0 (opening is symmetric)", got.PipDiff)
	}
}

// [I] QueryByBoardHash — returns positions with the same board layout.
func TestQueryByBoardHash(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)

	if _, err := store.UpsertPosition(ctx, rec, boardHash); err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	results, err := store.QueryByBoardHash(ctx, boardHash)
	if err != nil {
		t.Fatalf("QueryByBoardHash: %v", err)
	}
	if len(results) == 0 {
		t.Fatal("expected at least 1 result")
	}
	if results[0].BoardHash != boardHash {
		t.Errorf("board_hash: got %d, want %d", results[0].BoardHash, boardHash)
	}
}

// [I] Match → Game → Move round-trip.
func TestMatchGameMoveRoundTrip(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	m := gbf.Match{
		Metadata: gbf.MatchMetadata{
			Player1Name: "Alice",
			Player2Name: "Bob",
			MatchLength: 7,
		},
	}
	matchID, err := store.UpsertMatch(ctx, m, "hash1", "canon1")
	if err != nil {
		t.Fatalf("UpsertMatch: %v", err)
	}
	if matchID <= 0 {
		t.Fatalf("expected positive matchID, got %d", matchID)
	}

	// Idempotent: second upsert returns same id.
	matchID2, err := store.UpsertMatch(ctx, m, "hash1", "canon1")
	if err != nil {
		t.Fatalf("UpsertMatch (2nd): %v", err)
	}
	if matchID2 != matchID {
		t.Errorf("idempotent UpsertMatch: %d != %d", matchID2, matchID)
	}

	game := gbf.Game{
		GameNumber:   1,
		InitialScore: [2]int{0, 0},
		Winner:       0,
		PointsWon:    1,
		Crawford:     false,
	}
	gameID, err := store.InsertGame(ctx, matchID, game)
	if err != nil {
		t.Fatalf("InsertGame: %v", err)
	}
	if gameID <= 0 {
		t.Fatalf("expected positive gameID, got %d", gameID)
	}

	rec := standardOpeningRecord(t)
	posID, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	mv := gbf.Move{
		MoveType:     gbf.MoveTypeChecker,
		Player:       0,
		Dice:         [2]int{3, 1},
		MoveString:   "24/23 24/21",
		EquityDiff:   50,
		BestEquity:   -100,
		PlayedEquity: -150,
	}
	if err := store.InsertMove(ctx, gameID, 1, posID, mv); err != nil {
		t.Fatalf("InsertMove: %v", err)
	}
}

// [I] AddAnalysis — stored and returned with QueryByZobrist.
func TestAddAnalysis(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	id, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	payload := []byte{0x01, 0x02, 0x03}
	if err := store.AddAnalysis(ctx, id, 1, "gnubg", payload); err != nil {
		t.Fatalf("AddAnalysis: %v", err)
	}

	// Idempotent: duplicate is ignored.
	if err := store.AddAnalysis(ctx, id, 1, "gnubg", payload); err != nil {
		t.Fatalf("AddAnalysis (duplicate): %v", err)
	}

	results, err := store.QueryByZobrist(ctx, rec.Zobrist)
	if err != nil {
		t.Fatalf("QueryByZobrist: %v", err)
	}
	if len(results) == 0 {
		t.Fatal("no results")
	}
	if len(results[0].Analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(results[0].Analyses))
	}
	a := results[0].Analyses[0]
	if a.BlockType != 1 {
		t.Errorf("block_type: got %d, want 1", a.BlockType)
	}
	if a.EngineName != "gnubg" {
		t.Errorf("engine_name: got %q, want gnubg", a.EngineName)
	}
	if string(a.Payload) != string(payload) {
		t.Errorf("payload mismatch")
	}
}

// ── M7.3: Batcher ────────────────────────────────────────────────────────────

// variantRecord returns a valid BaseRecord derived from the standard opening
// but with a different MatchLength and away scores to produce a distinct Zobrist.
func variantRecord(t testing.TB, matchLength, awayX, awayO int) gbf.BaseRecord {
	t.Helper()
	pos := &gbf.PositionState{
		CubeValue:   1,
		CubeOwner:   gbf.CubeCenter,
		MatchLength: matchLength,
		AwayX:       awayX,
		AwayO:       awayO,
	}
	// Standard opening board layout.
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

// [I] BeginBatch/CommitBatch — positions visible after commit.
func TestBatchCommit(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	// Build records before opening the batch transaction.
	recs := []gbf.BaseRecord{
		variantRecord(t, 5, 1, 2),
		variantRecord(t, 7, 3, 4),
		variantRecord(t, 9, 2, 1),
	}

	if err := store.BeginBatch(ctx); err != nil {
		t.Fatalf("BeginBatch: %v", err)
	}
	for i, rec := range recs {
		r := rec
		if _, err := store.UpsertPosition(ctx, r, gbf.ComputeBoardOnlyZobrist(&r)); err != nil {
			store.RollbackBatch()
			t.Fatalf("UpsertPosition[%d]: %v", i, err)
		}
	}
	if err := store.CommitBatch(); err != nil {
		t.Fatalf("CommitBatch: %v", err)
	}

	// All three positions must now be queryable.
	for i, rec := range recs {
		res, err := store.QueryByZobrist(ctx, rec.Zobrist)
		if err != nil {
			t.Fatalf("QueryByZobrist[%d]: %v", i, err)
		}
		if len(res) != 1 {
			t.Errorf("position[%d]: expected 1 result after commit, got %d", i, len(res))
		}
	}
}

// [I] BeginBatch/RollbackBatch — positions NOT visible after rollback.
func TestBatchRollback(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	rec := variantRecord(t, 11, 4, 3)

	if err := store.BeginBatch(ctx); err != nil {
		t.Fatalf("BeginBatch: %v", err)
	}
	if _, err := store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec)); err != nil {
		store.RollbackBatch()
		t.Fatalf("UpsertPosition: %v", err)
	}
	store.RollbackBatch()

	res, err := store.QueryByZobrist(ctx, rec.Zobrist)
	if err != nil {
		t.Fatalf("QueryByZobrist: %v", err)
	}
	if len(res) != 0 {
		t.Errorf("expected 0 results after rollback, got %d", len(res))
	}
}

// ── M7.4: Concurrency ────────────────────────────────────────────────────────

// [I] 10 concurrent UpsertPosition goroutines — no data races, all succeed.
// Run with: go test -race ./pg/...
func TestConcurrentUpsert(t *testing.T) {
	store := openPGStore(t)
	ctx := context.Background()

	const workers = 10
	var wg sync.WaitGroup
	errs := make([]error, workers)

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			rec := variantRecord(t, idx+1, idx, idx%5)
			_, errs[idx] = store.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
		}(i)
	}
	wg.Wait()

	for i, err := range errs {
		if err != nil {
			t.Errorf("worker %d: %v", i, err)
		}
	}
}

// ── M7.5: Migration SQLite → PostgreSQL ─────────────────────────────────────

// [I] MigrateStore — row counts match between SQLite source and PG destination.
func TestMigrateStoreSQLiteToPG(t *testing.T) {
	ctx := context.Background()

	// Build SQLite source with a small dataset.
	src := openSQLiteStore(t)

	matchID, err := src.UpsertMatch(ctx,
		gbf.Match{Metadata: gbf.MatchMetadata{Player1Name: "A", Player2Name: "B", MatchLength: 5}},
		"mhash-migrate", "chash-migrate",
	)
	if err != nil {
		t.Fatalf("UpsertMatch: %v", err)
	}
	gameID, err := src.InsertGame(ctx, matchID,
		gbf.Game{GameNumber: 1, InitialScore: [2]int{0, 0}, Winner: 0, PointsWon: 1})
	if err != nil {
		t.Fatalf("InsertGame: %v", err)
	}

	for i := 0; i < 5; i++ {
		rec := variantRecord(t, i+1, i, i)
		posID, err := src.UpsertPosition(ctx, rec, gbf.ComputeBoardOnlyZobrist(&rec))
		if err != nil {
			t.Fatalf("UpsertPosition[%d]: %v", i, err)
		}
		mv := gbf.Move{
			MoveType:   gbf.MoveTypeChecker,
			Player:     0,
			Dice:       [2]int{3, 1},
			MoveString: "24/23 24/21",
		}
		if err := src.InsertMove(ctx, gameID, i+1, posID, mv); err != nil {
			t.Fatalf("InsertMove[%d]: %v", i, err)
		}
		if err := src.AddAnalysis(ctx, posID, 1, "gnubg", []byte{byte(i)}); err != nil {
			t.Fatalf("AddAnalysis[%d]: %v", i, err)
		}
	}

	// Count rows in SQLite source via the underlying DB.
	srcDB := src.DB()
	srcCounts := map[string]int{}
	for _, tbl := range []string{"positions", "matches", "games", "moves", "analyses"} {
		var n int
		if err := srcDB.QueryRowContext(ctx, "SELECT COUNT(*) FROM "+tbl).Scan(&n); err != nil {
			t.Fatalf("count %s: %v", tbl, err)
		}
		srcCounts[tbl] = n
	}

	// Run migration.
	dst := openPGStore(t)
	result, err := gbf.MigrateStore(ctx, srcDB, dst, 100)
	if err != nil {
		t.Fatalf("MigrateStore: %v", err)
	}

	if result.Positions != srcCounts["positions"] {
		t.Errorf("positions: migrated %d, src has %d", result.Positions, srcCounts["positions"])
	}
	if result.Matches != srcCounts["matches"] {
		t.Errorf("matches: migrated %d, src has %d", result.Matches, srcCounts["matches"])
	}
	if result.Games != srcCounts["games"] {
		t.Errorf("games: migrated %d, src has %d", result.Games, srcCounts["games"])
	}
	if result.Moves != srcCounts["moves"] {
		t.Errorf("moves: migrated %d, src has %d", result.Moves, srcCounts["moves"])
	}
	if result.Analyses != srcCounts["analyses"] {
		t.Errorf("analyses: migrated %d, src has %d", result.Analyses, srcCounts["analyses"])
	}
}
