package gbf

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"math"
	"os"
	"strconv"
	"strings"
)

// ExportFeaturesNpy writes features extracted from positions to a numpy .npy file
// (format v1.0, float64, C-order). Load in Python with:
//
//	import numpy as np
//	arr = np.load("features.npy")  # shape (N, 44)
func ExportFeaturesNpy(positions []BaseRecord, path string) error {
	if len(positions) == 0 {
		return fmt.Errorf("no positions to export")
	}

	N := len(positions)
	cols := NumFeatures

	// Build numpy header dict.
	header := fmt.Sprintf("{'descr': '<f8', 'fortran_order': False, 'shape': (%d, %d), }", N, cols)
	// Total prefix before header data: magic(6) + version(2) + headerlen(2) = 10 bytes.
	// Pad so that 10 + len(header) is a multiple of 64.
	const prefix = 10
	used := prefix + len(header) + 1 // +1 for the trailing '\n'
	padNeeded := (64 - used%64) % 64
	header += strings.Repeat(" ", padNeeded) + "\n"

	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create %s: %w", path, err)
	}
	defer f.Close()

	w := bufio.NewWriterSize(f, 1<<20)

	// Magic "\x93NUMPY" + version 1.0.
	w.Write([]byte{0x93, 'N', 'U', 'M', 'P', 'Y', 1, 0})

	// Header length as uint16 LE.
	var hl [2]byte
	binary.LittleEndian.PutUint16(hl[:], uint16(len(header)))
	w.Write(hl[:])

	w.WriteString(header)

	// Data: float64 LE, row-major.
	var buf [8]byte
	for _, rec := range positions {
		for _, v := range ExtractAllFeatures(rec) {
			binary.LittleEndian.PutUint64(buf[:], math.Float64bits(v))
			w.Write(buf[:])
		}
	}

	return w.Flush()
}

// ExportFeaturesCSV writes features to a CSV file with a header row.
// Readable with pandas.read_csv(path). Columns match FeatureNames().
func ExportFeaturesCSV(positions []BaseRecord, path string) error {
	if len(positions) == 0 {
		return fmt.Errorf("no positions to export")
	}

	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create %s: %w", path, err)
	}
	defer f.Close()

	w := bufio.NewWriterSize(f, 1<<20)

	names := FeatureNames()
	w.WriteString(strings.Join(names, ","))
	w.WriteByte('\n')

	row := make([]string, NumFeatures)
	for _, rec := range positions {
		for i, v := range ExtractAllFeatures(rec) {
			row[i] = strconv.FormatFloat(v, 'f', -1, 64)
		}
		w.WriteString(strings.Join(row, ","))
		w.WriteByte('\n')
	}

	return w.Flush()
}
