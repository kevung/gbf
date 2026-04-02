package gbf

// Zobrist hashing for GBF records.
//
// The hash must include: all checker layers, exact counts, bar, borne-off,
// side to move, cube state, away scores.
// The hash must exclude: pip counts, analysis blocks.
//
// Zobrist keys are deterministic 64-bit values derived from position
// components using a fixed PRNG seed.

// zobristKeys holds all pre-computed random values for hashing.
// Generated deterministically from a fixed seed via a simple xorshift64 PRNG.
var zobristKeys struct {
	// layerX[layer][point] - Player X layer bit at point
	layerX [4][24]uint64
	// layerO[layer][point] - Player O layer bit at point
	layerO [4][24]uint64
	// pointCount[point][count] - exact count at point (0-15)
	pointCount [24][16]uint64
	// barX[count] - Player X bar count (0-15)
	barX [16]uint64
	// barO[count] - Player O bar count (0-15)
	barO [16]uint64
	// borneOffX[count] - Player X borne off count (0-15)
	borneOffX [16]uint64
	// borneOffO[count] - Player O borne off count (0-15)
	borneOffO [16]uint64
	// sideToMove[side] - side to move (0=X, 1=O)
	sideToMove [2]uint64
	// cubeLog2[value] - cube log2 value (0-6 typically)
	cubeLog2 [8]uint64
	// cubeOwner[owner] - cube owner (0=center, 1=X, 2=O)
	cubeOwner [3]uint64
	// awayX[score] - Player X away score (0-255)
	awayX [256]uint64
	// awayO[score] - Player O away score (0-255)
	awayO [256]uint64
}

func init() {
	// Deterministic PRNG with fixed seed
	state := uint64(0x12345678DEADBEEF)

	next := func() uint64 {
		// xorshift64
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

// ComputeZobrist computes the Zobrist hash for a BaseRecord.
func ComputeZobrist(rec *BaseRecord) uint64 {
	var h uint64

	// Layer bitboards
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

	// Exact counts
	for pt := 0; pt < 24; pt++ {
		h ^= zobristKeys.pointCount[pt][rec.PointCounts[pt]]
	}

	// Bar
	h ^= zobristKeys.barX[rec.BarX]
	h ^= zobristKeys.barO[rec.BarO]

	// Borne off
	h ^= zobristKeys.borneOffX[rec.BorneOffX]
	h ^= zobristKeys.borneOffO[rec.BorneOffO]

	// Side to move
	h ^= zobristKeys.sideToMove[rec.SideToMove]

	// Cube state
	if rec.CubeLog2 < 8 {
		h ^= zobristKeys.cubeLog2[rec.CubeLog2]
	}
	if rec.CubeOwner < 3 {
		h ^= zobristKeys.cubeOwner[rec.CubeOwner]
	}

	// Away scores
	h ^= zobristKeys.awayX[rec.AwayX]
	h ^= zobristKeys.awayO[rec.AwayO]

	return h
}
