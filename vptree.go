package gbf

import (
	"math"
	"math/rand/v2"
	"sort"
)

// ── VP-Tree (Vantage Point Tree) ─────────────────────────────────────────────
//
// M10.2a: exact k-NN in metric spaces.
//   Build: O(n·log n) — random vantage point, median distance split, recurse.
//   Query: O(log n) amortised — max-heap + triangle-inequality pruning.
//
// Used by:
//   - umapKNN (M10.2b): replace brute-force for n ≥ 1000
//   - HDBSCAN core distances (M10.2c): replace brute-force for n ≥ 1000

const vpLeafCap = 32 // stop splitting when ≤ vpLeafCap points remain

// VPTree is an immutable k-NN index over a fixed point set.
// The point slice must not be modified after Build.
type VPTree struct {
	points [][]float64
	root   *vpNode
}

type vpNode struct {
	vpIdx  int     // index of vantage point in the original points slice
	mu     float64 // median distance — split boundary
	inner  *vpNode // dist(vp, p) < mu
	outer  *vpNode // dist(vp, p) ≥ mu
	bucket []int   // non-nil → leaf: brute-force over these indices
}

// BuildVPTree builds a VP-tree over points. Thread-safe after construction.
func BuildVPTree(points [][]float64) *VPTree {
	n := len(points)
	if n == 0 {
		return &VPTree{points: points}
	}
	indices := make([]int, n)
	for i := range indices {
		indices[i] = i
	}
	rng := rand.New(rand.NewPCG(0, 0))
	return &VPTree{
		points: points,
		root:   vpBuild(points, indices, rng),
	}
}

// vpBuild recursively builds the VP-tree.
// indices is a working slice; it may be modified in place.
func vpBuild(points [][]float64, indices []int, rng *rand.Rand) *vpNode {
	n := len(indices)
	if n == 0 {
		return nil
	}
	if n <= vpLeafCap {
		// Leaf node: copy indices into bucket.
		bucket := make([]int, n)
		copy(bucket, indices)
		return &vpNode{vpIdx: -1, bucket: bucket}
	}

	// Pick a random vantage point and swap it to position 0.
	vpPos := rng.IntN(n)
	indices[0], indices[vpPos] = indices[vpPos], indices[0]
	vpIdx := indices[0]
	rest := indices[1:]
	vp := points[vpIdx]

	// Compute distances from vp to all remaining points.
	dists := make([]float64, len(rest))
	for i, idx := range rest {
		dists[i] = eucDist(vp, points[idx])
	}

	// Find median distance using quickselect (operates on a copy internally).
	mu := quickSelect(dists, len(dists)/2)

	// Partition rest into inner (dist < mu) and outer (dist ≥ mu).
	inner := make([]int, 0, len(rest)/2+1)
	outer := make([]int, 0, len(rest)/2+1)
	for i, idx := range rest {
		if dists[i] < mu {
			inner = append(inner, idx)
		} else {
			outer = append(outer, idx)
		}
	}

	return &vpNode{
		vpIdx: vpIdx,
		mu:    mu,
		inner: vpBuild(points, inner, rng),
		outer: vpBuild(points, outer, rng),
	}
}

// ── k-NN Query ───────────────────────────────────────────────────────────────

// KNNExclude finds the k nearest neighbours of query, excluding excludeIdx.
// Returns indices and (non-squared) Euclidean distances, sorted ascending.
// If fewer than k neighbours exist (excluding excludeIdx), returns what is found.
func (t *VPTree) KNNExclude(query []float64, k, excludeIdx int) ([]int, []float64) {
	if t.root == nil {
		return nil, nil
	}
	h := newVPHeap(k)
	vpSearch(t.root, t.points, query, excludeIdx, h)
	return h.results()
}

