package gbf_test

import (
	"context"
	"database/sql"
	"strings"
	"testing"

	gbf "github.com/kevung/gbf"
)

// ── M9.1: Derived columns are populated on UpsertPosition ────────────────

// [U] Derived columns filled on insert — standard opening position.
func TestDerivedColumnsOnInsert(t *testing.T) {
	store := openSQLiteStore(t)
	rec := standardOpeningRecord(t)

	ctx := context.Background()
	id, err := store.UpsertPosition(ctx, rec, 0)
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	var posClass, pipDiff, primeLenX, primeLenO sql.NullInt64
	err = store.DB().QueryRowContext(ctx,
		`SELECT pos_class, pip_diff, prime_len_x, prime_len_o
		 FROM positions WHERE id = ?`, id,
	).Scan(&posClass, &pipDiff, &primeLenX, &primeLenO)
	if err != nil {
		t.Fatalf("query: %v", err)
	}

	if !posClass.Valid {
		t.Error("pos_class is NULL")
	} else if posClass.Int64 != int64(gbf.ClassContact) {
		t.Errorf("pos_class: got %d, want %d (contact)", posClass.Int64, gbf.ClassContact)
	}

	if !pipDiff.Valid {
		t.Error("pip_diff is NULL")
	} else if pipDiff.Int64 != 0 {
		// Opening position: pip_x == pip_o == 167.
		t.Errorf("pip_diff: got %d, want 0", pipDiff.Int64)
	}

	if !primeLenX.Valid {
		t.Error("prime_len_x is NULL")
	}
	if !primeLenO.Valid {
		t.Error("prime_len_o is NULL")
	}
	// Opening position: made points at non-consecutive pts — longest run = 1.
	if primeLenX.Int64 != 1 {
		t.Errorf("prime_len_x: got %d, want 1 (non-consecutive made points)", primeLenX.Int64)
	}
	if primeLenO.Int64 != 1 {
		t.Errorf("prime_len_o: got %d, want 1 (non-consecutive made points)", primeLenO.Int64)
	}
}

// [U] pos_class=race for a pure race position.
func TestDerivedColumnsRace(t *testing.T) {
	store := openSQLiteStore(t)

	pos := &gbf.PositionState{CubeValue: 1}
	// X in 6-11, O in 12-17 — no contact, not home board.
	pos.Board[6] = 3; pos.Board[7] = 3; pos.Board[8] = 3
	pos.Board[9] = 3; pos.Board[10] = 3
	pos.Board[12] = -3; pos.Board[13] = -3; pos.Board[14] = -3
	pos.Board[15] = -3; pos.Board[16] = -3

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	ctx := context.Background()
	id, err := store.UpsertPosition(ctx, *rec, 0)
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	var posClass sql.NullInt64
	store.DB().QueryRowContext(ctx,
		`SELECT pos_class FROM positions WHERE id = ?`, id,
	).Scan(&posClass)

	if !posClass.Valid || posClass.Int64 != int64(gbf.ClassRace) {
		t.Errorf("pos_class: got %v, want %d (race)", posClass, gbf.ClassRace)
	}
}

// [U] pos_class=bearoff for a bearoff position.
func TestDerivedColumnsBearoff(t *testing.T) {
	store := openSQLiteStore(t)

	pos := &gbf.PositionState{CubeValue: 1}
	pos.Board[0] = 3; pos.Board[1] = 3; pos.Board[2] = 3
	pos.Board[3] = 3; pos.Board[4] = 3
	pos.Board[18] = -3; pos.Board[19] = -3; pos.Board[20] = -3
	pos.Board[21] = -3; pos.Board[22] = -3

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	ctx := context.Background()
	id, err := store.UpsertPosition(ctx, *rec, 0)
	if err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	var posClass sql.NullInt64
	store.DB().QueryRowContext(ctx,
		`SELECT pos_class FROM positions WHERE id = ?`, id,
	).Scan(&posClass)

	if !posClass.Valid || posClass.Int64 != int64(gbf.ClassBearoff) {
		t.Errorf("pos_class: got %v, want %d (bearoff)", posClass, gbf.ClassBearoff)
	}
}

// ── M9.1: BackfillDerivedColumns ─────────────────────────────────────────

// [U] BackfillDerivedColumns updates rows with NULL derived columns.
func TestBackfillDerivedColumns(t *testing.T) {
	store := openSQLiteStore(t)
	db := store.DB()
	ctx := context.Background()

	// Insert a position with NULL derived columns (simulating pre-M9 import).
	rec := standardOpeningRecord(t)
	blob := gbf.MarshalBaseRecord(&rec)
	_, err := db.ExecContext(ctx, `
		INSERT INTO positions
			(zobrist_hash, board_hash, base_record, pip_x, pip_o, away_x, away_o,
			 cube_log2, cube_owner, bar_x, bar_o, borne_off_x, borne_off_o, side_to_move)
		VALUES (42, 0, ?, 167, 167, 0, 0, 0, 0, 0, 0, 0, 0, 0)`, blob)
	if err != nil {
		t.Fatalf("manual insert: %v", err)
	}

	// Verify that derived columns are NULL.
	var posClass sql.NullInt64
	db.QueryRowContext(ctx, `SELECT pos_class FROM positions WHERE zobrist_hash=42`).Scan(&posClass)
	if posClass.Valid {
		t.Fatal("expected pos_class to be NULL before backfill")
	}

	result, err := gbf.BackfillDerivedColumns(ctx, db, 100)
	if err != nil {
		t.Fatalf("BackfillDerivedColumns: %v", err)
	}
	if result.Updated != 1 {
		t.Errorf("Updated: got %d, want 1", result.Updated)
	}

	// Verify derived columns are now populated.
	db.QueryRowContext(ctx, `SELECT pos_class FROM positions WHERE zobrist_hash=42`).Scan(&posClass)
	if !posClass.Valid {
		t.Error("pos_class still NULL after backfill")
	} else if posClass.Int64 != int64(gbf.ClassContact) {
		t.Errorf("pos_class: got %d, want contact", posClass.Int64)
	}
}

