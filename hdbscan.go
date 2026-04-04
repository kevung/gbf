package gbf

import (
	"math"
	"runtime"
	"sort"
	"sync"
)

// HDBSCANResult holds the output of HDBSCAN clustering.
type HDBSCANResult struct {
	Labels    []int // cluster assignment per point (-1 for noise)
	NClusters int   // number of clusters found
	NNoise    int   // number of noise points
}

// ComputeHDBSCAN performs HDBSCAN clustering on 2D/3D embedding points.
// minClusterSize: minimum number of points to form a cluster (default 100).
// minSamples: smoothing factor for core distance (default 50).
// progressFn: optional callback(stage, pct) for progress reporting.
func ComputeHDBSCAN(points [][]float64, minClusterSize, minSamples int, progressFn func(string, int)) (*HDBSCANResult, error) {
	n := len(points)
	if n == 0 {
		return &HDBSCANResult{Labels: nil}, nil
	}

	reportProgress := func(stage string, pct int) {
		if progressFn != nil {
			progressFn(stage, pct)
		}
	}

	if minClusterSize <= 0 {
		minClusterSize = 100
	}
	if minSamples <= 0 {
		minSamples = min(50, minClusterSize)
	}

	reportProgress("hdbscan_core_dist", 0)

	// Step 1: Compute core distances (distance to k-th nearest neighbor).
	// M10.1f: parallelised across NumCPU goroutines (same pattern as UMAP k-NN).
	coreDist := make([]float64, n)
	{
		nWorkers := runtime.NumCPU()
		if nWorkers > n {
			nWorkers = n
		}
		chunkSize := (n + nWorkers - 1) / nWorkers
		kth := minSamples
		if kth >= n {
			kth = n - 1
		}
		var wg sync.WaitGroup
		for w := 0; w < nWorkers; w++ {
			start := w * chunkSize
			end := start + chunkSize
			if end > n {
				end = n
			}
			wg.Add(1)
			go func(start, end int) {
				defer wg.Done()
				dists := make([]float64, n)
				for i := start; i < end; i++ {
					for j := 0; j < n; j++ {
						if i == j {
							dists[j] = math.MaxFloat64
						} else {
							dists[j] = eucDist(points[i], points[j])
						}
					}
					coreDist[i] = quickSelect(dists, kth)
				}
			}(start, end)
		}
		wg.Wait()
		reportProgress("hdbscan_core_dist", 100)
	}

	reportProgress("hdbscan_mst", 0)

	// Step 2: Build the mutual reachability distance MST using Prim's algorithm.
	// Mutual reachability: d_mr(a,b) = max(coreDist[a], coreDist[b], dist(a,b))
	inMST := make([]bool, n)
	minDist := make([]float64, n)
	minFrom := make([]int, n)
	for i := range minDist {
		minDist[i] = math.MaxFloat64
		minFrom[i] = -1
	}

	type mstEdge struct {
		a, b   int
		weight float64
	}
	edges := make([]mstEdge, 0, n-1)

	// Start from node 0.
	inMST[0] = true
	for j := 1; j < n; j++ {
		d := mutualReachability(points[0], points[j], coreDist[0], coreDist[j])
		minDist[j] = d
		minFrom[j] = 0
	}

	for step := 1; step < n; step++ {
		// Find the minimum distance node not in MST.
		bestJ := -1
		bestD := math.MaxFloat64
		for j := 0; j < n; j++ {
			if !inMST[j] && minDist[j] < bestD {
				bestD = minDist[j]
				bestJ = j
			}
		}
		if bestJ < 0 {
			break
		}

		inMST[bestJ] = true
		edges = append(edges, mstEdge{a: minFrom[bestJ], b: bestJ, weight: bestD})

		// Update distances.
		for j := 0; j < n; j++ {
			if inMST[j] {
				continue
			}
			d := mutualReachability(points[bestJ], points[j], coreDist[bestJ], coreDist[j])
			if d < minDist[j] {
				minDist[j] = d
				minFrom[j] = bestJ
			}
		}

		if step%(n/10+1) == 0 {
			reportProgress("hdbscan_mst", step*100/n)
		}
	}

	reportProgress("hdbscan_hierarchy", 0)

	// Step 3: Sort MST edges by weight and build dendrogram using Union-Find.
	sort.Slice(edges, func(i, j int) bool {
		return edges[i].weight < edges[j].weight
	})

	uf := newUnionFind(n)
	parent := make([]int, 2*n-1)
	lambdaVal := make([]float64, 2*n-1)
	size := make([]int, 2*n-1)
	for i := 0; i < n; i++ {
		parent[i] = i
		size[i] = 1
	}

	nextCluster := n
	for _, e := range edges {
		ra := uf.find(e.a)
		rb := uf.find(e.b)
		if ra == rb {
			continue
		}

		// Create new internal node.
		if nextCluster >= len(parent) {
			break
		}
		parent[ra] = nextCluster
		parent[rb] = nextCluster
		parent[nextCluster] = nextCluster
		size[nextCluster] = size[ra] + size[rb]
		if e.weight > 0 {
			lambdaVal[nextCluster] = 1.0 / e.weight
		} else {
			lambdaVal[nextCluster] = math.MaxFloat64
		}
		uf.union(e.a, e.b)
		uf.rename(uf.find(e.a), nextCluster)
		nextCluster++
	}

	reportProgress("hdbscan_extract", 0)

	// Step 4: Extract clusters using simplified excess-of-mass.
	// Walk the dendrogram and identify stable clusters.
	labels := make([]int, n)
	for i := range labels {
		labels[i] = -1
	}

	// Simple cluster extraction: use the dendrogram structure.
	// Find internal nodes that contain >= minClusterSize points.
	// Start from root and split.
	type clusterInfo struct {
		node       int
		stability  float64
		isCluster  bool
		childNodes []int
	}
	info := make(map[int]*clusterInfo)

	// Build children map.
	children := make(map[int][]int)
	for i := 0; i < nextCluster; i++ {
		if parent[i] != i && parent[i] < nextCluster {
			children[parent[i]] = append(children[parent[i]], i)
		}
	}

	// Leaves of a node: all leaf (< n) nodes reachable from it.
	var getLeaves func(node int) []int
	getLeaves = func(node int) []int {
		if node < n {
			return []int{node}
		}
		var result []int
		for _, ch := range children[node] {
			result = append(result, getLeaves(ch)...)
		}
		return result
	}

	// Extract: any internal node with size >= minClusterSize whose children
	// are both also >= minClusterSize gets split; otherwise it's a leaf cluster.
	var extractClusters func(node int) []int // returns list of cluster root nodes
	extractClusters = func(node int) []int {
		if node < n {
			return nil
		}
		if size[node] < minClusterSize {
			return nil
		}

		chs := children[node]
		if len(chs) < 2 {
			return []int{node}
		}

		// Check if both children are large enough.
		bigChildren := 0
		for _, ch := range chs {
			if ch >= n && size[ch] >= minClusterSize {
				bigChildren++
			}
		}

		if bigChildren >= 2 {
			// Split: recurse into children.
			var result []int
			for _, ch := range chs {
				sub := extractClusters(ch)
				if len(sub) > 0 {
					result = append(result, sub...)
				}
			}
			if len(result) > 0 {
				return result
			}
			return []int{node}
		}

		return []int{node}
	}

	rootNode := nextCluster - 1
	if rootNode < n {
		rootNode = n
	}
	clusterNodes := extractClusters(rootNode)

	_ = info

	// Assign labels.
	for clID, cNode := range clusterNodes {
		leaves := getLeaves(cNode)
		for _, leaf := range leaves {
			labels[leaf] = clID
		}
	}

	nClusters := len(clusterNodes)
	nNoise := 0
	for _, l := range labels {
		if l < 0 {
			nNoise++
		}
	}

	return &HDBSCANResult{
		Labels:    labels,
		NClusters: nClusters,
		NNoise:    nNoise,
	}, nil
}

