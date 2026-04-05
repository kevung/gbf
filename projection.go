package gbf

import (
	"context"
	"fmt"
	"math"
	"math/rand/v2"
	"sort"
	"time"
)

// ── PCA (pure Go) ────────────────────────────────────────────────────────────

// PCAResult holds the result of a PCA projection.
type PCAResult struct {
	Embedding [][]float64 // N × nComponents
	Variance  []float64   // explained variance per component
}

// ComputePCA runs PCA on the feature matrix and returns nComponents dimensions.
// features is N × D (row-major). Data is centered and scaled in place.
func ComputePCA(features [][]float64, nComponents int) (*PCAResult, error) {
	n := len(features)
	if n == 0 {
		return nil, fmt.Errorf("empty feature matrix")
	}
	d := len(features[0])
	if nComponents > d {
		nComponents = d
	}

	// Center and scale (standard scaling).
	mean := make([]float64, d)
	std := make([]float64, d)
	for j := 0; j < d; j++ {
		var s float64
		for i := 0; i < n; i++ {
			s += features[i][j]
		}
		mean[j] = s / float64(n)
	}
	for j := 0; j < d; j++ {
		var s float64
		for i := 0; i < n; i++ {
			diff := features[i][j] - mean[j]
			s += diff * diff
		}
		std[j] = math.Sqrt(s / float64(n))
		if std[j] < 1e-12 {
			std[j] = 1
		}
	}
	for i := 0; i < n; i++ {
		for j := 0; j < d; j++ {
			features[i][j] = (features[i][j] - mean[j]) / std[j]
		}
	}

	// Compute covariance matrix (D × D).
	cov := make([][]float64, d)
	for i := range cov {
		cov[i] = make([]float64, d)
	}
	for i := 0; i < d; i++ {
		for j := i; j < d; j++ {
			var s float64
			for k := 0; k < n; k++ {
				s += features[k][i] * features[k][j]
			}
			cov[i][j] = s / float64(n-1)
			cov[j][i] = cov[i][j]
		}
	}

	// Power iteration to extract top nComponents eigenvectors.
	eigenvectors := make([][]float64, nComponents)
	eigenvalues := make([]float64, nComponents)

	for comp := 0; comp < nComponents; comp++ {
		v := make([]float64, d)
		rng := rand.New(rand.NewPCG(42, uint64(comp)))
		for j := range v {
			v[j] = rng.Float64() - 0.5
		}
		normalize(v)

		for iter := 0; iter < 300; iter++ {
			// w = cov * v
			w := make([]float64, d)
			for i := 0; i < d; i++ {
				var s float64
				for j := 0; j < d; j++ {
					s += cov[i][j] * v[j]
				}
				w[i] = s
			}

			// Deflate: remove components from previous eigenvectors.
			for prev := 0; prev < comp; prev++ {
				dot := dotProduct(w, eigenvectors[prev])
				for j := range w {
					w[j] -= dot * eigenvectors[prev][j]
				}
			}

			normalize(w)

			// Check convergence.
			diff := 0.0
			for j := range v {
				diff += (w[j] - v[j]) * (w[j] - v[j])
			}
			v = w
			if diff < 1e-12 {
				break
			}
		}

		eigenvectors[comp] = v
		// eigenvalue = v^T * cov * v
		w := make([]float64, d)
		for i := 0; i < d; i++ {
			var s float64
			for j := 0; j < d; j++ {
				s += cov[i][j] * v[j]
			}
			w[i] = s
		}
		eigenvalues[comp] = dotProduct(v, w)
	}

	// Project: embedding[i] = features[i] * eigenvectors^T
	embedding := make([][]float64, n)
	for i := 0; i < n; i++ {
		row := make([]float64, nComponents)
		for c := 0; c < nComponents; c++ {
			var s float64
			for j := 0; j < d; j++ {
				s += features[i][j] * eigenvectors[c][j]
			}
			row[c] = s
		}
		embedding[i] = row
	}

	return &PCAResult{Embedding: embedding, Variance: eigenvalues}, nil
}

// ── K-Means (pure Go) ───────────────────────────────────────────────────────

// KMeansResult holds the result of k-means clustering.
type KMeansResult struct {
	Labels    []int       // cluster assignment per point (-1 for noise)
	Centroids [][]float64 // k × nDims
	Inertia   float64     // total within-cluster sum of squares
}

