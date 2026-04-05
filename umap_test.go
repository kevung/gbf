package gbf

import (
	"math"
	"math/rand/v2"
	"testing"
)

func TestUMAPFindAB(t *testing.T) {
	// Fit 1/(1+a*x^(2b)) to the UMAP membership function.
	// Our grid search finds the global optimum; Python's scipy.curve_fit
	// finds a different local minimum (a≈1.929, b≈0.791), but ours has
	// lower MSE.
	a, b := umapFindAB(1.0, 0.1)
	t.Logf("a=%.4f b=%.4f", a, b)
	if a <= 0 || b <= 0 {
		t.Fatalf("invalid a=%.4f b=%.4f", a, b)
	}
	// Verify the curve approximates the target well.
	// At x=0: should be ~1.0
	f0 := 1.0 / (1.0 + a*math.Pow(0.01, 2*b))
	if f0 < 0.95 {
		t.Errorf("f(0.01)=%.3f, expected ~1.0", f0)
	}
	// At x=1.0: target = exp(-(1.0-0.1)/1.0) ≈ 0.407
	f1 := 1.0 / (1.0 + a*math.Pow(1.0, 2*b))
	target := math.Exp(-0.9)
	if math.Abs(f1-target) > 0.15 {
		t.Errorf("f(1.0)=%.3f, target=%.3f", f1, target)
	}
}

func TestUMAPFindABMinDist05(t *testing.T) {
	a, b := umapFindAB(1.0, 0.5)
	t.Logf("a=%.4f b=%.4f", a, b)
	if a <= 0 || b <= 0 {
		t.Fatalf("invalid a=%.4f b=%.4f", a, b)
	}
	// At x=1.0: target = exp(-(1.0-0.5)/1.0) ≈ 0.607
	f1 := 1.0 / (1.0 + a*math.Pow(1.0, 2*b))
	target := math.Exp(-0.5)
	if math.Abs(f1-target) > 0.15 {
		t.Errorf("f(1.0)=%.3f, target=%.3f", f1, target)
	}
}

func TestUMAPSmallCluster(t *testing.T) {
	rng := rand.New(rand.NewPCG(42, 0))
	var points [][]float64
	for c := 0; c < 3; c++ {
		cx, cy := float64(c*10), float64(c*10)
		for i := 0; i < 50; i++ {
			points = append(points, []float64{
				cx + rng.NormFloat64()*0.5,
				cy + rng.NormFloat64()*0.5,
			})
		}
	}

	result, err := ComputeUMAP(points, UMAPConfig{
		NComponents: 2,
		NNeighbors:  10,
		MinDist:     0.1,
		Seed:        42,
		NEpochs:     200,
	})
	if err != nil {
		t.Fatalf("ComputeUMAP: %v", err)
	}
	if len(result.Embedding) != 150 {
		t.Fatalf("expected 150 points, got %d", len(result.Embedding))
	}

	for i, row := range result.Embedding {
		for c, v := range row {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				t.Fatalf("NaN/Inf at point %d dim %d", i, c)
			}
		}
	}

	clusterCentroid := func(start, end int) (float64, float64) {
		var sx, sy float64
		for i := start; i < end; i++ {
			sx += result.Embedding[i][0]
			sy += result.Embedding[i][1]
		}
		n := float64(end - start)
		return sx / n, sy / n
	}

	var maxIntra float64
	for c := 0; c < 3; c++ {
		cx, cy := clusterCentroid(c*50, (c+1)*50)
		for i := c * 50; i < (c+1)*50; i++ {
			dx := result.Embedding[i][0] - cx
			dy := result.Embedding[i][1] - cy
			d := math.Sqrt(dx*dx + dy*dy)
			if d > maxIntra {
				maxIntra = d
			}
		}
	}

	var minInter float64 = math.MaxFloat64
	for c1 := 0; c1 < 3; c1++ {
		for c2 := c1 + 1; c2 < 3; c2++ {
			cx1, cy1 := clusterCentroid(c1*50, (c1+1)*50)
			cx2, cy2 := clusterCentroid(c2*50, (c2+1)*50)
			dx := cx1 - cx2
			dy := cy1 - cy2
			d := math.Sqrt(dx*dx + dy*dy)
			if d < minInter {
				minInter = d
			}
		}
	}

	t.Logf("maxIntra=%.3f minInter=%.3f ratio=%.2f", maxIntra, minInter, minInter/maxIntra)
	if minInter <= maxIntra {
		t.Errorf("clusters not separated: minInter=%.3f <= maxIntra=%.3f", minInter, maxIntra)
	}
}

