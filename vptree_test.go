package gbf

import (
	"math"
	"math/rand/v2"
	"sort"
	"testing"
)

// bruteKNN is a reference brute-force k-NN used to validate VP-tree results.
func bruteKNN(points [][]float64, query []float64, k, excludeIdx int) ([]int, []float64) {
	type pair struct {
		idx  int
		dist float64
	}
	var pairs []pair
	for i, p := range points {
		if i == excludeIdx {
			continue
		}
		pairs = append(pairs, pair{i, eucDist(query, p)})
	}
	sort.Slice(pairs, func(i, j int) bool { return pairs[i].dist < pairs[j].dist })
	if k > len(pairs) {
		k = len(pairs)
	}
	idx := make([]int, k)
	dist := make([]float64, k)
	for i := range idx {
		idx[i] = pairs[i].idx
		dist[i] = pairs[i].dist
	}
	return idx, dist
}

// TestVPTreeBuildQuery verifies that VP-tree k-NN matches brute-force exactly
// on small random datasets.
func TestVPTreeBuildQuery(t *testing.T) {
	rng := rand.New(rand.NewPCG(42, 0))
	n := 500
	dims := 10
	k := 10

	points := make([][]float64, n)
	for i := range points {
		row := make([]float64, dims)
		for j := range row {
			row[j] = rng.NormFloat64()
		}
		points[i] = row
	}

	tree := BuildVPTree(points)

	// Verify k-NN for a sample of query points.
	for qi := 0; qi < n; qi += 50 {
		gotIdx, gotDist := tree.KNNExclude(points[qi], k, qi)
		wantIdx, wantDist := bruteKNN(points, points[qi], k, qi)

		if len(gotIdx) != len(wantIdx) {
			t.Fatalf("qi=%d: got %d neighbours, want %d", qi, len(gotIdx), len(wantIdx))
		}
		for j := range gotIdx {
			if math.Abs(gotDist[j]-wantDist[j]) > 1e-9 {
				t.Errorf("qi=%d j=%d: dist=%.6f want=%.6f", qi, j, gotDist[j], wantDist[j])
			}
			if gotIdx[j] != wantIdx[j] {
				// Allow ties (same distance, different index order).
				if math.Abs(gotDist[j]-wantDist[j]) > 1e-9 {
					t.Errorf("qi=%d j=%d: idx=%d want=%d (dist %.6f vs %.6f)",
						qi, j, gotIdx[j], wantIdx[j], gotDist[j], wantDist[j])
				}
			}
		}
	}
}

// TestVPTreeHighDim verifies VP-tree on 44-dimensional data (UMAP feature size).
func TestVPTreeHighDim(t *testing.T) {
	rng := rand.New(rand.NewPCG(7, 0))
	n := 300
	dims := 44
	k := 15

	points := make([][]float64, n)
	for i := range points {
		row := make([]float64, dims)
		for j := range row {
			row[j] = rng.NormFloat64() * 1.5
		}
		points[i] = row
	}

	tree := BuildVPTree(points)

	// Check all query points.
	for qi := 0; qi < n; qi++ {
		gotIdx, gotDist := tree.KNNExclude(points[qi], k, qi)
		wantIdx, _ := bruteKNN(points, points[qi], k, qi)

		if len(gotIdx) != k {
			t.Fatalf("qi=%d: got %d neighbours, want %d", qi, len(gotIdx), k)
		}
		// Verify the sets match (same distance sum as a proxy for correctness).
		var gotSum, wantSum float64
		for j := range gotIdx {
			gotSum += gotDist[j]
			_ = wantIdx[j] // suppress unused
		}
		_, wantDist := bruteKNN(points, points[qi], k, qi)
		for _, d := range wantDist {
			wantSum += d
		}
		if math.Abs(gotSum-wantSum)/wantSum > 1e-6 {
			t.Errorf("qi=%d: dist sum mismatch: got %.6f, want %.6f", qi, gotSum, wantSum)
		}
	}
}

// TestVPTreeEdgeCases covers small n, n < k, and n=2.
func TestVPTreeEdgeCases(t *testing.T) {
	// n=2: each point has one neighbour.
	pts2 := [][]float64{{0, 0}, {3, 4}}
	tree2 := BuildVPTree(pts2)
	idx, dist := tree2.KNNExclude(pts2[0], 1, 0)
	if len(idx) != 1 || idx[0] != 1 {
		t.Errorf("n=2: expected neighbour 1, got %v", idx)
	}
	if math.Abs(dist[0]-5.0) > 1e-9 {
		t.Errorf("n=2: expected dist 5.0, got %.6f", dist[0])
	}

	// n < k: returns what's available.
	pts5 := make([][]float64, 5)
	for i := range pts5 {
		pts5[i] = []float64{float64(i), 0}
	}
	tree5 := BuildVPTree(pts5)
	idx5, _ := tree5.KNNExclude(pts5[0], 20, 0) // k=20 > n-1=4
	if len(idx5) != 4 {
		t.Errorf("n=5 k=20: expected 4 neighbours, got %d", len(idx5))
	}
}

// TestVPTreeSortedDistances verifies that returned distances are sorted ascending.
func TestVPTreeSortedDistances(t *testing.T) {
	rng := rand.New(rand.NewPCG(99, 0))
	n := 200
	k := 20
	points := make([][]float64, n)
	for i := range points {
		points[i] = []float64{rng.NormFloat64() * 5, rng.NormFloat64() * 5}
	}
	tree := BuildVPTree(points)
	for qi := 0; qi < n; qi += 10 {
		_, dists := tree.KNNExclude(points[qi], k, qi)
		for j := 1; j < len(dists); j++ {
			if dists[j] < dists[j-1]-1e-12 {
				t.Errorf("qi=%d: distances not sorted at j=%d: %.6f < %.6f",
					qi, j, dists[j], dists[j-1])
			}
		}
	}
}

// TestVPTreeExcludeConsistency verifies that excludeIdx is never returned.
func TestVPTreeExcludeConsistency(t *testing.T) {
	rng := rand.New(rand.NewPCG(1, 0))
	n := 200
	k := 15
	points := make([][]float64, n)
	for i := range points {
		points[i] = []float64{rng.NormFloat64(), rng.NormFloat64()}
	}
	tree := BuildVPTree(points)
	for qi := 0; qi < n; qi++ {
		idx, _ := tree.KNNExclude(points[qi], k, qi)
		for _, id := range idx {
			if id == qi {
				t.Errorf("qi=%d: excludeIdx returned as neighbour", qi)
			}
		}
	}
}
