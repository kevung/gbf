package gbf

import (
	"fmt"
	"math"
	"math/rand/v2"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
	"unsafe"
)

// ── UMAP (pure Go) ──────────────────────────────────────────────────────────
//
// Uniform Manifold Approximation and Projection following McInnes et al. (2018).
// Steps: k-NN → smooth distances → fuzzy simplicial set → SGD layout.

// UMAPResult holds the output of UMAP dimensionality reduction.
type UMAPResult struct {
	Embedding [][]float64 // N × nComponents
}

// UMAPConfig configures the UMAP algorithm.
type UMAPConfig struct {
	NComponents        int     // output dimensions (default 2)
	NNeighbors         int     // local neighborhood size (default 15)
	MinDist            float64 // minimum distance in output space (default 0.1)
	Spread             float64 // effective scale of embedding (default 1.0)
	NegativeSampleRate int     // negatives per positive edge (default 5)
	NEpochs            int     // optimization epochs (0 = auto: 200 if n>10k, else 500)
	LearningRate       float64 // initial SGD learning rate (default 1.0)
	Seed               uint64
	ProgressFn         func(stage string, pct int) // stage: "knn" or "optimize"
}

// ComputeUMAP runs UMAP on the feature matrix. points is N × D (not modified).
func ComputeUMAP(points [][]float64, cfg UMAPConfig) (*UMAPResult, error) {
	n := len(points)
	if n < 2 {
		return nil, fmt.Errorf("need ≥2 points, got %d", n)
	}
	d := len(points[0])

	// Defaults.
	if cfg.NComponents <= 0 {
		cfg.NComponents = 2
	}
	if cfg.NNeighbors <= 0 {
		cfg.NNeighbors = 15
	}
	if cfg.MinDist <= 0 {
		cfg.MinDist = 0.1
	}
	if cfg.Spread <= 0 {
		cfg.Spread = 1.0
	}
	if cfg.NegativeSampleRate <= 0 {
		cfg.NegativeSampleRate = 5
	}
	if cfg.LearningRate <= 0 {
		cfg.LearningRate = 1.0
	}
	if cfg.NEpochs <= 0 {
		if n > 10000 {
			cfg.NEpochs = 200
		} else {
			cfg.NEpochs = 500
		}
	}

	k := cfg.NNeighbors
	if k >= n {
		k = n - 1
	}

	// 1. k-nearest neighbors.
	// For high-dimensional inputs (d > 15) the VP-tree path in umapKNN is
	// skipped (triangle-inequality pruning degrades in high dimensions).
	// Pre-reducing to 10D via PCA re-enables VP-tree and cuts kNN from
	// O(n²) to O(n log n) with negligible effect on graph quality.
	knnPoints := points
	knnDims := d
	if d > 15 && n >= 1000 {
		const pcaTargetDims = 10
		pcaCopy := make([][]float64, n)
		for i, p := range points {
			pcaCopy[i] = make([]float64, d)
			copy(pcaCopy[i], p)
		}
		if pca, err := ComputePCA(pcaCopy, pcaTargetDims); err == nil {
			knnPoints = pca.Embedding
			knnDims = len(pca.Embedding[0])
		}
	}
	knnIdx, knnDist := umapKNN(knnPoints, k, knnDims, cfg.ProgressFn)

	// 2. Smooth kNN distances → sigma, rho per point.
	sigmas, rhos := umapSmoothKNN(knnDist, k)

	// 3. Fuzzy simplicial set (symmetrised graph).
	heads, tails, weights := umapGraph(knnIdx, knnDist, sigmas, rhos, n)

	// 4. Curve parameters a, b from spread / min_dist.
	a, b := umapFindAB(cfg.Spread, cfg.MinDist)

	// 5. Initialisation: spectral (fall back to random on failure).
	rng := rand.New(rand.NewPCG(cfg.Seed, 0))
	embedding := umapSpectralInit(heads, tails, weights, n, cfg.NComponents, rng)
	if embedding == nil {
		embedding = make([][]float64, n)
		for i := range embedding {
			embedding[i] = make([]float64, cfg.NComponents)
			for c := range embedding[i] {
				embedding[i][c] = rng.NormFloat64() * 10
			}
		}
	}

	// 6. SGD optimisation with negative sampling.
	umapOptimize(embedding, heads, tails, weights, a, b, n, cfg, rng)

	return &UMAPResult{Embedding: embedding}, nil
}

