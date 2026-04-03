package gbf

import "math/bits"

// Feature dimensions.
const (
	NumRawFeatures     = 34 // indices 0-33
	NumDerivedFeatures = 10 // indices 34-43
	NumFeatures        = NumRawFeatures + NumDerivedFeatures // 44
)

// Position class constants returned by ClassifyPosition.
const (
	ClassContact = 0 // checkers from both players are interleaved
	ClassRace    = 1 // no contact, but not all checkers in home board
	ClassBearoff = 2 // all checkers in respective home boards (or borne off)
)

// FeatureNames returns the ordered list of feature names matching ExtractAllFeatures output.
func FeatureNames() []string {
	names := make([]string, 0, NumFeatures)
	for i := 0; i < 24; i++ {
		names = append(names, "point"+itoa2(i+1))
	}
	names = append(names,
		"bar_x", "bar_o", "borne_off_x", "borne_off_o",
		"pip_x", "pip_o",
		"cube_log2", "cube_owner",
		"away_x", "away_o",
		// derived
		"blot_x", "blot_o",
		"made_x", "made_o",
		"prime_x", "prime_o",
		"anchor_x", "anchor_o",
		"pip_diff",
		"pos_class",
	)
	return names
}

// ExtractRawFeatures returns the 34 raw features from a BaseRecord.
//
// Indices 0-23: signed point counts (-15 to +15; positive = Player X).
// Indices 24-33: bar_x, bar_o, borne_off_x, borne_off_o, pip_x, pip_o,
//
//	cube_log2, cube_owner, away_x, away_o.
func ExtractRawFeatures(rec BaseRecord) []float64 {
	f := make([]float64, NumRawFeatures)

	for i := 0; i < 24; i++ {
		count := int(rec.PointCounts[i])
		if count == 0 {
			f[i] = 0
			continue
		}
		if rec.LayersX[0]>>uint(i)&1 == 1 {
			f[i] = float64(count)
		} else {
			f[i] = -float64(count)
		}
	}

	f[24] = float64(rec.BarX)
	f[25] = float64(rec.BarO)
	f[26] = float64(rec.BorneOffX)
	f[27] = float64(rec.BorneOffO)
	f[28] = float64(rec.PipX)
	f[29] = float64(rec.PipO)
	f[30] = float64(rec.CubeLog2)
	f[31] = float64(rec.CubeOwner)
	f[32] = float64(rec.AwayX)
	f[33] = float64(rec.AwayO)

	return f
}

// ExtractDerivedFeatures returns the 10 derived features from a BaseRecord.
//
// Indices 0-9 (absolute indices 34-43):
//
//	0  blot_x:    single X checkers (blots)
//	1  blot_o:    single O checkers (blots)
//	2  made_x:    X points with ≥2 checkers (made points)
//	3  made_o:    O points with ≥2 checkers (made points)
//	4  prime_x:   longest consecutive run of X made points
//	5  prime_o:   longest consecutive run of O made points
//	6  anchor_x:  X made points in O's home board (pts 18-23)
//	7  anchor_o:  O made points in X's home board (pts 0-5)
//	8  pip_diff:  pip_x - pip_o
//	9  pos_class: 0=contact, 1=race, 2=bearoff
func ExtractDerivedFeatures(rec BaseRecord) []float64 {
	f := make([]float64, NumDerivedFeatures)

	// Blots: LayersX[0] set but NOT LayersX[1] set (exactly 1 checker).
	blotMaskX := rec.LayersX[0] & ^rec.LayersX[1]
	blotMaskO := rec.LayersO[0] & ^rec.LayersO[1]
	f[0] = float64(bits.OnesCount32(blotMaskX))
	f[1] = float64(bits.OnesCount32(blotMaskO))

	// Made points: at least 2 checkers (LayersX[1] / LayersO[1]).
	f[2] = float64(bits.OnesCount32(rec.LayersX[1]))
	f[3] = float64(bits.OnesCount32(rec.LayersO[1]))

	// Prime length: longest consecutive run of made points.
	f[4] = float64(maxConsecutiveBits(rec.LayersX[1], 24))
	f[5] = float64(maxConsecutiveBits(rec.LayersO[1], 24))

	// Anchors: X's made points in O's home board (pts 18-23 = bits 18-23).
	// O's made points in X's home board (pts 0-5 = bits 0-5).
	const oHomeBoard uint32 = 0x3F << 18 // bits 18-23
	const xHomeBoard uint32 = 0x3F       // bits 0-5
	f[6] = float64(bits.OnesCount32(rec.LayersX[1] & oHomeBoard))
	f[7] = float64(bits.OnesCount32(rec.LayersO[1] & xHomeBoard))

	// Pip diff: X pip count - O pip count.
	f[8] = float64(int(rec.PipX) - int(rec.PipO))

	// Position class.
	f[9] = float64(ClassifyPosition(rec))

	return f
}

