# M4 — Feature Extraction

## Objective

Define and implement the numeric feature vector extracted from each
position for dimensionality reduction and clustering. Provide export
to numpy-compatible formats for Python analysis.

## Pre-requisites

M3 (at least 1 BMAB region imported into SQLite).

## Sub-steps

### M4.1 — Raw Feature Vector

Extract directly from BaseRecord fields:

| Index | Feature         | Source         | Range     |
|-------|-----------------|----------------|-----------|
| 0-23  | point_counts    | PointCounts    | -15 to 15 |
| 24    | bar_x           | BarX           | 0-15      |
| 25    | bar_o           | BarO           | 0-15      |
| 26    | borne_off_x     | BorneOffX      | 0-15      |
| 27    | borne_off_o     | BorneOffO      | 0-15      |
| 28    | pip_x           | PipX           | 0-375     |
| 29    | pip_o           | PipO           | 0-375     |
| 30    | cube_log2       | CubeLog2       | 0-6       |
| 31    | cube_owner      | CubeOwner      | 0-2       |
| 32    | away_x          | AwayX          | 0-255     |
| 33    | away_o          | AwayO          | 0-255     |

34 raw dimensions.

### M4.2 — Derived Features

Computed from the raw features and bitboard layers:

| Index | Feature              | Computation                              |
|-------|----------------------|------------------------------------------|
| 34    | blot_count_x         | Count points where LayerX1=1, LayerX2=0  |
| 35    | blot_count_o         | Count points where LayerO1=1, LayerO2=0  |
| 36    | made_point_count_x   | Count points where LayerX2=1             |
| 37    | made_point_count_o   | Count points where LayerO2=1             |
| 38    | max_prime_length_x   | Longest consecutive run of LayerX2=1     |
| 39    | max_prime_length_o   | Longest consecutive run of LayerO2=1     |
| 40    | anchor_count_x       | X's made points in O's home board (18-23)|
| 41    | anchor_count_o       | O's made points in X's home board (0-5)  |
| 42    | pip_diff             | pip_x - pip_o (racing advantage)         |
| 43    | position_class       | 0=contact, 1=race, 2=bearoff             |

~44 total dimensions. Exact count may evolve based on M5 exploration.

### M4.3 — Position Classification

Classify each position into one of:
- **Contact** (0): at least one checker of each player behind an opponent's checker
- **Race** (1): no contact, both players have checkers outside home board
- **Bearoff** (2): all checkers in home board or borne off

This classification is a derived feature (index 43) and also a useful
filter column for queries.

### M4.4 — Normalization

For UMAP/PCA, features must be on comparable scales. Options:
- **Min-max scaling**: map each feature to [0, 1] using dataset min/max
- **Standard scaling**: zero mean, unit variance

Default: standard scaling (better for PCA). Min-max for UMAP comparison.

Normalization parameters (mean, std or min, max) computed on the full
dataset and stored for consistent re-application on new data.

### M4.5 — Go Implementation

In `features.go`:

```go
func ExtractFeatures(rec BaseRecord) []float64
func ExtractDerivedFeatures(rec BaseRecord) []float64
func ExtractAllFeatures(rec BaseRecord) []float64  // raw + derived
func ClassifyPosition(rec BaseRecord) int          // 0=contact, 1=race, 2=bearoff
```

These functions operate on a single BaseRecord and return the feature
vector. No database access needed.

### M4.6 — Export to Numpy

Two export paths:

**Path A — Parquet export**:
Query all positions from SQLite, compute features in Go, write to
Parquet file. Python reads with `pandas.read_parquet()`.

**Path B — Direct .npy export**:
Write a raw binary file in numpy .npy format (header + float64 array).
Faster for large datasets, skips the Parquet overhead.

Implement at least Path A. Path B is optional optimization.

## Files to Create/Modify

| File | Action |
|------|--------|
| `features.go` | Create (feature extraction + classification) |
| `export.go` | Create (Parquet and/or npy export) |

## Acceptance Criteria

- [ ] `ExtractAllFeatures` returns a vector of correct length (~44)
- [ ] Starting position produces expected feature values
- [ ] Position classification is correct for known positions
- [ ] Parquet export of 10K positions loads in pandas without error
- [ ] No NaN or Inf in any exported feature vector

## Tests

### Unit Tests

**[U] Starting position features**
Extract features from the standard opening position.
Success: pip_x = pip_o = 167, blot_count = 0, made_point_count_x = 4
(6, 8, 13, 24 points), position_class = contact.

**[U] Bearoff position classification**
Create a position where all X checkers are in points 0-5 and all O
checkers are in points 18-23.
Success: ClassifyPosition returns 2 (bearoff).

**[U] Race position classification**
Create a position with no contact but checkers outside home boards.
Success: ClassifyPosition returns 1 (race).

**[U] Prime length calculation**
Create a position where X has 5 consecutive made points (e.g., 4-8).
Success: max_prime_length_x = 5.

**[U] Feature vector length**
Extract features from 5 different positions.
Success: all vectors have the same length.

**[U] No NaN/Inf**
Extract features from 100 random positions.
Success: no NaN or Inf values in any vector.

### Functional Tests

**[F] Export 10K positions to Parquet**
Query 10K positions from the BMAB database, extract features, export.
Load in Python with pandas.
Success: DataFrame has correct shape (10000, ~44), correct column names,
no null values.

**[F] Feature consistency across export**
Export 1000 positions, re-extract features from the same base_records.
Compare values.
Success: all values identical (deterministic).

**[F] Normalization round-trip**
Normalize features, then denormalize using stored parameters.
Success: original values recovered (within float64 precision).