// ComputeKMeans runs k-means++ on the given points (N × D).
func ComputeKMeans(points [][]float64, k, maxIter int, seed uint64) (*KMeansResult, error) {
	n := len(points)
	if n == 0 {
		return nil, fmt.Errorf("empty points")
	}
	if k <= 0 || k > n {
		return nil, fmt.Errorf("invalid k=%d for n=%d", k, n)
	}
	d := len(points[0])

	rng := rand.New(rand.NewPCG(seed, 0))

	// k-means++ initialization.
	centroids := make([][]float64, k)
	centroids[0] = copySlice(points[rng.IntN(n)])

	dist := make([]float64, n)
	for c := 1; c < k; c++ {
		totalDist := 0.0
		for i := 0; i < n; i++ {
			minD := math.MaxFloat64
			for cc := 0; cc < c; cc++ {
				dd := sqDist(points[i], centroids[cc])
				if dd < minD {
					minD = dd
				}
			}
			dist[i] = minD
			totalDist += minD
		}
		// Weighted random selection.
		target := rng.Float64() * totalDist
		cum := 0.0
		chosen := 0
		for i := 0; i < n; i++ {
			cum += dist[i]
			if cum >= target {
				chosen = i
				break
			}
		}
		centroids[c] = copySlice(points[chosen])
	}

	labels := make([]int, n)
	if maxIter <= 0 {
		maxIter = 100
	}

	for iter := 0; iter < maxIter; iter++ {
		// Assignment.
		changed := false
		for i := 0; i < n; i++ {
			bestC := 0
			bestD := sqDist(points[i], centroids[0])
			for c := 1; c < k; c++ {
				dd := sqDist(points[i], centroids[c])
				if dd < bestD {
					bestD = dd
					bestC = c
				}
			}
			if labels[i] != bestC {
				labels[i] = bestC
				changed = true
			}
		}

		if !changed {
			break
		}

		// Update centroids.
		for c := 0; c < k; c++ {
			newC := make([]float64, d)
			count := 0
			for i := 0; i < n; i++ {
				if labels[i] == c {
					for j := 0; j < d; j++ {
						newC[j] += points[i][j]
					}
					count++
				}
			}
			if count > 0 {
				for j := 0; j < d; j++ {
					newC[j] /= float64(count)
				}
				centroids[c] = newC
			}
		}
	}

	// Compute inertia.
	inertia := 0.0
	for i := 0; i < n; i++ {
		inertia += sqDist(points[i], centroids[labels[i]])
	}

	return &KMeansResult{
		Labels:    labels,
		Centroids: centroids,
		Inertia:   inertia,
	}, nil
}

// ── Projection Pipeline ─────────────────────────────────────────────────────

// ProjectionConfig configures a projection computation.
type ProjectionConfig struct {
	Method         string // "pca_2d", "tsne_2d", "umap_2d"
	K              int    // number of clusters for k-means (default: 8; 0 = use HDBSCAN)
	SampleSize     int    // subsample if > 0 and < total positions
	Seed           uint64
	FeatureVersion string
	ProgressFn     func(stage string, pct int) // optional progress callback
	// M10.3: LoD level. 0=overview (~5-10K), 1=medium (~50-100K), 2=complete.
	// For lod < 2 with SampleSize > 0, stratified sampling is used.
	LoD int

	// t-SNE specific.
	Perplexity float64 // t-SNE perplexity (default 30)
	TSNEIter   int     // t-SNE iterations (default 1000)

	// UMAP specific.
	UMAPNeighbors int     // UMAP n_neighbors (default 15)
	UMAPMinDist   float64 // UMAP min_dist (default 0.1)

	// Clustering.
	ClusterMethod    string // "kmeans" (default) or "hdbscan"
	HDBSCANMinSize   int    // HDBSCAN min_cluster_size (default 100)
	HDBSCANMinSample int    // HDBSCAN min_samples (default 50)

	// Feature selection: indices of features to use (0-43). Nil = all 44.
	FeatureIndices []int
}