// ── k-NN (VP-tree for n≥1000, heap brute-force otherwise, parallelised) ──────
//
// M10.1a: replaced brute-force full sort with a max-heap of size k.
//   - Compare squared distances (no Sqrt per pair; Sqrt applied only to k results)
//   - Heap O(n·log k) instead of sort O(n·log n)
//   - dist/heap buffers allocated once per goroutine, reused across points
//
// M10.2b: for n ≥ 1000, build a VP-tree once and use it for all queries.
//   - Build O(n·log n), each query O(log n) amortised
//   - Tree is read-only → safe to query from multiple goroutines concurrently

func umapKNN(points [][]float64, k, dims int, progressFn func(string, int)) ([][]int, [][]float64) {
	n := len(points)
	knnIdx := make([][]int, n)
	knnDist := make([][]float64, n)

	var doneCount atomic.Int64
	var lastPct atomic.Int64

	nWorkers := runtime.NumCPU()
	if nWorkers > n {
		nWorkers = n
	}
	chunkSize := (n + nWorkers - 1) / nWorkers

	// M10.2b: use VP-tree only when dimensionality is low enough for pruning to help.
	// In high dimensions (dims > 15), the triangle-inequality pruning degrades to a
	// near-linear scan, making the VP-tree slower than the parallelised heap.
	// Empirical threshold: VP-tree is beneficial only for dims ≤ 15.
	if n >= 1000 && dims <= 15 {
		tree := BuildVPTree(points)
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
				for i := start; i < end; i++ {
					idx, dist := tree.KNNExclude(points[i], k, i)
					knnIdx[i] = idx
					knnDist[i] = dist

					if progressFn != nil {
						cnt := doneCount.Add(1)
						pct := int(cnt * 100 / int64(n))
						old := int(lastPct.Load())
						if pct >= old+5 && lastPct.CompareAndSwap(int64(old), int64(pct)) {
							progressFn("knn", pct)
						}
					}
				}
			}(start, end)
		}
		wg.Wait()
		return knnIdx, knnDist
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
			// Per-goroutine buffers reused across all points in the chunk.
			heapIdx := make([]int, k)
			heapSq := make([]float64, k)

			for i := start; i < end; i++ {
				pi := points[i]

				// Initialise heap with first k neighbours (excluding i).
				hSize := 0
				for j := 0; j < n && hSize < k; j++ {
					if j == i {
						continue
					}
					var sq float64
					pj := points[j]
					for d := 0; d < dims; d++ {
						diff := pi[d] - pj[d]
						sq += diff * diff
					}
					heapIdx[hSize] = j
					heapSq[hSize] = sq
					hSize++
				}
				// Build max-heap over the initial k elements.
				for p := hSize/2 - 1; p >= 0; p-- {
					knnSiftDown(heapIdx, heapSq, p, hSize)
				}

				// Scan remaining points; replace heap root if closer.
				startJ := k + 1 // first j not yet seen (skip i if i < k)
				if i < k {
					startJ = k
				}
				for j := startJ; j < n; j++ {
					if j == i {
						continue
					}
					var sq float64
					pj := points[j]
					for d := 0; d < dims; d++ {
						diff := pi[d] - pj[d]
						sq += diff * diff
					}
					if sq < heapSq[0] {
						heapIdx[0] = j
						heapSq[0] = sq
						knnSiftDown(heapIdx, heapSq, 0, k)
					}
				}

				// Sort heap so nearest is first (optional but matches UMAP convention).
				sort.Sort(&knnHeapSorter{heapIdx[:k], heapSq[:k]})

				// Apply Sqrt only to the k final distances.
				idxOut := make([]int, k)
				dstOut := make([]float64, k)
				copy(idxOut, heapIdx[:k])
				for j := 0; j < k; j++ {
					dstOut[j] = math.Sqrt(heapSq[j])
				}
				knnIdx[i] = idxOut
				knnDist[i] = dstOut

				if progressFn != nil {
					cnt := doneCount.Add(1)
					pct := int(cnt * 100 / int64(n))
					old := int(lastPct.Load())
					if pct >= old+5 && lastPct.CompareAndSwap(int64(old), int64(pct)) {
						progressFn("knn", pct)
					}
				}
			}
		}(start, end)
	}
	wg.Wait()

	return knnIdx, knnDist
}

