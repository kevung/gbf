# M4 — Feature Extraction ✅

## Objective

Define and implement the 44-dimensional numeric feature vector extracted
from each position for dimensionality reduction and clustering. Provide
export to numpy-compatible formats for Python analysis.

## Pre-requisites

M3 (at least 1 BMAB region imported into SQLite).

## Sub-steps

### M4.1 — Raw Feature Vector ✅

Implemented in `features.go` via `ExtractRawFeatures(rec BaseRecord) []float64`.

| Index | Feature         | Source                         | Range     |
|-------|-----------------|--------------------------------|-----------|
| 0-23  | point_01…24     | Signed: +PointCounts[i] if X, −PointCounts[i] if O | −15 to 15 |
| 24    | bar_x           | BarX                           | 0-15      |
| 25    | bar_o           | BarO                           | 0-15      |
| 26    | borne_off_x     | BorneOffX                      | 0-15      |
| 27    | borne_off_o     | BorneOffO                      | 0-15      |
| 28    | pip_x           | PipX                           | 0-375     |
| 29    | pip_o           | PipO                           | 0-375     |
| 30    | cube_log2       | CubeLog2                       | 0-6       |
| 31    | cube_owner      | CubeOwner                      | 0-2       |
| 32    | away_x          | AwayX                          | 0-255     |
| 33    | away_o          | AwayO                          | 0-255     |

34 raw dimensions.

### M4.2 — Derived Features ✅

Implemented via `ExtractDerivedFeatures(rec BaseRecord) []float64`.

| Index | Feature         | Computation                                  |
|-------|-----------------|----------------------------------------------|
| 34    | blot_x          | popcount(LayersX[0] & ^LayersX[1])           |
| 35    | blot_o          | popcount(LayersO[0] & ^LayersO[1])           |
| 36    | made_x          | popcount(LayersX[1])                         |
| 37    | made_o          | popcount(LayersO[1])                         |
| 38    | prime_x         | longest consecutive run in LayersX[1]        |
| 39    | prime_o         | longest consecutive run in LayersO[1]        |
| 40    | anchor_x        | popcount(LayersX[1] & bits 18-23)            |
| 41    | anchor_o        | popcount(LayersO[1] & bits 0-5)              |
| 42    | pip_diff        | PipX − PipO                                  |
| 43    | pos_class       | 0=contact, 1=race, 2=bearoff                 |

44 total dimensions.

### M4.3 — Position Classification ✅

`ClassifyPosition(rec BaseRecord) int` in `features.go`:

- **Contact (0)**: X's highest checker index ≥ O's lowest checker index.
  (Bar checkers extend the range: BarX → maxX=24; BarO → minO=−1.)
- **Bearoff (2)**: No contact, all X in pts 0-5 (no bar), all O in pts 18-23 (no bar).
- **Race (1)**: No contact and not bearoff.

### M4.4 — Normalization ✅

Implemented in `normalize.go`:
- `ComputeNormParams(features [][]float64) NormalizationParams` — computes mean, std, min, max
- `StandardScale(f, params)` / `InverseStandardScale(f, params)` — zero-mean/unit-variance
- `MinMaxScale(f, params)` — [0, 1] scaling

### M4.5 — Go Implementation ✅

`features.go` exports:
```go
func ExtractRawFeatures(rec BaseRecord) []float64    // 34 features
func ExtractDerivedFeatures(rec BaseRecord) []float64 // 10 features
func ExtractAllFeatures(rec BaseRecord) []float64    // 44 features
func ClassifyPosition(rec BaseRecord) int            // 0/1/2
func FeatureNames() []string                         // 44 column names
```

Constants: `NumRawFeatures=34`, `NumDerivedFeatures=10`, `NumFeatures=44`,
`ClassContact=0`, `ClassRace=1`, `ClassBearoff=2`.

### M4.6 — Export to Numpy ✅

`export.go` implements two paths:

**Path A — CSV** (`ExportFeaturesCSV`): column-named CSV readable by `pandas.read_csv()`.
Export of 1,000 positions: 98,747 bytes.

**Path B — .npy** (`ExportFeaturesNpy`): numpy v1.0 binary format (float64 LE, C-order).
Load in Python: `np.load("features.npy")` → shape (N, 44).
Export of 10,000 positions: 3,520,128 bytes (= 10000 × 44 × 8 bytes data + header).

Parquet dependency was avoided to keep the module lean; CSV + .npy cover
all M5 visualization use cases.

## Files Created

| File | Action | Status |
|------|--------|--------|
| `features.go` | Create (feature extraction + classification + names) | ✅ |
| `normalize.go` | Create (ComputeNormParams, StandardScale, MinMaxScale) | ✅ |
| `export.go` | Create (ExportFeaturesNpy, ExportFeaturesCSV) | ✅ |
| `features_test.go` | Create (unit + functional tests) | ✅ |

## Acceptance Criteria

- [x] `ExtractAllFeatures` returns a vector of length 44
- [x] Starting position: pip_x = pip_o = 167, made_x = 4, blot_x = 0, class = contact
- [x] ClassifyPosition correct for contact, race, bearoff positions
- [x] .npy export of 10K positions: correct size, loadable by numpy
- [x] No NaN or Inf in any exported feature vector (tested on 100 real positions)

## Tests

All tests pass; large tests skip with `-short`:

### Unit Tests (always run)

**[U] Starting position features** ✅
`TestStartingPositionFeatures`: pip_x=pip_o=167, blot_x=0, made_x=4, class=contact.

**[U] Bearoff classification** ✅
`TestBearoffClassification`: all X in 0-5, all O in 18-23 → class=2.

**[U] Race classification** ✅
`TestRaceClassification`: X in 6-11, O in 12-17, no overlap → class=1.

**[U] Prime length** ✅
`TestPrimeLengthCalculation`: 5 consecutive X made points 4-8 → prime_x=5.

**[U] Feature vector length** ✅
`TestFeatureVectorLength`: raw=34, derived=10, all=44, names=44.

**[U] Signed point counts** ✅
`TestSignedPointCounts`: X@23=+2, X@12=+5, O@0=−2, O@11=−5.

**[U] Normalization round-trip** ✅
`TestNormalizationRoundTrip`: StandardScale then Inverse recovers original (< 1e-9 error).

### DB-backed tests (skip with -short)

**[U] No NaN/Inf** ✅
`TestNoNaNInfInFeatures`: 100 real BMAB positions, zero NaN/Inf.

**[F] .npy export** ✅
`TestExportNpy`: 10K positions exported, file size = 3,520,128 bytes.

**[F] CSV export** ✅
`TestExportCSV`: 1,000 positions, 44 columns, correct header.

## Notes

**Signed point count encoding**: PointCounts stores the absolute count (0-15).
The sign is derived from LayersX[0]: if bit i is set, the count is positive (X);
otherwise negative (O). Points with 0 checkers have count=0.

**Prime computation**: uses LayersX[1]/LayersO[1] (≥2 checkers = "made point"),
consistent with the backgammon definition of a prime as consecutive made points.

**Anchor definition**: an anchor is a made point in the opponent's home board.
X's anchors: made points in pts 18-23 (O's home). O's anchors: made points in pts 0-5 (X's home).