// ProjectionComputeResult holds the computed projection + clustering.
type ProjectionComputeResult struct {
	Points     []ProjectionPoint
	Method     string
	Params     string
	NPoints    int
	LoD        int    // M10.3: LoD level (0/1/2)
	BoundsJSON string // M10.3: {"min_x":…,"max_x":…,"min_y":…,"max_y":…}
}

// ComputeProjectionFromStore extracts features from the store, computes
// PCA/t-SNE + k-means/HDBSCAN, and returns projection points ready for insertion.
func ComputeProjectionFromStore(ctx context.Context, store Store, cfg ProjectionConfig) (*ProjectionComputeResult, error) {
	progress := func(stage string, pct int) {
		if cfg.ProgressFn != nil {
			cfg.ProgressFn(stage, pct)
		}
	}

	if cfg.K < 0 {
		cfg.K = 0
	}
	if cfg.Seed == 0 {
		cfg.Seed = 42
	}
	if cfg.FeatureVersion == "" {
		cfg.FeatureVersion = "v1.0"
	}
	if cfg.ClusterMethod == "" {
		if cfg.K > 0 {
			cfg.ClusterMethod = "kmeans"
		} else {
			cfg.ClusterMethod = "hdbscan"
		}
	}

	progress("extracting", 0)

	var ids []int64
	var features [][]float64

	// Use stratified sampling for LoD 0/1 when SampleSize is set, to preserve
	// class distribution. Fall back to uniform sampling for LoD 2 (full dataset).
	type stratifiedExporter interface {
		ExportStratifiedFeatures(ctx context.Context, sampleSize int, seed uint64) ([]int64, [][]float64, error)
	}
	type allFeaturesExporter interface {
		ExportAllFeatures(ctx context.Context, sampleSize int, seed uint64) ([]int64, [][]float64, error)
	}

	if cfg.LoD < 2 && cfg.SampleSize > 0 {
		if se, ok := store.(stratifiedExporter); ok {
			var err error
			ids, features, err = se.ExportStratifiedFeatures(ctx, cfg.SampleSize, cfg.Seed)
			if err != nil {
				return nil, fmt.Errorf("export stratified features: %w", err)
			}
		}
	}
	if ids == nil {
		// Fallback: uniform sampling via ExportAllFeatures.
		if accessor, ok := store.(allFeaturesExporter); ok {
			var err error
			ids, features, err = accessor.ExportAllFeatures(ctx, cfg.SampleSize, cfg.Seed)
			if err != nil {
				return nil, fmt.Errorf("export features: %w", err)
			}
		} else {
			return nil, fmt.Errorf("store does not support ExportAllFeatures")
		}
	}

	if len(ids) == 0 {
		return nil, fmt.Errorf("no positions found")
	}

	// Apply feature selection if specified.
	if len(cfg.FeatureIndices) > 0 {
		for i, f := range features {
			selected := make([]float64, len(cfg.FeatureIndices))
			for j, idx := range cfg.FeatureIndices {
				if idx >= 0 && idx < len(f) {
					selected[j] = f[idx]
				}
			}
			features[i] = selected
		}
	}

	progress("extracting", 100)

	// ── Dimensionality Reduction ─────────────────────────────────────────
	var embedding [][]float64
	var varianceInfo string

	switch cfg.Method {
	case "umap_2d":
		progress("computing_umap", 0)
		featuresCopy := make([][]float64, len(features))
		for i, f := range features {
			featuresCopy[i] = copySlice(f)
		}
		standardScale(featuresCopy)

		nNeighbors := cfg.UMAPNeighbors
		if nNeighbors <= 0 {
			nNeighbors = 15
		}
		minDist := cfg.UMAPMinDist
		if minDist <= 0 {
			minDist = 0.1
		}
		result, err := ComputeUMAP(featuresCopy, UMAPConfig{
			NComponents: 2,
			NNeighbors:  nNeighbors,
			MinDist:     minDist,
			Seed:        cfg.Seed,
			ProgressFn: func(stage string, pct int) {
				switch stage {
				case "knn":
					// kNN is ~70% of total compute time.
					progress("computing_umap", pct*70/100)
				case "optimize":
					progress("computing_umap", 70+pct*30/100)
				}
			},
		})
		if err != nil {
			return nil, fmt.Errorf("UMAP: %w", err)
		}
		embedding = result.Embedding
		varianceInfo = fmt.Sprintf(`"n_neighbors":%d,"min_dist":%.3f`, nNeighbors, minDist)
		progress("computing_umap", 100)

	case "tsne_2d":
		// t-SNE builds O(n²) matrices; cap to avoid OOM.
		const tsneMaxN = 5000
		if len(features) > tsneMaxN {
			return nil, fmt.Errorf("t-SNE limited to %d points (got %d); use sample_size or switch to umap_2d", tsneMaxN, len(features))
		}
		progress("computing_tsne", 0)
		featuresCopy := make([][]float64, len(features))
		for i, f := range features {
			featuresCopy[i] = copySlice(f)
		}
		// Standard scale first.
		standardScale(featuresCopy)

		perplexity := cfg.Perplexity
		if perplexity <= 0 {
			perplexity = 30
		}
		tsneIter := cfg.TSNEIter
		if tsneIter <= 0 {
			tsneIter = 1000
		}
		result, err := ComputeTSNE(featuresCopy, 2, perplexity, tsneIter, cfg.Seed,
			func(iter, maxIter int) {
				progress("computing_tsne", iter*100/maxIter)
			})
		if err != nil {
			return nil, fmt.Errorf("t-SNE: %w", err)
		}
		embedding = result.Embedding
		varianceInfo = fmt.Sprintf(`"perplexity":%.0f,"iterations":%d`, perplexity, tsneIter)
		progress("computing_tsne", 100)

	default: // "pca_2d"
		progress("computing_pca", 0)
		featuresCopy := make([][]float64, len(features))
		for i, f := range features {
			featuresCopy[i] = copySlice(f)
		}
		pca, err := ComputePCA(featuresCopy, 2)
		if err != nil {
			return nil, fmt.Errorf("PCA: %w", err)
		}
		embedding = pca.Embedding
		varianceInfo = fmt.Sprintf(`"variance":[%.4f,%.4f]`, pca.Variance[0], pca.Variance[1])
		progress("computing_pca", 100)
	}

	// ── Clustering ───────────────────────────────────────────────────────
	var clusterLabels []int
	var clusterInfo string

	switch cfg.ClusterMethod {
	case "hdbscan":
		progress("computing_hdbscan", 0)
		minSize := cfg.HDBSCANMinSize
		if minSize <= 0 {
			minSize = 100
		}
		minSample := cfg.HDBSCANMinSample
		if minSample <= 0 {
			minSample = 50
		}
		result, err := ComputeHDBSCAN(embedding, minSize, minSample,
			func(stage string, pct int) {
				progress(stage, pct)
			})
		if err != nil {
			return nil, fmt.Errorf("HDBSCAN: %w", err)
		}
		clusterLabels = result.Labels
		clusterInfo = fmt.Sprintf(`"cluster_method":"hdbscan","n_clusters":%d,"n_noise":%d,"min_cluster_size":%d`,
			result.NClusters, result.NNoise, minSize)
		progress("computing_hdbscan", 100)

	default: // "kmeans"
		if cfg.K <= 0 {
			cfg.K = 8
		}
		progress("computing_kmeans", 0)
		kmeans, err := ComputeKMeans(embedding, cfg.K, 100, cfg.Seed)
		if err != nil {
			return nil, fmt.Errorf("k-means: %w", err)
		}
		clusterLabels = kmeans.Labels
		clusterInfo = fmt.Sprintf(`"cluster_method":"kmeans","k":%d`, cfg.K)
		progress("computing_kmeans", 100)
	}

	progress("saving", 0)

	// Build projection points.
	points := make([]ProjectionPoint, len(ids))
	for i, id := range ids {
		x := float32(embedding[i][0])
		y := float32(embedding[i][1])
		cid := clusterLabels[i]
		pp := ProjectionPoint{
			PositionID: id,
			X:          x,
			Y:          y,
		}
		if cid >= 0 {
			pp.ClusterID = &cid
		}
		points[i] = pp
	}

	featureInfo := `"features":"all"`
	if len(cfg.FeatureIndices) > 0 {
		featureInfo = fmt.Sprintf(`"features":%d`, len(cfg.FeatureIndices))
	}

	// Compute projection bounds (min/max x/y) for LoD tile system.
	boundsJSON := computeBoundsJSON(embedding)

	return &ProjectionComputeResult{
		Points:     points,
		Method:     cfg.Method,
		Params:     fmt.Sprintf(`{%s,"n":%d,%s,%s}`, varianceInfo, len(ids), clusterInfo, featureInfo),
		NPoints:    len(ids),
		LoD:        cfg.LoD,
		BoundsJSON: boundsJSON,
	}, nil
}

