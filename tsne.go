package gbf

import (
	"math"
	"math/rand/v2"
)

// TSNEResult holds the output of t-SNE dimensionality reduction.
type TSNEResult struct {
	Embedding [][]float64 // N × nComponents
}

// ComputeTSNE performs t-SNE dimensionality reduction on the input data.
// points: N × D feature matrix (will not be modified).
// nComponents: output dimensionality (typically 2).
// perplexity: target perplexity (default ~30; good range: 5-50).
// maxIter: number of gradient descent iterations (default 1000).
// seed: random seed for reproducibility.
// progressFn: optional callback(iter, maxIter) for progress reporting.
func ComputeTSNE(points [][]float64, nComponents int, perplexity float64, maxIter int, seed uint64, progressFn func(int, int)) (*TSNEResult, error) {
	n := len(points)
	d := len(points[0])

	if perplexity <= 0 {
		perplexity = 30
	}
	if maxIter <= 0 {
		maxIter = 1000
	}
	if nComponents <= 0 {
		nComponents = 2
	}

	// Compute pairwise distances.
	dist := make([][]float64, n)
	for i := 0; i < n; i++ {
		dist[i] = make([]float64, n)
		for j := i + 1; j < n; j++ {
			var s float64
			for k := 0; k < d; k++ {
				diff := points[i][k] - points[j][k]
				s += diff * diff
			}
			dist[i][j] = s
			dist[j][i] = s
		}
	}

	// Compute symmetric P matrix using binary search for sigma.
	p := computePMatrix(dist, perplexity, n)

	// Initialize Y randomly.
	rng := rand.New(rand.NewPCG(seed, 0))
	y := make([][]float64, n)
	for i := 0; i < n; i++ {
		y[i] = make([]float64, nComponents)
		for c := 0; c < nComponents; c++ {
			y[i][c] = rng.NormFloat64() * 1e-4
		}
	}

	// Gradient descent with momentum.
	yPrev := make([][]float64, n)
	for i := 0; i < n; i++ {
		yPrev[i] = make([]float64, nComponents)
		copy(yPrev[i], y[i])
	}

	gains := make([][]float64, n)
	for i := 0; i < n; i++ {
		gains[i] = make([]float64, nComponents)
		for c := 0; c < nComponents; c++ {
			gains[i][c] = 1.0
		}
	}

	// Exaggerate P in early iterations.
	exFactor := 4.0
	stopExIter := 250
	if maxIter < 500 {
		stopExIter = maxIter / 4
	}

	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			p[i][j] *= exFactor
		}
	}

	for iter := 0; iter < maxIter; iter++ {
		if iter == stopExIter {
			for i := 0; i < n; i++ {
				for j := 0; j < n; j++ {
					p[i][j] /= exFactor
				}
			}
		}

		// Compute Q matrix (t-distribution).
		qNum := make([][]float64, n)
		var qSum float64
		for i := 0; i < n; i++ {
			qNum[i] = make([]float64, n)
			for j := i + 1; j < n; j++ {
				var dSq float64
				for c := 0; c < nComponents; c++ {
					diff := y[i][c] - y[j][c]
					dSq += diff * diff
				}
				val := 1.0 / (1.0 + dSq)
				qNum[i][j] = val
				qNum[j][i] = val
				qSum += 2 * val
			}
		}
		if qSum < 1e-12 {
			qSum = 1e-12
		}

		// Compute gradients.
		lr := 200.0
		momentum := 0.5
		if iter > 250 {
			momentum = 0.8
		}

		for i := 0; i < n; i++ {
			for c := 0; c < nComponents; c++ {
				var grad float64
				for j := 0; j < n; j++ {
					if i == j {
						continue
					}
					pij := p[i][j]
					qij := qNum[i][j] / qSum
					mult := (pij - qij) * qNum[i][j]
					grad += mult * (y[i][c] - y[j][c])
				}
				grad *= 4.0

				// Adaptive gains.
				sign := (grad > 0) != (y[i][c]-yPrev[i][c] > 0)
				if sign {
					gains[i][c] += 0.2
				} else {
					gains[i][c] *= 0.8
				}
				if gains[i][c] < 0.01 {
					gains[i][c] = 0.01
				}

				newVal := y[i][c] - lr*gains[i][c]*grad + momentum*(y[i][c]-yPrev[i][c])
				yPrev[i][c] = y[i][c]
				y[i][c] = newVal
			}
		}

		// Re-center.
		for c := 0; c < nComponents; c++ {
			var mean float64
			for i := 0; i < n; i++ {
				mean += y[i][c]
			}
			mean /= float64(n)
			for i := 0; i < n; i++ {
				y[i][c] -= mean
			}
		}

		if progressFn != nil && (iter%50 == 0 || iter == maxIter-1) {
			progressFn(iter, maxIter)
		}
	}

	return &TSNEResult{Embedding: y}, nil
}

// computePMatrix computes the symmetric P matrix for t-SNE.
func computePMatrix(dist [][]float64, perplexity float64, n int) [][]float64 {
	targetH := math.Log(perplexity)

	p := make([][]float64, n)
	for i := 0; i < n; i++ {
		p[i] = make([]float64, n)

		// Binary search for sigma.
		lo, hi := 1e-10, 1e10
		var sigma float64

		for iter := 0; iter < 50; iter++ {
			sigma = (lo + hi) / 2
			twoSigmaSq := 2.0 * sigma * sigma

			// Compute conditional probabilities and entropy.
			var sumP, h float64
			for j := 0; j < n; j++ {
				if j == i {
					continue
				}
				val := math.Exp(-dist[i][j] / twoSigmaSq)
				p[i][j] = val
				sumP += val
			}
			if sumP < 1e-12 {
				sumP = 1e-12
			}
			for j := 0; j < n; j++ {
				if j == i {
					continue
				}
				p[i][j] /= sumP
				if p[i][j] > 1e-10 {
					h -= p[i][j] * math.Log(p[i][j])
				}
			}

			if math.Abs(h-targetH) < 1e-5 {
				break
			}
			if h > targetH {
				hi = sigma
			} else {
				lo = sigma
			}
		}
	}

	// Symmetrize.
	for i := 0; i < n; i++ {
		for j := i + 1; j < n; j++ {
			sym := (p[i][j] + p[j][i]) / (2.0 * float64(n))
			p[i][j] = sym
			p[j][i] = sym
		}
	}

	return p
}
