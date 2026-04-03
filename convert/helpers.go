package convert

import "math"

func roundToInt32(f float64) int32 {
	return int32(math.Round(f))
}

func roundToUint16(f float64) uint16 {
	v := math.Round(f)
	if v < 0 {
		return 0
	}
	if v > 65535 {
		return 65535
	}
	return uint16(v)
}
