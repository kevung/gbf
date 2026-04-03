package gbf

import "math"

// NormalizationParams holds per-feature statistics for standard scaling.
type NormalizationParams struct {
	Mean []float64 // per-feature mean
	Std  []float64 // per-feature standard deviation (1 if std==0 to avoid division)
	Min  []float64 // per-feature minimum (for min-max scaling)
	Max  []float64 // per-feature maximum
}

// ComputeNormParams computes standard and min-max normalization parameters
// from a matrix of feature vectors (rows = samples, cols = features).
func ComputeNormParams(features [][]float64) NormalizationParams {
	if len(features) == 0 {
		return NormalizationParams{}
	}
	n := len(features[0])
	p := NormalizationParams{
		Mean: make([]float64, n),
		Std:  make([]float64, n),
		Min:  make([]float64, n),
		Max:  make([]float64, n),
	}

	// Initialize Min/Max from first sample.
	copy(p.Min, features[0])
	copy(p.Max, features[0])

	// Compute mean and min/max.
	for _, row := range features {
		for j, v := range row {
			p.Mean[j] += v
			if v < p.Min[j] {
				p.Min[j] = v
			}
			if v > p.Max[j] {
				p.Max[j] = v
			}
		}
	}
	m := float64(len(features))
	for j := range p.Mean {
		p.Mean[j] /= m
	}

	// Compute std.
	for _, row := range features {
		for j, v := range row {
			d := v - p.Mean[j]
			p.Std[j] += d * d
		}
	}
	for j := range p.Std {
		variance := p.Std[j] / m
		std := math.Sqrt(variance)
		if std < 1e-10 {
			std = 1 // avoid division by zero for constant features
		}
		p.Std[j] = std
	}

	return p
}

// StandardScale applies zero-mean/unit-variance scaling: (x - mean) / std.
func StandardScale(f []float64, p NormalizationParams) []float64 {
	out := make([]float64, len(f))
	for i, v := range f {
		out[i] = (v - p.Mean[i]) / p.Std[i]
	}
	return out
}

// InverseStandardScale reverses standard scaling: x * std + mean.
func InverseStandardScale(f []float64, p NormalizationParams) []float64 {
	out := make([]float64, len(f))
	for i, v := range f {
		out[i] = v*p.Std[i] + p.Mean[i]
	}
	return out
}

// MinMaxScale applies min-max scaling to [0, 1]: (x - min) / (max - min).
func MinMaxScale(f []float64, p NormalizationParams) []float64 {
	out := make([]float64, len(f))
	for i, v := range f {
		r := p.Max[i] - p.Min[i]
		if r < 1e-10 {
			out[i] = 0
		} else {
			out[i] = (v - p.Min[i]) / r
		}
	}
	return out
}