// knnSiftDown maintains a max-heap property at position i.
func knnSiftDown(idx []int, sq []float64, i, n int) {
	for {
		largest := i
		l, r := 2*i+1, 2*i+2
		if l < n && sq[l] > sq[largest] {
			largest = l
		}
		if r < n && sq[r] > sq[largest] {
			largest = r
		}
		if largest == i {
			return
		}
		idx[i], idx[largest] = idx[largest], idx[i]
		sq[i], sq[largest] = sq[largest], sq[i]
		i = largest
	}
}

// knnHeapSorter sorts k nearest neighbours by ascending distance.
type knnHeapSorter struct {
	idx []int
	sq  []float64
}

func (s *knnHeapSorter) Len() int           { return len(s.idx) }
func (s *knnHeapSorter) Less(i, j int) bool { return s.sq[i] < s.sq[j] }
func (s *knnHeapSorter) Swap(i, j int) {
	s.idx[i], s.idx[j] = s.idx[j], s.idx[i]
	s.sq[i], s.sq[j] = s.sq[j], s.sq[i]
}

// ── Smooth kNN distances ────────────────────────────────────────────────────
//
// For each point, binary-search for sigma such that:
//   sum_{j=1}^{k-1} exp(-(d_j - rho) / sigma) = log2(k)
// rho = distance to nearest neighbour (local connectivity = 1).

func umapSmoothKNN(knnDist [][]float64, k int) ([]float64, []float64) {
	n := len(knnDist)
	target := math.Log2(float64(k))
	sigmas := make([]float64, n)
	rhos := make([]float64, n)

	for i := 0; i < n; i++ {
		rhos[i] = knnDist[i][0]
		lo, hi, mid := 0.0, 1000.0, 1.0
		for iter := 0; iter < 64; iter++ {
			var psum float64
			for j := 1; j < len(knnDist[i]); j++ {
				d := knnDist[i][j] - rhos[i]
				if d > 0 {
					psum += math.Exp(-d / mid)
				} else {
					psum += 1.0
				}
			}
			if math.Abs(psum-target) < 1e-5 {
				break
			}
			if psum > target {
				hi = mid
				mid = (lo + hi) / 2
			} else {
				lo = mid
				if hi >= 999.0 {
					mid *= 2
				} else {
					mid = (lo + hi) / 2
				}
			}
		}
		sigmas[i] = mid

		// Guard: sigma shouldn't vanish.
		if rhos[i] > 0 {
			var meanDist float64
			for _, d := range knnDist[i] {
				meanDist += d
			}
			meanDist /= float64(len(knnDist[i]))
			if minSigma := 1e-3 * meanDist; sigmas[i] < minSigma {
				sigmas[i] = minSigma
			}
		}
	}
	return sigmas, rhos
}

// ── Fuzzy simplicial set ────────────────────────────────────────────────────
//
// Converts kNN distances to membership strengths, symmetrises using the
// probabilistic t-conorm: w = a + b − ab, and returns a directed edge list
// (both directions stored).

func umapGraph(knnIdx [][]int, knnDist [][]float64, sigmas, rhos []float64, n int) ([]int, []int, []float64) {
	type edge struct{ i, j int }

	// Directed membership strengths.
	directed := make(map[edge]float64, n*len(knnIdx[0]))
	for i := 0; i < n; i++ {
		for jj := 0; jj < len(knnIdx[i]); jj++ {
			j := knnIdx[i][jj]
			d := knnDist[i][jj]
			var val float64
			if d <= rhos[i] || sigmas[i] < 1e-10 {
				val = 1.0
			} else {
				val = math.Exp(-(d - rhos[i]) / sigmas[i])
			}
			if val < 1e-30 {
				continue
			}
			directed[edge{i, j}] = val
		}
	}

	// Symmetrise.
	type canonEdge struct{ lo, hi int }
	sym := make(map[canonEdge]float64, len(directed))
	for e := range directed {
		lo, hi := e.i, e.j
		if lo > hi {
			lo, hi = hi, lo
		}
		key := canonEdge{lo, hi}
		if _, ok := sym[key]; ok {
			continue
		}
		wFwd := directed[edge{lo, hi}]
		wRev := directed[edge{hi, lo}]
		w := wFwd + wRev - wFwd*wRev
		if w > 0 {
			sym[key] = w
		}
	}

	// Flatten — store both directions for the SGD.
	heads := make([]int, 0, len(sym)*2)
	tails := make([]int, 0, len(sym)*2)
	weights := make([]float64, 0, len(sym)*2)
	for e, w := range sym {
		heads = append(heads, e.lo, e.hi)
		tails = append(tails, e.hi, e.lo)
		weights = append(weights, w, w)
	}

	return heads, tails, weights
}

