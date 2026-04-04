package gbf_test

// M10.0 — Projection algorithm benchmarks.
//
// Uses synthetic 44-dimensional feature data (same dimensionality as GBF
// feature vectors) with deterministic seeding for reproducibility.
//
// Run:
//   go test -bench=BenchmarkProjection -benchtime=1x -v ./...
//   go test -bench=BenchmarkUMAPKNN    -benchtime=3s   ./...
//   go test -bench=.                   -benchtime=1x   ./...   # quick baseline
//
// Profile:
//   go test -bench=BenchmarkUMAPFull/n=10000 -cpuprofile=cpu.prof ./...
//   go tool pprof -http=:8080 cpu.prof

import (
	"fmt"
	"math/rand/v2"
	"testing"

	gbf "github.com/kevung/gbf"
)

// genFeatures returns n × 44 synthetic float64 feature matrix.
// Values are in [-3, 3] (standardised range typical for GBF features).
func genFeatures(n int, seed uint64) [][]float64 {
	rng := rand.New(rand.NewPCG(seed, 0))
	pts := make([][]float64, n)
	for i := range pts {
		row := make([]float64, 44)
		for j := range row {
			row[j] = rng.NormFloat64() * 1.5
		}
		pts[i] = row
	}
	return pts
}

// gen2D returns n × 2 points (for post-projection clustering benchmarks).
func gen2D(n int, seed uint64) [][]float64 {
	rng := rand.New(rand.NewPCG(seed, 0))
	pts := make([][]float64, n)
	for i := range pts {
		pts[i] = []float64{rng.NormFloat64() * 5, rng.NormFloat64() * 5}
	}
	return pts
}

// ── UMAP k-NN ────────────────────────────────────────────────────────────────

// BenchmarkUMAPKNN isolates the k-NN step (typically 70% of UMAP runtime).
func BenchmarkUMAPKNN(b *testing.B) {
	sizes := []int{1_000, 5_000, 10_000, 50_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := genFeatures(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputeUMAP(pts, gbf.UMAPConfig{ //nolint
					NComponents: 2,
					NNeighbors:  15,
					NEpochs:     1, // single epoch: isolate k-NN + graph build
					Seed:        42,
				})
			}
		})
	}
}

// ── UMAP full pipeline ────────────────────────────────────────────────────────

// BenchmarkUMAPFull measures the complete UMAP pipeline (k-NN + SGD).
func BenchmarkUMAPFull(b *testing.B) {
	sizes := []int{1_000, 5_000, 10_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := genFeatures(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputeUMAP(pts, gbf.UMAPConfig{ //nolint
					NComponents: 2,
					NNeighbors:  15,
					MinDist:     0.1,
					Seed:        42,
				})
			}
		})
	}
}

// ── t-SNE ────────────────────────────────────────────────────────────────────

// BenchmarkTSNE measures t-SNE (limited to 5K due to O(n²) memory).
func BenchmarkTSNE(b *testing.B) {
	sizes := []int{500, 1_000, 2_000, 5_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := genFeatures(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputeTSNE(pts, 2, 30, 200, 42, nil) //nolint
			}
		})
	}
}

// ── HDBSCAN ──────────────────────────────────────────────────────────────────

// BenchmarkHDBSCAN measures HDBSCAN on 2D embeddings (post-projection use case).
func BenchmarkHDBSCAN(b *testing.B) {
	sizes := []int{1_000, 5_000, 10_000, 50_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := gen2D(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputeHDBSCAN(pts, 50, 25, nil) //nolint
			}
		})
	}
}

// ── K-Means ───────────────────────────────────────────────────────────────────

// BenchmarkKMeans measures k-means++ on 2D embeddings.
func BenchmarkKMeans(b *testing.B) {
	sizes := []int{10_000, 50_000, 100_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := gen2D(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputeKMeans(pts, 8, 100, 42) //nolint
			}
		})
	}
}

// ── PCA ───────────────────────────────────────────────────────────────────────

// BenchmarkPCA measures PCA on 44-dimensional features.
func BenchmarkPCA(b *testing.B) {
	sizes := []int{10_000, 100_000}
	for _, n := range sizes {
		b.Run(fmt.Sprintf("n=%d", n), func(b *testing.B) {
			pts := genFeatures(n, 42)
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				gbf.ComputePCA(pts, 2) //nolint
			}
		})
	}
}
