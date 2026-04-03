package gbf_test

import (
	"context"
	"math"
	"os"
	"path/filepath"
	"testing"

	gbf "github.com/kevung/gbf"
)

// standardOpeningPosition returns the BaseRecord for the standard backgammon opening.
// X: 2@23, 5@12, 3@7, 5@5
// O: 2@0,  5@11, 3@16, 5@18
func standardOpeningRecord(t *testing.T) gbf.BaseRecord {
	t.Helper()
	pos := &gbf.PositionState{
		CubeValue:   1,
		CubeOwner:   gbf.CubeCenter,
		MatchLength: 0,
		AwayX:       0,
		AwayO:       0,
	}
	pos.Board[23] = 2
	pos.Board[12] = 5
	pos.Board[7] = 3
	pos.Board[5] = 5
	pos.Board[0] = -2
	pos.Board[11] = -5
	pos.Board[16] = -3
	pos.Board[18] = -5
	pos.BorneOffX = 0
	pos.BorneOffO = 0

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}
	return *rec
}

// [U] Starting position features.
func TestStartingPositionFeatures(t *testing.T) {
	rec := standardOpeningRecord(t)
	f := gbf.ExtractAllFeatures(rec)

	// pip_x and pip_o: 2*24 + 5*13 + 3*8 + 5*6 = 48+65+24+30 = 167.
	pipX := f[28]
	pipO := f[29]
	if pipX != 167 {
		t.Errorf("pip_x: got %.0f, want 167", pipX)
	}
	if pipO != 167 {
		t.Errorf("pip_o: got %.0f, want 167", pipO)
	}

	// blot_count_x: no isolated X checkers.
	blotX := f[34]
	if blotX != 0 {
		t.Errorf("blot_x: got %.0f, want 0", blotX)
	}

	// made_point_count_x: pts 5, 7, 12, 23 each have ≥2 X checkers = 4.
	madeX := f[36]
	if madeX != 4 {
		t.Errorf("made_x: got %.0f, want 4", madeX)
	}

	// position_class = contact.
	class := f[43]
	if class != float64(gbf.ClassContact) {
		t.Errorf("pos_class: got %.0f, want %d (contact)", class, gbf.ClassContact)
	}
}

// [U] Bearoff position classification.
func TestBearoffClassification(t *testing.T) {
	pos := &gbf.PositionState{CubeValue: 1}
	// All X in home board (0-5), all O in home board (18-23).
	pos.Board[0] = 3
	pos.Board[1] = 3
	pos.Board[2] = 3
	pos.Board[3] = 3
	pos.Board[4] = 3
	pos.Board[18] = -3
	pos.Board[19] = -3
	pos.Board[20] = -3
	pos.Board[21] = -3
	pos.Board[22] = -3

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	class := gbf.ClassifyPosition(*rec)
	if class != gbf.ClassBearoff {
		t.Errorf("ClassifyPosition: got %d, want %d (bearoff)", class, gbf.ClassBearoff)
	}
}

// [U] Race position classification.
func TestRaceClassification(t *testing.T) {
	pos := &gbf.PositionState{CubeValue: 1}
	// X in 6-11, O in 12-17 — no contact, but not in home boards.
	pos.Board[6] = 3
	pos.Board[7] = 3
	pos.Board[8] = 3
	pos.Board[9] = 3
	pos.Board[10] = 3
	pos.Board[12] = -3
	pos.Board[13] = -3
	pos.Board[14] = -3
	pos.Board[15] = -3
	pos.Board[16] = -3

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	class := gbf.ClassifyPosition(*rec)
	if class != gbf.ClassRace {
		t.Errorf("ClassifyPosition: got %d, want %d (race)", class, gbf.ClassRace)
	}
}