// ── Curve parameters a, b ───────────────────────────────────────────────────
//
// Fit  f(d) = 1 / (1 + a·d^{2b})  to the target membership function:
//   1           if d ≤ min_dist
//   exp(-(d − min_dist) / spread)  otherwise
//
// M10.1c: cached result for standard UMAP defaults (spread=1.0, minDist=0.1).

func umapFindAB(spread, minDist float64) (float64, float64) {
	// Fast path: standard UMAP defaults (McInnes et al. 2018 recommended values).
	if spread == 1.0 && minDist == 0.1 {
		return 1.929, 0.7915
	}
	const nPts = 100
	xMax := spread * 3
	xs := make([]float64, nPts)
	ys := make([]float64, nPts)
	logXs := make([]float64, nPts) // pre-computed log(x) for fast pow
	for i := range xs {
		xs[i] = xMax * float64(i) / float64(nPts-1)
		if xs[i] < minDist {
			ys[i] = 1.0
		} else {
			ys[i] = math.Exp(-(xs[i] - minDist) / spread)
		}
		if xs[i] > 0 {
			logXs[i] = math.Log(xs[i])
		} else {
			logXs[i] = -50 // effectively x^(2b) ≈ 0
		}
	}

	// MSE using exp(2*b*log(x)) instead of math.Pow(x, 2*b).
	mse := func(a, b float64) float64 {
		var s float64
		for i := range xs {
			xpow := math.Exp(2 * b * logXs[i])
			pred := 1.0 / (1.0 + a*xpow)
			d := pred - ys[i]
			s += d * d
		}
		return s
	}

	// Two-pass grid search: coarse then fine.
	bestA, bestB := 1.0, 1.0
	bestErr := math.MaxFloat64

	// Coarse: 100×100 grid, a in [0.01, 100], b in [0.1, 2.0].
	for ia := 0; ia < 100; ia++ {
		a := math.Pow(10, -2.0+float64(ia)*4.0/100.0)
		for ib := 0; ib < 100; ib++ {
			b := 0.1 + float64(ib)*1.9/100.0
			if e := mse(a, b); e < bestErr {
				bestErr = e
				bestA, bestB = a, b
			}
		}
	}

	// Fine: refine around the best.
	fineA, fineB := bestA, bestB
	for ia := -25; ia <= 25; ia++ {
		a := bestA * math.Pow(10, float64(ia)*0.004)
		for ib := -25; ib <= 25; ib++ {
			b := bestB + float64(ib)*0.002
			if b <= 0 {
				continue
			}
			if e := mse(a, b); e < bestErr {
				bestErr = e
				fineA, fineB = a, b
			}
		}
	}

	return fineA, fineB
}

// ── Spectral initialisation ─────────────────────────────────────────────────
//
// Computes the nComponents largest eigenvectors of the normalised adjacency
// D^{-1/2} W D^{-1/2} via power iteration, then discards the trivial first
// eigenvector to obtain a Laplacian eigenmap initialisation.

