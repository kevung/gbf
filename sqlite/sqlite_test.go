package sqlite_test

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	gbf "github.com/kevung/gbf"
	"github.com/kevung/gbf/sqlite"
	_ "modernc.org/sqlite"
)

func openTemp(t *testing.T) (*sqlite.SQLiteStore, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.db")
	store, err := sqlite.NewSQLiteStore(path)
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store, path
}

// [U] SQLiteStore lifecycle: open, verify 5 tables, close.
func TestLifecycle(t *testing.T) {
	_, path := openTemp(t)

	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	rows, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table' ORDER BY name`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()

	var tables []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatal(err)
		}
		tables = append(tables, name)
	}

	want := []string{"analyses", "games", "matches", "moves", "positions", "projection_runs", "projections"}
	if len(tables) != len(want) {
		t.Fatalf("got tables %v, want %v", tables, want)
	}
	for i, name := range want {
		if tables[i] != name {
			t.Errorf("table[%d] = %q, want %q", i, tables[i], name)
		}
	}
}

// [U] Schema constraints: duplicate zobrist_hash is silently ignored.
func TestUpsertDuplicate(t *testing.T) {
	store, _ := openTemp(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)

	id1, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("first upsert: %v", err)
	}

	id2, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("second upsert: %v", err)
	}

	if id1 != id2 {
		t.Errorf("expected same id on duplicate upsert, got %d and %d", id1, id2)
	}
}

// [U] QueryByZobrist: round-trip through the DB.
func TestQueryByZobrist(t *testing.T) {
	store, _ := openTemp(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)

	_, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}

	positions, err := store.QueryByZobrist(ctx, rec.Zobrist)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(positions) != 1 {
		t.Fatalf("expected 1 position, got %d", len(positions))
	}

	got := positions[0]
	if got.ZobristHash != rec.Zobrist {
		t.Errorf("ZobristHash mismatch: got %d, want %d", got.ZobristHash, rec.Zobrist)
	}
	if got.BoardHash != boardHash {
		t.Errorf("BoardHash mismatch: got %d, want %d", got.BoardHash, boardHash)
	}
	if got.BaseRecord.Zobrist != rec.Zobrist {
		t.Errorf("BaseRecord.Zobrist mismatch after round-trip")
	}
}

// [F] Full schema creation: insert one row per table, query back.
func TestFullSchemaRoundTrip(t *testing.T) {
	store, path := openTemp(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)

	posID, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("upsert position: %v", err)
	}

	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	// Insert match
	res, err := db.Exec(`INSERT INTO matches
		(match_hash, canonical_hash, source_format, player1, player2, match_length)
		VALUES ('hash1', 'canon1', 'xg', 'Alice', 'Bob', 7)`)
	if err != nil {
		t.Fatalf("insert match: %v", err)
	}
	matchID, _ := res.LastInsertId()

	// Insert game
	res, err = db.Exec(`INSERT INTO games
		(match_id, game_number, score_x, score_o, winner, points_won, crawford)
		VALUES (?, 1, 0, 0, 0, 1, 0)`, matchID)
	if err != nil {
		t.Fatalf("insert game: %v", err)
	}
	gameID, _ := res.LastInsertId()

	// Insert move
	_, err = db.Exec(`INSERT INTO moves
		(game_id, move_number, position_id, player, move_type, dice_1, dice_2, equity_diff)
		VALUES (?, 1, ?, 0, 'checker', 3, 1, 500)`, gameID, posID)
	if err != nil {
		t.Fatalf("insert move: %v", err)
	}

	// Insert analysis
	_, err = db.Exec(`INSERT INTO analyses
		(position_id, block_type, engine_name, payload)
		VALUES (?, 1, 'XG', X'01')`, posID)
	if err != nil {
		t.Fatalf("insert analysis: %v", err)
	}

	// Verify counts
	for _, tc := range []struct {
		table string
		want  int
	}{
		{"positions", 1},
		{"matches", 1},
		{"games", 1},
		{"moves", 1},
		{"analyses", 1},
	} {
		var count int
		db.QueryRow("SELECT COUNT(*) FROM " + tc.table).Scan(&count)
		if count != tc.want {
			t.Errorf("table %s: got %d rows, want %d", tc.table, count, tc.want)
		}
	}

	_ = os.Remove(path)
}

// standardOpeningRecord builds the standard backgammon starting position as a BaseRecord.
func standardOpeningRecord(t *testing.T) gbf.BaseRecord {
	t.Helper()
	pos := &gbf.PositionState{
		SideToMove: gbf.PlayerX,
		CubeValue:  1,
		CubeOwner:  gbf.CubeCenter,
		AwayX:      7,
		AwayO:      7,
	}
	// Standard opening: X on 6(×5), 8(×3), 13(×5), 24(×2)
	pos.Board[5] = 5
	pos.Board[7] = 3
	pos.Board[12] = 5
	pos.Board[23] = 2
	// O on 1(×2), 12(×5), 17(×3), 19(×5) — mirrored
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