// SaveProjectionResult saves the computed projection into the store.
func SaveProjectionResult(ctx context.Context, store Store, result *ProjectionComputeResult, featureVersion string) error {
	if featureVersion == "" {
		featureVersion = "v1.0"
	}

	run := ProjectionRun{
		Method:         result.Method,
		FeatureVersion: featureVersion,
		Params:         result.Params,
		NPoints:        result.NPoints,
		CreatedAt:      time.Now().UTC().Format(time.RFC3339),
		LoD:            result.LoD,
		BoundsJSON:     result.BoundsJSON,
	}

	runID, err := store.CreateProjectionRun(ctx, run)
	if err != nil {
		return fmt.Errorf("create run: %w", err)
	}

	// Insert all points in batches of 5000, wrapped in a single transaction
	// when the store implements Batcher. This prevents race conditions with
	// concurrent import operations that share the same s.tx field.
	if b, ok := store.(Batcher); ok {
		if err := b.BeginBatch(ctx); err != nil {
			return fmt.Errorf("begin insert: %w", err)
		}
		for i := 0; i < len(result.Points); i += 5000 {
			end := i + 5000
			if end > len(result.Points) {
				end = len(result.Points)
			}
			if err := store.InsertProjectionBatch(ctx, runID, result.Points[i:end]); err != nil {
				b.RollbackBatch()
				return fmt.Errorf("insert batch at %d: %w", i, err)
			}
		}
		if err := b.CommitBatch(); err != nil {
			return fmt.Errorf("commit insert: %w", err)
		}
	} else {
		for i := 0; i < len(result.Points); i += 5000 {
			end := i + 5000
			if end > len(result.Points) {
				end = len(result.Points)
			}
			if err := store.InsertProjectionBatch(ctx, runID, result.Points[i:end]); err != nil {
				return fmt.Errorf("insert batch at %d: %w", i, err)
			}
		}
	}

	if err := store.ActivateProjectionRun(ctx, runID); err != nil {
		return fmt.Errorf("activate run: %w", err)
	}

	// Build pre-computed tiles for the tile API (M10.4).
	if result.BoundsJSON != "" {
		if err := BuildTiles(ctx, store, runID, result.LoD, result.BoundsJSON); err != nil {
			return fmt.Errorf("build tiles: %w", err)
		}
	}

	return nil
}