func umapSpectralInit(heads, tails []int, weights []float64, n, nComponents int, rng *rand.Rand) [][]float64 {
	type entry struct {
		j int
		w float64
	}
	adj := make([][]entry, n)
	degree := make([]float64, n)
	for i := range heads {
		adj[heads[i]] = append(adj[heads[i]], entry{tails[i], weights[i]})
		degree[heads[i]] += weights[i]
	}

	dInvSqrt := make([]float64, n)
	for i := range dInvSqrt {
		if degree[i] > 0 {
			dInvSqrt[i] = 1.0 / math.Sqrt(degree[i])
		}
	}

	// Matrix-vector: y = D^{-1/2} W D^{-1/2} x
	matvec := func(x []float64) []float64 {
		y := make([]float64, n)
		for i := 0; i < n; i++ {
			di := dInvSqrt[i]
			for _, e := range adj[i] {
				y[i] += e.w * di * dInvSqrt[e.j] * x[e.j]
			}
		}
		return y
	}

	vecNorm := func(v []float64) float64 {
		var s float64
		for _, x := range v {
			s += x * x
		}
		return math.Sqrt(s)
	}

	// Power iteration for nComponents+1 eigenvectors (first is trivial).
	eigvecs := make([][]float64, 0, nComponents+1)
	for comp := 0; comp <= nComponents; comp++ {
		v := make([]float64, n)
		for i := range v {
			v[i] = rng.NormFloat64()
		}
		norm := vecNorm(v)
		if norm < 1e-12 {
			return nil
		}
		for i := range v {
			v[i] /= norm
		}

		for iter := 0; iter < 300; iter++ {
			w := matvec(v)
			// Deflate previous eigenvectors.
			for _, prev := range eigvecs {
				var dot float64
				for i := range w {
					dot += w[i] * prev[i]
				}
				for i := range w {
					w[i] -= dot * prev[i]
				}
			}
			norm := vecNorm(w)
			if norm < 1e-12 {
				return nil // degenerate graph
			}
			for i := range w {
				w[i] /= norm
			}
			var diff float64
			for i := range v {
				d := w[i] - v[i]
				diff += d * d
			}
			v = w
			if diff < 1e-8 {
				break
			}
		}
		eigvecs = append(eigvecs, v)
	}

	if len(eigvecs) < nComponents+1 {
		return nil
	}

	// Use eigenvectors 1..nComponents (skip trivial), scaled.
	embedding := make([][]float64, n)
	for i := range embedding {
		embedding[i] = make([]float64, nComponents)
		for c := 0; c < nComponents; c++ {
			embedding[i][c] = eigvecs[c+1][i] * 10
		}
	}

	// Sanity check: all finite, non-zero variance.
	for c := 0; c < nComponents; c++ {
		var sum, sumSq float64
		for i := 0; i < n; i++ {
			v := embedding[i][c]
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return nil
			}
			sum += v
			sumSq += v * v
		}
		mean := sum / float64(n)
		variance := sumSq/float64(n) - mean*mean
		if variance < 1e-10 {
			return nil
		}
	}

	return embedding
}

// ── SGD optimisation ────────────────────────────────────────────────────────
//
// Optimises the low-dimensional embedding using stochastic gradient descent
// with edge sampling and negative sampling, following the UMAP loss
// (cross-entropy between high-dim and low-dim fuzzy sets).
//
// M10.2d: parallel SGD (Hogwild! style).
//   - Edges partitioned into nWorkers chunks; each goroutine has its own RNG.
//   - Racy reads/writes on shared embedding rows are acceptable: the algorithm
//     converges even with stale reads (standard practice, see Recht et al. 2011).

