package gbf

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// FileFormat represents a supported backgammon file format.
type FileFormat string

const (
	FormatXG      FileFormat = "xg"  // eXtreme Gammon binary
	FormatSGF     FileFormat = "sgf" // GNU Backgammon SGF
	FormatMAT     FileFormat = "mat" // GNU Backgammon MAT
	FormatBGF     FileFormat = "bgf" // BGBlitz binary
	FormatTXT     FileFormat = "txt" // BGBlitz text export
	FormatGBF     FileFormat = "gbf" // Gammon Binary Format
	FormatUnknown FileFormat = "unknown"
)

// DetectFormat determines the file format from its extension.
func DetectFormat(filename string) FileFormat {
	ext := strings.ToLower(filepath.Ext(filename))
	switch ext {
	case ".xg":
		return FormatXG
	case ".sgf":
		return FormatSGF
	case ".mat":
		return FormatMAT
	case ".bgf":
		return FormatBGF
	case ".txt":
		return FormatTXT
	case ".gbf":
		return FormatGBF
	default:
		return FormatUnknown
	}
}

// ParseFile parses a backgammon file in any supported format and returns
// a GBF Match. The format is auto-detected from the file extension.
func ParseFile(filename string) (*Match, error) {
	format := DetectFormat(filename)
	return ParseFileAs(filename, format)
}

// ParseFileAs parses a backgammon file using the specified format.
func ParseFileAs(filename string, format FileFormat) (*Match, error) {
	switch format {
	case FormatXG:
		return ParseXGFile(filename)
	case FormatSGF:
		return ParseSGFFile(filename)
	case FormatMAT:
		return ParseMATFile(filename)
	case FormatBGF:
		return ParseBGFFile(filename)
	case FormatTXT:
		return parseTXTAsMatch(filename)
	case FormatGBF:
		return ReadGBFFile(filename)
	default:
		return nil, fmt.Errorf("unsupported file format: %s", format)
	}
}

// parseTXTAsMatch wraps a text position parse into a single-position Match.
func parseTXTAsMatch(filename string) (*Match, error) {
	pos, cpa, cda, err := ParseBGFTextFile(filename)
	if err != nil {
		return nil, err
	}
	return positionToMatch(pos, cpa, cda), nil
}

func positionToMatch(pos *PositionState, cpa *CheckerPlayAnalysis, cda *CubeDecisionAnalysis) *Match {
	mv := Move{
		Position: pos,
		Player:   pos.SideToMove,
		Dice:     pos.Dice,
	}

	if cda != nil {
		mv.MoveType = MoveTypeCube
		mv.CubeAnalysis = cda
	} else {
		mv.MoveType = MoveTypeChecker
	}
	if cpa != nil {
		mv.CheckerAnalysis = cpa
	}

	return &Match{
		Metadata: MatchMetadata{
			Player1Name: pos.Player1Name,
			Player2Name: pos.Player2Name,
			MatchLength: pos.MatchLength,
		},
		Games: []Game{{
			GameNumber: 1,
			Moves:      []Move{mv},
		}},
	}
}

// WriteGBFFile writes a Match to a GBF binary file.
func WriteGBFFile(filename string, match *Match) error {
	f, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("creating GBF file: %w", err)
	}
	defer f.Close()

	return WriteGBF(f, match)
}

// WriteGBF writes a Match to a writer in GBF binary format.
// The output uses a structured layout:
//  1. A header record (zeroed base record) with a MatchMetadata block (type=4)
//  2. For each game:
//     a. A game boundary record (zeroed base record) with a GameBoundary block (type=5)
//     b. Move records with their analysis blocks
func WriteGBF(w io.Writer, match *Match) error {
	// Write match metadata header record
	headerRec := &Record{
		Blocks: []AnalysisBlock{
			NewMatchMetadataBlock(&match.Metadata),
		},
	}
	headerData, err := MarshalRecord(headerRec)
	if err != nil {
		return fmt.Errorf("marshaling match metadata: %w", err)
	}
	if _, err := w.Write(headerData); err != nil {
		return fmt.Errorf("writing match metadata: %w", err)
	}

	for _, game := range match.Games {
		// Write game boundary record
		crawford := uint8(0)
		if game.Crawford {
			crawford = 1
		}
		gb := &GameBoundary{
			GameNumber: uint16(game.GameNumber),
			ScoreX:     uint16(game.InitialScore[0]),
			ScoreO:     uint16(game.InitialScore[1]),
			Winner:     int8(game.Winner),
			PointsWon:  uint8(game.PointsWon),
			Crawford:   crawford,
			MoveCount:  uint16(len(game.Moves)),
		}
		gameRec := &Record{
			Blocks: []AnalysisBlock{
				NewGameBoundaryBlock(gb),
			},
		}
		gameData, err := MarshalRecord(gameRec)
		if err != nil {
			return fmt.Errorf("marshaling game boundary: %w", err)
		}
		if _, err := w.Write(gameData); err != nil {
			return fmt.Errorf("writing game boundary: %w", err)
		}

		// Write move records
		for _, mv := range game.Moves {
			if mv.Position == nil {
				continue
			}
			rec, err := MoveToRecord(&mv, &match.Metadata)
			if err != nil {
				continue
			}
			data, err := MarshalRecord(rec)
			if err != nil {
				continue
			}
			if _, err := w.Write(data); err != nil {
				return fmt.Errorf("writing move record: %w", err)
			}
		}
	}

	return nil
}