// [U] Prime length calculation.
func TestPrimeLengthCalculation(t *testing.T) {
	pos := &gbf.PositionState{CubeValue: 1}
	// X has 5 consecutive made points at 4-8 (indices 4,5,6,7,8).
	pos.Board[4] = 2
	pos.Board[5] = 2
	pos.Board[6] = 2
	pos.Board[7] = 2
	pos.Board[8] = 2
	// O has remaining checkers so total = 15 each.
	pos.Board[23] = 5
	pos.Board[0] = -5
	pos.Board[11] = -5
	pos.Board[18] = -5

	rec, err := gbf.PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	f := gbf.ExtractDerivedFeatures(*rec)
	primeX := f[4] // prime_x
	if primeX != 5 {
		t.Errorf("prime_x: got %.0f, want 5", primeX)
	}
}

// [U] Feature vector length consistency.
func TestFeatureVectorLength(t *testing.T) {
	rec := standardOpeningRecord(t)

	raw := gbf.ExtractRawFeatures(rec)
	if len(raw) != gbf.NumRawFeatures {
		t.Errorf("raw features: got %d, want %d", len(raw), gbf.NumRawFeatures)
	}

	derived := gbf.ExtractDerivedFeatures(rec)
	if len(derived) != gbf.NumDerivedFeatures {
		t.Errorf("derived features: got %d, want %d", len(derived), gbf.NumDerivedFeatures)
	}

	all := gbf.ExtractAllFeatures(rec)
	if len(all) != gbf.NumFeatures {
		t.Errorf("all features: got %d, want %d", len(all), gbf.NumFeatures)
	}

	names := gbf.FeatureNames()
	if len(names) != gbf.NumFeatures {
		t.Errorf("feature names: got %d, want %d", len(names), gbf.NumFeatures)
	}
}

// [U] No NaN or Inf in feature vectors from real data.
func TestNoNaNInfInFeatures(t *testing.T) {
	dir := filepath.Join("data", "bmab-2025-06-23")
	if _, err := os.Stat(dir); err != nil {
		t.Skipf("BMAB dataset not found: %s", dir)
	}

	store := openSQLiteStore(t)
	importN := 10
	if testing.Short() {
		importN = 5
	}

	opts := gbf.ImportOpts{
		BatchSize:  importN,
		Limit:      importN,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	ctx := context.Background()
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		t.Fatalf("import: %v", err)
	}

	rows, err := store.DB().Query("SELECT base_record FROM positions LIMIT 100")
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer rows.Close()

	checked := 0
	for rows.Next() {
		var blob []byte
		if err := rows.Scan(&blob); err != nil {
			t.Fatalf("scan: %v", err)
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			t.Fatalf("unmarshal: %v", err)
		}
		feats := gbf.ExtractAllFeatures(*rec)
		for i, v := range feats {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				t.Errorf("feature[%d]=%v for record %d", i, v, checked)
			}
		}
		checked++
	}
	if checked == 0 {
		t.Error("no positions checked")
	}
}

// [U] Signed point counts match expected values for opening position.
func TestSignedPointCounts(t *testing.T) {
	rec := standardOpeningRecord(t)
	f := gbf.ExtractRawFeatures(rec)

	// X checkers: positive values.
	if f[23] != 2 {
		t.Errorf("point[23] (X 24-pt): got %.0f, want 2", f[23])
	}
	if f[12] != 5 {
		t.Errorf("point[12] (X 13-pt): got %.0f, want 5", f[12])
	}

	// O checkers: negative values.
	if f[0] != -2 {
		t.Errorf("point[0] (O 24-pt equiv): got %.0f, want -2", f[0])
	}
	if f[11] != -5 {
		t.Errorf("point[11] (O 12-pt): got %.0f, want -5", f[11])
	}
}

