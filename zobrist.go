package gbf

// Zobrist hashing for GBF records.
//
// Two hash variants:
//   - Context-aware: includes board, bar, borne-off, side to move, cube, away scores.
//     Stored in the BaseRecord.Zobrist field.
//   - Board-only: includes only board, bar, borne-off.
//     Computed at import time, stored as a DB column (board_hash).
//
// Both use the same PRNG seed (0x12345678DEADBEEF) and key tables.
// The board-only hash simply omits XOR contributions from context fields.

var zobristKeys struct {
	layerX     [4][24]uint64
	layerO     [4][24]uint64
	pointCount [24][16]uint64
	barX       [16]uint64
	barO       [16]uint64
	borneOffX  [16]uint64
	borneOffO  [16]uint64
	sideToMove [2]uint64
	cubeLog2   [8]uint64
	cubeOwner  [3]uint64
	awayX      [256]uint64
	awayO      [256]uint64
}

func init() {
	state := uint64(0x12345678DEADBEEF)
	next := func() uint64 {
		state ^= state << 13
		state ^= state >> 7
		state ^= state << 17
		return state
	}

	for layer := 0; layer < 4; layer++ {
		for pt := 0; pt < 24; pt++ {
			zobristKeys.layerX[layer][pt] = next()
		}
	}
	for layer := 0; layer < 4; layer++ {
		for pt := 0; pt < 24; pt++ {
			zobristKeys.layerO[layer][pt] = next()
		}
	}
	for pt := 0; pt < 24; pt++ {
		for c := 0; c < 16; c++ {
			zobristKeys.pointCount[pt][c] = next()
		}
	}
	for c := 0; c < 16; c++ {
		zobristKeys.barX[c] = next()
	}
	for c := 0; c < 16; c++ {
		zobristKeys.barO[c] = next()
	}
	for c := 0; c < 16; c++ {
		zobristKeys.borneOffX[c] = next()
	}
	for c := 0; c < 16; c++ {
		zobristKeys.borneOffO[c] = next()
	}
	for i := 0; i < 2; i++ {
		zobristKeys.sideToMove[i] = next()
	}
	for i := 0; i < 8; i++ {
		zobristKeys.cubeLog2[i] = next()
	}
	for i := 0; i < 3; i++ {
		zobristKeys.cubeOwner[i] = next()
	}
	for i := 0; i < 256; i++ {
		zobristKeys.awayX[i] = next()
	}
	for i := 0; i < 256; i++ {
		zobristKeys.awayO[i] = next()
	}
}

// boardHash computes the board-only component shared by both hash variants.
func boardHash(rec *BaseRecord) uint64 {
	var h uint64
	for layer := 0; layer < 4; layer++ {
		for pt := 0; pt < 24; pt++ {
			if rec.LayersX[layer]&(1<<uint(pt)) != 0 {
				h ^= zobristKeys.layerX[layer][pt]
			}
			if rec.LayersO[layer]&(1<<uint(pt)) != 0 {
				h ^= zobristKeys.layerO[layer][pt]
			}
		}
	}
	for pt := 0; pt < 24; pt++ {
		h ^= zobristKeys.pointCount[pt][rec.PointCounts[pt]]
	}
	h ^= zobristKeys.barX[rec.BarX]
	h ^= zobristKeys.barO[rec.BarO]
	h ^= zobristKeys.borneOffX[rec.BorneOffX]
	h ^= zobristKeys.borneOffO[rec.BorneOffO]
	return h
}

// ComputeZobrist computes the context-aware Zobrist hash for a BaseRecord.
// Includes: board, bar, borne-off, side to move, cube state, away scores.
func ComputeZobrist(rec *BaseRecord) uint64 {
	h := boardHash(rec)
	h ^= zobristKeys.sideToMove[rec.SideToMove]
	if rec.CubeLog2 < 8 {
		h ^= zobristKeys.cubeLog2[rec.CubeLog2]
	}
	if rec.CubeOwner < 3 {
		h ^= zobristKeys.cubeOwner[rec.CubeOwner]
	}
	h ^= zobristKeys.awayX[rec.AwayX]
	h ^= zobristKeys.awayO[rec.AwayO]
	return h
}

// ComputeBoardOnlyZobrist computes the board-only Zobrist hash for a BaseRecord.
// Includes: board, bar, borne-off only. Excludes side to move, cube, away scores.
// Used as the board_hash DB column to find the same board layout across contexts.
func ComputeBoardOnlyZobrist(rec *BaseRecord) uint64 {
	return boardHash(rec)
}