// [U] BackfillDerivedColumns skips rows already populated.
func TestBackfillSkipsPopulatedRows(t *testing.T) {
	store := openSQLiteStore(t)
	ctx := context.Background()

	rec := standardOpeningRecord(t)
	if _, err := store.UpsertPosition(ctx, rec, 0); err != nil {
		t.Fatalf("UpsertPosition: %v", err)
	}

	result, err := gbf.BackfillDerivedColumns(ctx, store.DB(), 100)
	if err != nil {
		t.Fatalf("BackfillDerivedColumns: %v", err)
	}
	if result.Updated != 0 {
		t.Errorf("Updated: got %d, want 0 (already populated)", result.Updated)
	}
	if result.Skipped != 1 {
		t.Errorf("Skipped: got %d, want 1", result.Skipped)
	}
}

// ── M9.2: Index usage ─────────────────────────────────────────────────────

// [U] Composite index idx_positions_class_away is used for class+away query.
func TestCompositeIndexUsed(t *testing.T) {
	store := openSQLiteStore(t)
	db := store.DB()

	plan := ""
	rows, err := db.Query(
		`EXPLAIN QUERY PLAN
		 SELECT id FROM positions
		 WHERE pos_class = 0 AND away_x = 1 AND away_o = 1`)
	if err != nil {
		t.Fatalf("EXPLAIN: %v", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, parent, notused int
		var detail string
		rows.Scan(&id, &parent, &notused, &detail)
		plan += detail + "\n"
	}

	if !strings.Contains(strings.ToLower(plan), "idx_positions_class_away") {
		t.Errorf("expected idx_positions_class_away in query plan, got:\n%s", plan)
	}
}

// [U] pip_diff index is used for range queries.
func TestPipDiffIndexUsed(t *testing.T) {
	store := openSQLiteStore(t)
	db := store.DB()

	plan := ""
	rows, err := db.Query(
		`EXPLAIN QUERY PLAN
		 SELECT id FROM positions WHERE pip_diff BETWEEN -10 AND 10`)
	if err != nil {
		t.Fatalf("EXPLAIN: %v", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, parent, notused int
		var detail string
		rows.Scan(&id, &parent, &notused, &detail)
		plan += detail + "\n"
	}

	if !strings.Contains(strings.ToLower(plan), "idx_positions_pip_diff") {
		t.Errorf("expected idx_positions_pip_diff in query plan, got:\n%s", plan)
	}
}

// ── M9: Functional — backfill on imported data ────────────────────────────

// [F] Backfill on 100 BMAB positions: no NULL, values match ExtractFeatures.
func TestBackfillCorrectness(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping backfill correctness test in short mode")
	}

	dir := bmabDir(t)
	store := openSQLiteStore(t)
	ctx := context.Background()

	// Import 10 files with the old-style insert (NULL derived columns).
	db := store.DB()
	opts := gbf.ImportOpts{
		BatchSize:  10,
		Limit:      10,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		t.Fatalf("import: %v", err)
	}

	// Count positions.
	var total int
	db.QueryRowContext(ctx, `SELECT COUNT(*) FROM positions`).Scan(&total)
	if total == 0 {
		t.Fatal("no positions imported")
	}

	// Reset derived columns to NULL to simulate pre-M9 state.
	if _, err := db.ExecContext(ctx,
		`UPDATE positions SET pos_class=NULL, pip_diff=NULL, prime_len_x=NULL, prime_len_o=NULL`,
	); err != nil {
		t.Fatalf("reset: %v", err)
	}

	result, err := gbf.BackfillDerivedColumns(ctx, db, 200)
	if err != nil {
		t.Fatalf("BackfillDerivedColumns: %v", err)
	}
	if result.Updated != total {
		t.Errorf("Updated: got %d, want %d", result.Updated, total)
	}
	if result.Errors != 0 {
		t.Errorf("Errors: got %d, want 0", result.Errors)
	}

	// Spot-check: compare DB columns against ExtractDerivedFeatures.
	rows, err := db.QueryContext(ctx,
		`SELECT base_record, pos_class, pip_diff, prime_len_x, prime_len_o
		 FROM positions LIMIT 100`)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer rows.Close()

	checked := 0
	for rows.Next() {
		var blob []byte
		var cls, pd, plx, plo sql.NullInt64
		if err := rows.Scan(&blob, &cls, &pd, &plx, &plo); err != nil {
			t.Fatalf("scan: %v", err)
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			t.Fatalf("unmarshal: %v", err)
		}
		derived := gbf.ExtractDerivedFeatures(*rec)
		wantClass := int64(derived[9])
		wantDiff  := int64(derived[8])
		wantPLX   := int64(derived[4])
		wantPLO   := int64(derived[5])

		if !cls.Valid || cls.Int64 != wantClass {
			t.Errorf("pos_class mismatch: got %v, want %d", cls, wantClass)
		}
		if !pd.Valid || pd.Int64 != wantDiff {
			t.Errorf("pip_diff mismatch: got %v, want %d", pd, wantDiff)
		}
		if !plx.Valid || plx.Int64 != wantPLX {
			t.Errorf("prime_len_x mismatch: got %v, want %d", plx, wantPLX)
		}
		if !plo.Valid || plo.Int64 != wantPLO {
			t.Errorf("prime_len_o mismatch: got %v, want %d", plo, wantPLO)
		}
		checked++
	}
	t.Logf("spot-checked %d positions, all derived columns correct", checked)
}
