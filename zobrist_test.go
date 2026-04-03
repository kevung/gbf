package gbf_test

import (
	"testing"

	gbf "github.com/kevung/gbf"
)

// [U] Board-only Zobrist: same board, different context → same hash.
func TestBoardOnlyZobristSameBoard(t *testing.T) {
	base := standardOpening()

	a := *base
	a.CubeLog2 = 0
	a.CubeOwner = gbf.CubeCenter
	a.AwayX = 7
	a.AwayO = 7
	a.SideToMove = gbf.PlayerX

	b := *base
	b.CubeLog2 = 2 // cube=4
	b.CubeOwner = gbf.CubeX
	b.AwayX = 3
	b.AwayO = 5
	b.SideToMove = gbf.PlayerO

	ha := gbf.ComputeBoardOnlyZobrist(&a)
	hb := gbf.ComputeBoardOnlyZobrist(&b)

	if ha != hb {
		t.Errorf("expected same board-only hash for identical boards, got %d vs %d", ha, hb)
	}
}

// [U] Board-only Zobrist: different boards → different hash.
func TestBoardOnlyZobristDifferentBoards(t *testing.T) {
	a := standardOpening()

	b := *a
	// Move one checker from point 5 (5 checkers) to point 4 (empty)
	b.PointCounts[5] = 4
	b.PointCounts[4] = 1
	b.LayersX[0] |= 1 << 4  // layer1[4] = present
	b.LayersX[3] &^= 1 << 5 // layer4[5] = absent (was set for 5 checkers)

	ha := gbf.ComputeBoardOnlyZobrist(a)
	hb := gbf.ComputeBoardOnlyZobrist(&b)

	if ha == hb {
		t.Errorf("expected different board-only hash for different boards")
	}
}

// [U] Context-aware Zobrist: same position as legacy produces identical hash.
// We verify that ComputeZobrist matches itself on a round-trip (legacy parity
// would require importing the legacy package; we test self-consistency here).
func TestZobristRoundTrip(t *testing.T) {
	pos := &gbf.PositionState{
		SideToMove: gbf.PlayerX,
		CubeValue:  1,
		CubeOwner:  gbf.CubeCenter,
		AwayX:      7,
		AwayO:      7,
	}
	pos.Board[5] = 5
	pos.Board[7] = 3
	pos.Board[12] = 5
	pos.Board[23] = 2
	pos.Board[0] = -2
	pos.Board[11] = -5
	pos.Board[16] = -3
	pos.Board[18] = -5

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	// Zobrist stored in record must equal recomputed value
	recomputed := gbf.ComputeZobrist(rec)
	if rec.Zobrist != recomputed {
		t.Errorf("stored Zobrist %d != recomputed %d", rec.Zobrist, recomputed)
	}

	// Marshal → unmarshal → recompute must still match
	blob := gbf.MarshalBaseRecord(rec)
	rec2, err := gbf.UnmarshalBaseRecord(blob)
	if err != nil {
		t.Fatalf("UnmarshalBaseRecord: %v", err)
	}
	if gbf.ComputeZobrist(rec2) != rec.Zobrist {
		t.Errorf("Zobrist changed after marshal/unmarshal round-trip")
	}
}

// [U] Context-aware Zobrist: different context on same board → different hash.
func TestZobristContextSensitive(t *testing.T) {
	base := standardOpening()

	a := *base
	a.AwayX = 7
	a.AwayO = 7
	a.Zobrist = gbf.ComputeZobrist(&a)

	b := *base
	b.AwayX = 1
	b.AwayO = 1
	b.Zobrist = gbf.ComputeZobrist(&b)

	if a.Zobrist == b.Zobrist {
		t.Errorf("expected different context-aware hashes for different away scores")
	}
}

// standardOpening returns a BaseRecord for the standard opening position.
func standardOpening() *gbf.BaseRecord {
	pos := &gbf.PositionState{
		SideToMove: gbf.PlayerX,
		CubeValue:  1,
		CubeOwner:  gbf.CubeCenter,
		AwayX:      7,
		AwayO:      7,
	}
	pos.Board[5] = 5
	pos.Board[7] = 3
	pos.Board[12] = 5
	pos.Board[23] = 2
	pos.Board[0] = -2
	pos.Board[11] = -5
	pos.Board[16] = -3
	pos.Board[18] = -5

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		panic(err)
	}
	return rec
}