// RebuildProjectionTiles rebuilds the pre-computed tile data for an existing
// active projection run whose tiles are missing or whose bounds_json was not
// recorded. It computes bounds from the stored projection points, updates the
// run record, and calls BuildTiles.
func RebuildProjectionTiles(ctx context.Context, store Store, run *ProjectionRun) error {
	rows, err := store.QueryProjectionsByRunID(ctx, run.ID)
	if err != nil {
		return fmt.Errorf("query projections: %w", err)
	}
	if len(rows) == 0 {
		return fmt.Errorf("no projection points found for run %d", run.ID)
	}

	// Compute bounds from stored points.
	minX, maxX := float64(rows[0].X), float64(rows[0].X)
	minY, maxY := float64(rows[0].Y), float64(rows[0].Y)
	for _, r := range rows[1:] {
		x, y := float64(r.X), float64(r.Y)
		if x < minX {
			minX = x
		}
		if x > maxX {
			maxX = x
		}
		if y < minY {
			minY = y
		}
		if y > maxY {
			maxY = y
		}
	}
	boundsJSON := fmt.Sprintf(`{"min_x":%.6f,"max_x":%.6f,"min_y":%.6f,"max_y":%.6f}`,
		minX, maxX, minY, maxY)

	if err := store.UpdateProjectionBoundsJSON(ctx, run.ID, boundsJSON); err != nil {
		return fmt.Errorf("update bounds: %w", err)
	}

	return BuildTiles(ctx, store, run.ID, run.LoD, boundsJSON)
}

// ── Helpers ──────────────────────────────────────────────────────────────────