// MoveToRecord converts a Move with its position and analysis into a GBF Record.
func MoveToRecord(mv *Move, metadata *MatchMetadata) (*Record, error) {
	base, err := PositionToBaseRecord(mv.Position)
	if err != nil {
		return nil, err
	}

	rec := &Record{Base: *base}

	// Add analysis blocks
	if mv.CheckerAnalysis != nil {
		rec.Blocks = append(rec.Blocks, NewCheckerPlayBlock(mv.CheckerAnalysis))
	}

	if mv.CubeAnalysis != nil {
		rec.Blocks = append(rec.Blocks, NewCubeDecisionBlock(mv.CubeAnalysis))
	}

	// Add engine metadata if available
	if metadata != nil && metadata.EngineName != "" {
		em := &EngineMetadata{
			EngineName:    metadata.EngineName,
			EngineVersion: metadata.EngineVersion,
			METName:       metadata.METName,
		}
		rec.Blocks = append(rec.Blocks, NewEngineMetadataBlock(em))
	}

	return rec, nil
}

// ReadGBFFile reads a GBF binary file and returns a Match.
func ReadGBFFile(filename string) (*Match, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, fmt.Errorf("reading GBF file: %w", err)
	}

	return ReadGBF(data)
}

// ReadGBF parses GBF binary data and returns a Match.
// It recognizes the structured layout with match metadata (type=4) and
// game boundary (type=5) blocks, as well as the legacy flat format
// (just move records without headers).
func ReadGBF(data []byte) (*Match, error) {
	match := &Match{}

	offset := 0
	var currentGame *Game
	hasStructuredFormat := false

	for offset < len(data) {
		if offset+BaseRecordSize > len(data) {
			break
		}

		rec, err := UnmarshalRecord(data[offset:])
		if err != nil {
			return nil, fmt.Errorf("record at offset %d: %w", offset, err)
		}

		// Advance past base record + all blocks
		advance := BaseRecordSize
		for _, block := range rec.Blocks {
			advance += 4 + int(block.BlockLength) // header + payload
		}

		// Check for special record types (zeroed base record with metadata/boundary blocks)
		isMetaRecord := false
		for _, block := range rec.Blocks {
			switch block.BlockType {
			case BlockTypeMatchMetadata:
				md, err := UnmarshalMatchMetadata(block.Payload)
				if err != nil {
					return nil, fmt.Errorf("match metadata at offset %d: %w", offset, err)
				}
				match.Metadata = *md
				hasStructuredFormat = true
				isMetaRecord = true

			case BlockTypeGameBoundary:
				gb, err := UnmarshalGameBoundary(block.Payload)
				if err != nil {
					return nil, fmt.Errorf("game boundary at offset %d: %w", offset, err)
				}
				game := Game{
					GameNumber:   int(gb.GameNumber),
					InitialScore: [2]int{int(gb.ScoreX), int(gb.ScoreO)},
					Winner:       int(gb.Winner),
					PointsWon:    int(gb.PointsWon),
					Crawford:     gb.Crawford == 1,
				}
				match.Games = append(match.Games, game)
				currentGame = &match.Games[len(match.Games)-1]
				hasStructuredFormat = true
				isMetaRecord = true
			}
		}

		if !isMetaRecord {
			// Regular move record
			mv := RecordToMove(rec)

			if currentGame == nil {
				// Legacy format or first record before any game boundary
				if !hasStructuredFormat {
					match.Games = append(match.Games, Game{GameNumber: 1})
					currentGame = &match.Games[0]
				} else {
					// Structured format but record before first game — skip
					offset += advance
					continue
				}
			}
			currentGame.Moves = append(currentGame.Moves, mv)
		}

		offset += advance
	}

	// Legacy format: extract metadata from first engine metadata block
	if !hasStructuredFormat && len(match.Games) > 0 {
		for _, mv := range match.Games[0].Moves {
			if mv.EngineMetadata != nil {
				match.Metadata.EngineName = mv.EngineMetadata.EngineName
				match.Metadata.EngineVersion = mv.EngineMetadata.EngineVersion
				match.Metadata.METName = mv.EngineMetadata.METName
				break
			}
		}
	}

	return match, nil
}

// RecordToMove converts a GBF Record back to a Move.
func RecordToMove(rec *Record) Move {
	pos := BaseRecordToPosition(&rec.Base)

	mv := Move{
		Position: pos,
		Player:   pos.SideToMove,
	}

	for _, block := range rec.Blocks {
		decoded, err := DecodeBlock(&block)
		if err != nil {
			continue
		}

		switch v := decoded.(type) {
		case *CheckerPlayAnalysis:
			mv.MoveType = MoveTypeChecker
			mv.CheckerAnalysis = v
		case *CubeDecisionAnalysis:
			mv.MoveType = MoveTypeCube
			mv.CubeAnalysis = v
		case *EngineMetadata:
			mv.EngineMetadata = v
		}
	}

	if mv.MoveType == "" {
		mv.MoveType = MoveTypeChecker
	}

	return mv
}

// MatchToRecords converts all positions in a Match to GBF Records.
func MatchToRecords(match *Match) ([]*Record, error) {
	var records []*Record
	var errs []error

	for _, game := range match.Games {
		for _, mv := range game.Moves {
			if mv.Position == nil {
				continue
			}
			rec, err := MoveToRecord(&mv, &match.Metadata)
			if err != nil {
				errs = append(errs, err)
				continue
			}
			records = append(records, rec)
		}
	}

	if len(records) == 0 && len(errs) > 0 {
		return nil, fmt.Errorf("no valid records: first error: %w", errs[0])
	}

	return records, nil
}