func umapOptimize(embedding [][]float64, heads, tails []int, weights []float64,
	a, b float64, n int, cfg UMAPConfig, rng *rand.Rand) {

	nEdges := len(heads)
	nComp := cfg.NComponents
	nEpochs := cfg.NEpochs
	alpha0 := cfg.LearningRate
	negRate := cfg.NegativeSampleRate

	// Compute edge sampling schedule from weights.
	var maxW float64
	for _, w := range weights {
		if w > maxW {
			maxW = w
		}
	}

	epochsPerSample := make([]float64, nEdges)
	epochOfNextSample := make([]float64, nEdges)
	epochsPerNegSample := make([]float64, nEdges)
	epochOfNextNegSample := make([]float64, nEdges)

	for i, w := range weights {
		nSamples := float64(nEpochs) * w / maxW
		if nSamples > 0 {
			epochsPerSample[i] = float64(nEpochs) / nSamples
		} else {
			epochsPerSample[i] = float64(nEpochs) + 1
		}
		epochOfNextSample[i] = epochsPerSample[i]
		epochsPerNegSample[i] = epochsPerSample[i] / float64(negRate)
		epochOfNextNegSample[i] = epochsPerNegSample[i]
	}

	// Per-worker RNGs seeded deterministically from cfg.Seed.
	nWorkers := runtime.NumCPU()
	if nWorkers > nEdges {
		nWorkers = nEdges
	}
	workerRngs := make([]*rand.Rand, nWorkers)
	for w := range workerRngs {
		workerRngs[w] = rand.New(rand.NewPCG(cfg.Seed+uint64(w)+1, 0))
	}
	edgeChunk := (nEdges + nWorkers - 1) / nWorkers

	for epoch := 0; epoch < nEpochs; epoch++ {
		alpha := alpha0 * (1.0 - float64(epoch)/float64(nEpochs))
		epochF := float64(epoch)

		var wg sync.WaitGroup
		for w := 0; w < nWorkers; w++ {
			eStart := w * edgeChunk
			eEnd := eStart + edgeChunk
			if eEnd > nEdges {
				eEnd = nEdges
			}
			localRng := workerRngs[w]
			wg.Add(1)
			go func(eStart, eEnd int) {
				defer wg.Done()
				for i := eStart; i < eEnd; i++ {
					if epochOfNextSample[i] > epochF {
						continue
					}
					j := heads[i]
					k := tails[i]

					// Squared distance in embedding space.
					// embLoad: atomic read so the race detector is satisfied.
					var distSq float64
					for c := 0; c < nComp; c++ {
						d := embLoad(&embedding[j][c]) - embLoad(&embedding[k][c])
						distSq += d * d
					}

					// Attractive gradient.
					// M10.1b: replace math.Pow with exp(b*log(x)) to avoid slow pow.
					var gradCoeff float64
					if distSq > 0 {
						pow_b := math.Exp(b * math.Log(distSq))
						gradCoeff = -2.0 * a * b * (pow_b / distSq) / (a*pow_b + 1)
					}
					for c := 0; c < nComp; c++ {
						jc := embLoad(&embedding[j][c])
						kc := embLoad(&embedding[k][c])
						g := umapClip(gradCoeff*(jc-kc)) * alpha
						embAdd(&embedding[j][c], g)
					}

					epochOfNextSample[i] += epochsPerSample[i]

					// Negative sampling.
					nNeg := int((epochF - epochOfNextNegSample[i]) / epochsPerNegSample[i])
					if nNeg < 0 {
						nNeg = 0
					}
					for p := 0; p < nNeg; p++ {
						neg := localRng.IntN(n)
						if neg == j {
							continue
						}
						var negDistSq float64
						for c := 0; c < nComp; c++ {
							d := embLoad(&embedding[j][c]) - embLoad(&embedding[neg][c])
							negDistSq += d * d
						}
						var repCoeff float64
						if negDistSq > 0 {
							pow_b := math.Exp(b * math.Log(negDistSq))
							repCoeff = 2.0 * b / ((0.001 + negDistSq) * (a*pow_b + 1))
						}
						for c := 0; c < nComp; c++ {
							jc := embLoad(&embedding[j][c])
							nc := embLoad(&embedding[neg][c])
							g := umapClip(repCoeff*(jc-nc)) * alpha
							embAdd(&embedding[j][c], g)
						}
					}
					epochOfNextNegSample[i] += float64(nNeg) * epochsPerNegSample[i]
				}
			}(eStart, eEnd)
		}
		wg.Wait()

		if cfg.ProgressFn != nil && (epoch%10 == 0 || epoch == nEpochs-1) {
			pct := epoch * 100 / nEpochs
			if epoch == nEpochs-1 {
				pct = 100
			}
			cfg.ProgressFn("optimize", pct)
		}
	}
}

// umapClip clamps a gradient value to [-4, 4] for numerical stability.
func umapClip(x float64) float64 {
	if x > 4 {
		return 4
	}
	if x < -4 {
		return -4
	}
	return x
}

// ── Atomic float64 helpers ───────────────────────────────────────────────────
//
// Used in parallel SGD to make concurrent embedding accesses race-detector safe.
// Technique: reinterpret *float64 as *uint64 and use sync/atomic operations.
// This is standard practice in high-performance Go (e.g. go.uber.org/atomic).

// embLoad atomically reads a float64 from p.
func embLoad(p *float64) float64 {
	return math.Float64frombits(atomic.LoadUint64((*uint64)(unsafe.Pointer(p))))
}

// embAdd atomically adds delta to *p using a CAS loop.
func embAdd(p *float64, delta float64) {
	for {
		old := atomic.LoadUint64((*uint64)(unsafe.Pointer(p)))
		if atomic.CompareAndSwapUint64((*uint64)(unsafe.Pointer(p)), old,
			math.Float64bits(math.Float64frombits(old)+delta)) {
			return
		}
	}
}