// [F] Export 10K positions to .npy — correct shape, loadable from Python.
func TestExportNpy(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping export test in short mode")
	}

	dir := filepath.Join("data", "bmab-2025-06-23")
	if _, err := os.Stat(dir); err != nil {
		t.Skipf("BMAB dataset not found: %s", dir)
	}

	store := openSQLiteStore(t)
	opts := gbf.ImportOpts{
		BatchSize:  100,
		Limit:      200,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	ctx := context.Background()
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		t.Fatalf("import: %v", err)
	}

	// Query base records.
	rows, err := store.DB().Query("SELECT base_record FROM positions LIMIT 10000")
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer rows.Close()

	var recs []gbf.BaseRecord
	for rows.Next() {
		var blob []byte
		if err := rows.Scan(&blob); err != nil {
			t.Fatalf("scan: %v", err)
		}
		rec, err := gbf.UnmarshalBaseRecord(blob)
		if err != nil {
			t.Fatalf("unmarshal: %v", err)
		}
		recs = append(recs, *rec)
	}

	if len(recs) == 0 {
		t.Fatal("no positions found")
	}

	t.Logf("exporting %d positions", len(recs))

	npyPath := filepath.Join(t.TempDir(), "features.npy")
	if err := gbf.ExportFeaturesNpy(recs, npyPath); err != nil {
		t.Fatalf("ExportFeaturesNpy: %v", err)
	}

	// Verify file size: 10 (header prefix) + header_len + N * NumFeatures * 8.
	fi, err := os.Stat(npyPath)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	expectedDataBytes := int64(len(recs)) * int64(gbf.NumFeatures) * 8
	if fi.Size() <= expectedDataBytes {
		t.Errorf("file too small: got %d bytes, data alone needs %d", fi.Size(), expectedDataBytes)
	}

	t.Logf("npy file: %d bytes for %d positions × %d features", fi.Size(), len(recs), gbf.NumFeatures)
}

// [F] CSV export — correct column count, loadable structure.
func TestExportCSV(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping export test in short mode")
	}

	dir := filepath.Join("data", "bmab-2025-06-23")
	if _, err := os.Stat(dir); err != nil {
		t.Skipf("BMAB dataset not found: %s", dir)
	}

	store := openSQLiteStore(t)
	opts := gbf.ImportOpts{
		BatchSize:  50,
		Limit:      50,
		FileParser: xgParser,
		EngineName: "eXtreme Gammon",
	}
	ctx := context.Background()
	if _, err := gbf.ImportDirectory(ctx, store, dir, opts); err != nil {
		t.Fatalf("import: %v", err)
	}

	rows, err := store.DB().Query("SELECT base_record FROM positions LIMIT 1000")
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer rows.Close()

	var recs []gbf.BaseRecord
	for rows.Next() {
		var blob []byte
		rows.Scan(&blob)
		rec, _ := gbf.UnmarshalBaseRecord(blob)
		recs = append(recs, *rec)
	}

	csvPath := filepath.Join(t.TempDir(), "features.csv")
	if err := gbf.ExportFeaturesCSV(recs, csvPath); err != nil {
		t.Fatalf("ExportFeaturesCSV: %v", err)
	}

	// Count columns in header line.
	data, err := os.ReadFile(csvPath)
	if err != nil {
		t.Fatalf("read csv: %v", err)
	}
	firstLine := ""
	for i, b := range data {
		if b == '\n' {
			firstLine = string(data[:i])
			break
		}
	}
	cols := len(splitCSV(firstLine))
	if cols != gbf.NumFeatures {
		t.Errorf("CSV columns: got %d, want %d", cols, gbf.NumFeatures)
	}
	t.Logf("CSV: %d positions × %d features, file size: %d bytes", len(recs), cols, len(data))
}

// [F] Normalization round-trip.
func TestNormalizationRoundTrip(t *testing.T) {
	rec := standardOpeningRecord(t)
	original := gbf.ExtractAllFeatures(rec)

	// Build a small dataset.
	matrix := make([][]float64, 10)
	for i := range matrix {
		matrix[i] = gbf.ExtractAllFeatures(rec)
	}

	params := gbf.ComputeNormParams(matrix)
	normalized := gbf.StandardScale(original, params)
	recovered := gbf.InverseStandardScale(normalized, params)

	for i, v := range recovered {
		if math.Abs(v-original[i]) > 1e-9 {
			t.Errorf("round-trip mismatch at feature %d: got %.15f, want %.15f", i, v, original[i])
		}
	}
}

func splitCSV(s string) []string {
	var result []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == ',' {
			result = append(result, s[start:i])
			start = i + 1
		}
	}
	result = append(result, s[start:])
	return result
}