func TestUMAPHighDim(t *testing.T) {
	rng := rand.New(rand.NewPCG(123, 0))
	n := 200
	d := 44
	points := make([][]float64, n)
	for i := 0; i < n; i++ {
		points[i] = make([]float64, d)
		offset := 0.0
		if i >= n/2 {
			offset = 5.0
		}
		for j := 0; j < d; j++ {
			points[i][j] = rng.NormFloat64()*0.5 + offset
		}
	}

	result, err := ComputeUMAP(points, UMAPConfig{
		NComponents: 2,
		NNeighbors:  15,
		MinDist:     0.1,
		Seed:        42,
		NEpochs:     300,
	})
	if err != nil {
		t.Fatalf("ComputeUMAP: %v", err)
	}
	if len(result.Embedding) != n {
		t.Fatalf("expected %d points, got %d", n, len(result.Embedding))
	}

	centroid := func(start, end int) (float64, float64) {
		var sx, sy float64
		for i := start; i < end; i++ {
			sx += result.Embedding[i][0]
			sy += result.Embedding[i][1]
		}
		cnt := float64(end - start)
		return sx / cnt, sy / cnt
	}
	cx1, cy1 := centroid(0, n/2)
	cx2, cy2 := centroid(n/2, n)
	dist := math.Sqrt((cx1-cx2)*(cx1-cx2) + (cy1-cy2)*(cy1-cy2))
	t.Logf("inter-cluster distance = %.3f", dist)
	if dist < 1.0 {
		t.Errorf("clusters not separated: distance=%.3f", dist)
	}
}

// TestUMAPHighDimLarge verifies that the PCA pre-reduction path (n>=1000, d>15)
// produces a meaningful embedding that preserves cluster structure.
func TestUMAPHighDimLarge(t *testing.T) {
	rng := rand.New(rand.NewPCG(99, 0))
	n := 1200 // exceeds the 1000-point threshold that triggers PCA pre-reduction
	d := 44
	points := make([][]float64, n)
	for i := 0; i < n; i++ {
		points[i] = make([]float64, d)
		offset := 0.0
		if i >= n/2 {
			offset = 6.0
		}
		for j := 0; j < d; j++ {
			points[i][j] = rng.NormFloat64()*0.5 + offset
		}
	}

	result, err := ComputeUMAP(points, UMAPConfig{
		NComponents: 2,
		NNeighbors:  15,
		MinDist:     0.1,
		Seed:        42,
		NEpochs:     200,
	})
	if err != nil {
		t.Fatalf("ComputeUMAP: %v", err)
	}
	if len(result.Embedding) != n {
		t.Fatalf("expected %d points, got %d", n, len(result.Embedding))
	}
	for i, row := range result.Embedding {
		for c, v := range row {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				t.Fatalf("NaN/Inf at point %d dim %d", i, c)
			}
		}
	}

	centroid := func(start, end int) (float64, float64) {
		var sx, sy float64
		for i := start; i < end; i++ {
			sx += result.Embedding[i][0]
			sy += result.Embedding[i][1]
		}
		cnt := float64(end - start)
		return sx / cnt, sy / cnt
	}
	cx1, cy1 := centroid(0, n/2)
	cx2, cy2 := centroid(n/2, n)
	dist := math.Sqrt((cx1-cx2)*(cx1-cx2) + (cy1-cy2)*(cy1-cy2))
	t.Logf("inter-cluster distance = %.3f (PCA pre-reduction path)", dist)
	if dist < 1.0 {
		t.Errorf("clusters not separated: distance=%.3f", dist)
	}
}

func TestUMAPTinyInput(t *testing.T) {
	points := [][]float64{{0, 0}, {1, 1}}
	result, err := ComputeUMAP(points, UMAPConfig{
		NComponents: 2,
		NNeighbors:  1,
		Seed:        42,
		NEpochs:     50,
	})
	if err != nil {
		t.Fatalf("ComputeUMAP: %v", err)
	}
	if len(result.Embedding) != 2 {
		t.Fatalf("expected 2 points, got %d", len(result.Embedding))
	}
}

func TestUMAPProgressCallback(t *testing.T) {
	rng := rand.New(rand.NewPCG(77, 0))
	points := make([][]float64, 30)
	for i := range points {
		points[i] = []float64{rng.NormFloat64(), rng.NormFloat64()}
	}

	var lastOptPct int
	_, err := ComputeUMAP(points, UMAPConfig{
		NComponents: 2,
		NEpochs:     100,
		Seed:        42,
		ProgressFn: func(stage string, pct int) {
			if stage == "optimize" && pct > lastOptPct {
				lastOptPct = pct
			}
		},
	})
	if err != nil {
		t.Fatalf("ComputeUMAP: %v", err)
	}
	if lastOptPct != 100 {
		t.Errorf("expected final optimize pct=100, got %d", lastOptPct)
	}
}

func BenchmarkUMAP500x10(b *testing.B) {
	rng := rand.New(rand.NewPCG(42, 0))
	points := make([][]float64, 500)
	for i := range points {
		points[i] = make([]float64, 10)
		for j := range points[i] {
			points[i][j] = rng.NormFloat64()
		}
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, _ = ComputeUMAP(points, UMAPConfig{
			NComponents: 2,
			NNeighbors:  15,
			Seed:        42,
			NEpochs:     50,
		})
	}
}
