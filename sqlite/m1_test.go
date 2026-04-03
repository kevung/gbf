package sqlite_test

import (
	"context"
	"testing"

	gbf "github.com/kevung/gbf"
)

// [U] UpsertMatch — canonical hash dedup.
func TestUpsertMatchDedup(t *testing.T) {
	store, _ := openTemp(t)
	ctx := context.Background()

	m := gbf.Match{
		Metadata: gbf.MatchMetadata{
			Player1Name: "Alice",
			Player2Name: "Bob",
			MatchLength: 7,
		},
	}

	id1, err := store.UpsertMatch(ctx, m, "hash1", "canon1")
	if err != nil {
		t.Fatalf("first upsert: %v", err)
	}
	id2, err := store.UpsertMatch(ctx, m, "hash1", "canon1")
	if err != nil {
		t.Fatalf("second upsert: %v", err)
	}
	if id1 != id2 {
		t.Errorf("expected same match id on duplicate, got %d and %d", id1, id2)
	}
}

// [U] InsertGame — round-trip.
func TestInsertGame(t *testing.T) {
	store, _ := openTemp(t)
	ctx := context.Background()

	m := gbf.Match{Metadata: gbf.MatchMetadata{Player1Name: "A", Player2Name: "B", MatchLength: 7}}
	matchID, err := store.UpsertMatch(ctx, m, "mh", "ch")
	if err != nil {
		t.Fatalf("upsert match: %v", err)
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
		t.Fatalf("insert game: %v", err)
	}
	if gameID <= 0 {
		t.Errorf("expected positive game ID, got %d", gameID)
	}
}

// [U] InsertMove — equity columns populated.
func TestInsertMoveEquity(t *testing.T) {
	store, path := openTemp(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)
	posID, err := store.UpsertPosition(ctx, rec, boardHash)
	if err != nil {
		t.Fatalf("upsert position: %v", err)
	}

	m := gbf.Match{Metadata: gbf.MatchMetadata{Player1Name: "A", Player2Name: "B", MatchLength: 7}}
	matchID, _ := store.UpsertMatch(ctx, m, "mh2", "ch2")
	game := gbf.Game{GameNumber: 1, Winner: 0, PointsWon: 1}
	gameID, _ := store.InsertGame(ctx, matchID, game)

	mv := gbf.Move{
		MoveType:     gbf.MoveTypeChecker,
		Player:       gbf.PlayerX,
		Dice:         [2]int{3, 1},
		MoveString:   "8/5 6/5",
		BestEquity:   2000,  // 0.2000 in x10000
		PlayedEquity: -1500, // mistake
		EquityDiff:   3500,
	}

	if err := store.InsertMove(ctx, gameID, 1, posID, mv); err != nil {
		t.Fatalf("insert move: %v", err)
	}

	// Verify equity columns in DB.
	db := store.DB()
	var equityDiff, bestEquity, playedEquity int
	err = db.QueryRowContext(ctx,
		`SELECT equity_diff, best_equity, played_equity FROM moves WHERE game_id = ? AND move_number = 1`,
		gameID,
	).Scan(&equityDiff, &bestEquity, &playedEquity)
	if err != nil {
		t.Fatalf("query move: %v", err)
	}
	if equityDiff != 3500 {
		t.Errorf("equity_diff: got %d, want 3500", equityDiff)
	}
	if bestEquity != 2000 {
		t.Errorf("best_equity: got %d, want 2000", bestEquity)
	}
	if playedEquity != -1500 {
		t.Errorf("played_equity: got %d, want -1500", playedEquity)
	}

	_ = path
}

// [U] AddAnalysis — stores payload and engine_name.
func TestAddAnalysis(t *testing.T) {
	store, _ := openTemp(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	boardHash := gbf.ComputeBoardOnlyZobrist(&rec)
	posID, _ := store.UpsertPosition(ctx, rec, boardHash)

	payload := []byte{0x01, 0x02, 0x03}
	if err := store.AddAnalysis(ctx, posID, gbf.BlockTypeCheckerPlay, "XG", payload); err != nil {
		t.Fatalf("add analysis: %v", err)
	}

	// Duplicate insert should be silently ignored.
	if err := store.AddAnalysis(ctx, posID, gbf.BlockTypeCheckerPlay, "XG", payload); err != nil {
		t.Fatalf("duplicate add analysis: %v", err)
	}

	var count int
	store.DB().QueryRowContext(ctx,
		`SELECT COUNT(*) FROM analyses WHERE position_id = ?`, posID,
	).Scan(&count)
	if count != 1 {
		t.Errorf("expected 1 analysis row, got %d", count)
	}
}