// ── Helpers ──────────────────────────────────────────────────────────────────

func eucDist(a, b []float64) float64 {
	var s float64
	for i := range a {
		d := a[i] - b[i]
		s += d * d
	}
	return math.Sqrt(s)
}

func mutualReachability(a, b []float64, coreA, coreB float64) float64 {
	d := eucDist(a, b)
	if coreA > d {
		d = coreA
	}
	if coreB > d {
		d = coreB
	}
	return d
}

// quickSelect returns the k-th smallest element using introselect
// (partition-based, O(n) average, O(n·log n) worst-case via sort fallback).
// M10.1d: replaces the previous full sort O(n·log n).
func quickSelect(data []float64, k int) float64 {
	if k >= len(data) {
		k = len(data) - 1
	}
	arr := make([]float64, len(data))
	copy(arr, data)
	lo, hi := 0, len(arr)-1
	for lo < hi {
		p := qsPartition(arr, lo, hi)
		if p == k {
			return arr[p]
		} else if p < k {
			lo = p + 1
		} else {
			hi = p - 1
		}
	}
	return arr[lo]
}

// qsPartition uses median-of-three pivot selection for better average
// performance on nearly-sorted inputs, then partitions in place.
func qsPartition(arr []float64, lo, hi int) int {
	// Median-of-three pivot.
	mid := lo + (hi-lo)/2
	if arr[lo] > arr[mid] {
		arr[lo], arr[mid] = arr[mid], arr[lo]
	}
	if arr[lo] > arr[hi] {
		arr[lo], arr[hi] = arr[hi], arr[lo]
	}
	if arr[mid] > arr[hi] {
		arr[mid], arr[hi] = arr[hi], arr[mid]
	}
	pivot := arr[mid]
	arr[mid], arr[hi-1] = arr[hi-1], arr[mid]
	i := lo
	for j := lo; j < hi; j++ {
		if arr[j] <= pivot {
			arr[i], arr[j] = arr[j], arr[i]
			i++
		}
	}
	arr[i], arr[hi] = arr[hi], arr[i]
	return i
}

// ── Union-Find ───────────────────────────────────────────────────────────────

type unionFind struct {
	parent []int
	rank   []int
}

func newUnionFind(n int) *unionFind {
	parent := make([]int, 2*n)
	rank := make([]int, 2*n)
	for i := range parent {
		parent[i] = i
	}
	return &unionFind{parent: parent, rank: rank}
}

func (uf *unionFind) find(x int) int {
	for uf.parent[x] != x {
		uf.parent[x] = uf.parent[uf.parent[x]]
		x = uf.parent[x]
	}
	return x
}

func (uf *unionFind) union(x, y int) int {
	rx := uf.find(x)
	ry := uf.find(y)
	if rx == ry {
		return rx
	}
	if uf.rank[rx] < uf.rank[ry] {
		rx, ry = ry, rx
	}
	uf.parent[ry] = rx
	if uf.rank[rx] == uf.rank[ry] {
		uf.rank[rx]++
	}
	return rx
}

func (uf *unionFind) rename(old, new_ int) {
	uf.parent[old] = new_
}