// vpSearch recursively searches the VP-tree, updating heap h.
func vpSearch(node *vpNode, points [][]float64, query []float64, excludeIdx int, h *vpHeap) {
	if node == nil {
		return
	}

	// Leaf node: brute-force over bucket.
	if node.bucket != nil {
		for _, idx := range node.bucket {
			if idx == excludeIdx {
				continue
			}
			d := eucDist(query, points[idx])
			h.consider(idx, d)
		}
		return
	}

	// Internal node: check vantage point.
	d := eucDist(query, points[node.vpIdx])
	if node.vpIdx != excludeIdx {
		h.consider(node.vpIdx, d)
	}

	tau := h.maxDist()

	if d < node.mu {
		// Query is inside the ball — search inner first (likely closer).
		vpSearch(node.inner, points, query, excludeIdx, h)
		tau = h.maxDist()
		// Prune outer only if mu - d > tau (all outer points ≥ mu-d away).
		if node.mu-d <= tau {
			vpSearch(node.outer, points, query, excludeIdx, h)
		}
	} else {
		// Query is outside the ball — search outer first (likely closer).
		vpSearch(node.outer, points, query, excludeIdx, h)
		tau = h.maxDist()
		// Prune inner only if d - mu > tau (all inner points ≥ d-mu away).
		if d-node.mu <= tau {
			vpSearch(node.inner, points, query, excludeIdx, h)
		}
	}
}

// ── Max-heap for k-NN collection ─────────────────────────────────────────────
//
// Maintains the k nearest neighbours seen so far.
// Root = current k-th nearest (maximum distance in the set).

type vpHeap struct {
	idx  []int
	dist []float64
	k    int
	size int
}

func newVPHeap(k int) *vpHeap {
	return &vpHeap{
		idx:  make([]int, k),
		dist: make([]float64, k),
		k:    k,
	}
}

// consider adds (idx, d) if d is closer than the current k-th neighbour.
func (h *vpHeap) consider(idx int, d float64) {
	if h.size < h.k {
		h.idx[h.size] = idx
		h.dist[h.size] = d
		h.size++
		if h.size == h.k {
			// Heap is now full — build max-heap.
			for i := h.k/2 - 1; i >= 0; i-- {
				vpHeapSiftDown(h.idx, h.dist, i, h.k)
			}
		}
		return
	}
	// Heap full: replace root if closer.
	if d < h.dist[0] {
		h.idx[0] = idx
		h.dist[0] = d
		vpHeapSiftDown(h.idx, h.dist, 0, h.k)
	}
}

// maxDist returns the current k-th distance (tau for pruning).
// Returns +Inf if the heap is not yet full.
func (h *vpHeap) maxDist() float64 {
	if h.size < h.k {
		return math.MaxFloat64
	}
	return h.dist[0]
}

// results returns (indices, distances) sorted by ascending distance.
func (h *vpHeap) results() ([]int, []float64) {
	n := h.size
	idxOut := make([]int, n)
	distOut := make([]float64, n)
	copy(idxOut, h.idx[:n])
	copy(distOut, h.dist[:n])
	sort.Sort(&vpHeapSorter{idxOut, distOut})
	return idxOut, distOut
}

// vpHeapSiftDown maintains the max-heap property at position i for a heap of size n.
func vpHeapSiftDown(idx []int, dist []float64, i, n int) {
	for {
		largest := i
		l, r := 2*i+1, 2*i+2
		if l < n && dist[l] > dist[largest] {
			largest = l
		}
		if r < n && dist[r] > dist[largest] {
			largest = r
		}
		if largest == i {
			return
		}
		idx[i], idx[largest] = idx[largest], idx[i]
		dist[i], dist[largest] = dist[largest], dist[i]
		i = largest
	}
}

// vpHeapSorter sorts k nearest neighbours by ascending distance.
type vpHeapSorter struct {
	idx  []int
	dist []float64
}

func (s *vpHeapSorter) Len() int           { return len(s.idx) }
func (s *vpHeapSorter) Less(i, j int) bool { return s.dist[i] < s.dist[j] }
func (s *vpHeapSorter) Swap(i, j int) {
	s.idx[i], s.idx[j] = s.idx[j], s.idx[i]
	s.dist[i], s.dist[j] = s.dist[j], s.dist[i]
}