func dotProduct(a, b []float64) float64 {
	var s float64
	for i := range a {
		s += a[i] * b[i]
	}
	return s
}

func normalize(v []float64) {
	norm := math.Sqrt(dotProduct(v, v))
	if norm < 1e-12 {
		return
	}
	for i := range v {
		v[i] /= norm
	}
}

func sqDist(a, b []float64) float64 {
	var s float64
	for i := range a {
		d := a[i] - b[i]
		s += d * d
	}
	return s
}

func copySlice(s []float64) []float64 {
	c := make([]float64, len(s))
	copy(c, s)
	return c
}

// standardScale centers and scales each column to zero mean and unit variance.
func standardScale(features [][]float64) {
	if len(features) == 0 {
		return
	}
	n := len(features)
	d := len(features[0])
	mean := make([]float64, d)
	std := make([]float64, d)
	for j := 0; j < d; j++ {
		var s float64
		for i := 0; i < n; i++ {
			s += features[i][j]
		}
		mean[j] = s / float64(n)
	}
	for j := 0; j < d; j++ {
		var s float64
		for i := 0; i < n; i++ {
			diff := features[i][j] - mean[j]
			s += diff * diff
		}
		std[j] = math.Sqrt(s / float64(n))
		if std[j] < 1e-12 {
			std[j] = 1
		}
	}
	for i := 0; i < n; i++ {
		for j := 0; j < d; j++ {
			features[i][j] = (features[i][j] - mean[j]) / std[j]
		}
	}
}

// SilhouetteScore computes a simplified silhouette score for the clustering.
// Uses a random sample for efficiency when n > maxSample.
func SilhouetteScore(points [][]float64, labels []int, maxSample int) float64 {
	n := len(points)
	if n < 2 {
		return 0
	}

	// Find unique clusters.
	clusterSet := map[int]bool{}
	for _, l := range labels {
		clusterSet[l] = true
	}
	if len(clusterSet) < 2 {
		return 0
	}

	// Sample indices if too many.
	indices := make([]int, n)
	for i := range indices {
		indices[i] = i
	}
	if maxSample > 0 && n > maxSample {
		rng := rand.New(rand.NewPCG(42, 0))
		rng.Shuffle(n, func(i, j int) { indices[i], indices[j] = indices[j], indices[i] })
		indices = indices[:maxSample]
		sort.Ints(indices)
	}

	// Group points by cluster.
	clusters := map[int][]int{}
	for i, l := range labels {
		clusters[l] = append(clusters[l], i)
	}

	totalScore := 0.0
	for _, idx := range indices {
		myCluster := labels[idx]
		members := clusters[myCluster]

		// a(i) = avg distance to same cluster.
		a := 0.0
		for _, j := range members {
			if j != idx {
				a += math.Sqrt(sqDist(points[idx], points[j]))
			}
		}
		if len(members) > 1 {
			a /= float64(len(members) - 1)
		}

		// b(i) = min avg distance to other clusters.
		b := math.MaxFloat64
		for cl, others := range clusters {
			if cl == myCluster {
				continue
			}
			avg := 0.0
			for _, j := range others {
				avg += math.Sqrt(sqDist(points[idx], points[j]))
			}
			avg /= float64(len(others))
			if avg < b {
				b = avg
			}
		}

		s := 0.0
		if a < b {
			s = 1 - a/b
		} else if a > b {
			s = b/a - 1
		}
		totalScore += s
	}

	return totalScore / float64(len(indices))
}

// computeBoundsJSON returns a JSON string with the min/max x/y of the embedding.
func computeBoundsJSON(embedding [][]float64) string {
	if len(embedding) == 0 {
		return ""
	}
	minX, maxX := embedding[0][0], embedding[0][0]
	minY, maxY := embedding[0][1], embedding[0][1]
	for _, pt := range embedding[1:] {
		if pt[0] < minX {
			minX = pt[0]
		}
		if pt[0] > maxX {
			maxX = pt[0]
		}
		if pt[1] < minY {
			minY = pt[1]
		}
		if pt[1] > maxY {
			maxY = pt[1]
		}
	}
	return fmt.Sprintf(`{"min_x":%.6f,"max_x":%.6f,"min_y":%.6f,"max_y":%.6f}`,
		minX, maxX, minY, maxY)
}