// ExtractAllFeatures returns all 44 features (raw + derived) for a BaseRecord.
func ExtractAllFeatures(rec BaseRecord) []float64 {
	raw := ExtractRawFeatures(rec)
	derived := ExtractDerivedFeatures(rec)
	return append(raw, derived...)
}

// ClassifyPosition classifies a position as contact (0), race (1), or bearoff (2).
//
// Contact: an X checker at index i and an O checker at index j with i >= j
// (players are still interleaved — X hasn't fully passed O).
//
// Race: no contact, but neither player has all checkers in their home board.
//
// Bearoff: no contact, and all checkers (of each player) are in their
// respective home boards or borne off.
func ClassifyPosition(rec BaseRecord) int {
	// Determine extent of each player's checkers on the board.
	// For contact detection, we need the "back" checker of each player.
	// X moves from high to low: back checker = highest occupied index.
	// O moves from low to high: back checker = lowest occupied index.

	// maxX: highest board index with an X checker (-1 if none on board).
	// minO: lowest board index with an O checker (24 if none on board).
	maxX := -1
	if rec.LayersX[0] != 0 {
		maxX = bits.Len32(rec.LayersX[0]) - 1
	}
	if rec.BarX > 0 {
		maxX = 24 // bar is "behind" all board points for X
	}

	minO := 24
	if rec.LayersO[0] != 0 {
		minO = bits.TrailingZeros32(rec.LayersO[0])
	}
	if rec.BarO > 0 {
		minO = -1 // bar for O is "behind" all board points from O's direction
	}

	isContact := maxX >= minO && maxX >= 0 && minO < 24

	// Bearoff: all X in home board (pts 0-5) + no bar, all O in home board (pts 18-23) + no bar.
	const oHome uint32 = 0x3F << 18 // bits 18-23
	const xHome uint32 = 0x3F       // bits 0-5
	allXHome := rec.BarX == 0 && (rec.LayersX[0]&^xHome) == 0
	allOHome := rec.BarO == 0 && (rec.LayersO[0]&^oHome) == 0

	if isContact {
		return ClassContact
	}
	if allXHome && allOHome {
		return ClassBearoff
	}
	return ClassRace
}

// maxConsecutiveBits returns the length of the longest run of consecutive
// set bits in the lower n bits of mask.
func maxConsecutiveBits(mask uint32, n int) int {
	maxRun, run := 0, 0
	for i := 0; i < n; i++ {
		if mask>>uint(i)&1 == 1 {
			run++
			if run > maxRun {
				maxRun = run
			}
		} else {
			run = 0
		}
	}
	return maxRun
}

// itoa2 converts a point index (1-24) to a zero-padded 2-digit string.
func itoa2(n int) string {
	if n < 10 {
		return "0" + string(rune('0'+n))
	}
	return string(rune('0'+n/10)) + string(rune('0'+n%10))
}
