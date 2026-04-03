package gbf

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"math"
)

// PositionToBaseRecord converts a PositionState into a GBF BaseRecord.
func PositionToBaseRecord(pos *PositionState) (*BaseRecord, error) {
	rec := &BaseRecord{}

	for i := 0; i < 24; i++ {
		count := pos.Board[i]
		if count > 0 {
			rec.PointCounts[i] = uint8(count)
			for layer := 0; layer < 4 && layer < count; layer++ {
				rec.LayersX[layer] |= 1 << uint(i)
			}
		} else if count < 0 {
			absCount := -count
			rec.PointCounts[i] = uint8(absCount)
			for layer := 0; layer < 4 && layer < absCount; layer++ {
				rec.LayersO[layer] |= 1 << uint(i)
			}
		}
	}

	rec.BarX = uint8(pos.BarX)
	rec.BarO = uint8(pos.BarO)
	rec.BorneOffX = uint8(pos.BorneOffX)
	rec.BorneOffO = uint8(pos.BorneOffO)
	rec.SideToMove = uint8(pos.SideToMove)

	if pos.CubeValue <= 0 {
		rec.CubeLog2 = 0
	} else {
		rec.CubeLog2 = uint8(math.Log2(float64(pos.CubeValue)))
	}
	rec.CubeOwner = uint8(pos.CubeOwner)

	rec.AwayX = uint8(pos.AwayX)
	rec.AwayO = uint8(pos.AwayO)

	rec.PipX = computePipCountX(pos)
	rec.PipO = computePipCountO(pos)

	if err := validateCheckerCounts(pos, rec); err != nil {
		return nil, err
	}

	rec.Zobrist = ComputeZobrist(rec)

	return rec, nil
}

// BaseRecordToPosition converts a BaseRecord back into a PositionState.
func BaseRecordToPosition(rec *BaseRecord) *PositionState {
	pos := &PositionState{}

	for i := 0; i < 24; i++ {
		count := int(rec.PointCounts[i])
		if count == 0 {
			continue
		}
		if rec.LayersX[0]&(1<<uint(i)) != 0 {
			pos.Board[i] = count
		} else if rec.LayersO[0]&(1<<uint(i)) != 0 {
			pos.Board[i] = -count
		}
	}

	pos.BarX = int(rec.BarX)
	pos.BarO = int(rec.BarO)
	pos.BorneOffX = int(rec.BorneOffX)
	pos.BorneOffO = int(rec.BorneOffO)
	pos.SideToMove = int(rec.SideToMove)
	pos.CubeValue = 1 << rec.CubeLog2
	pos.CubeOwner = int(rec.CubeOwner)
	pos.AwayX = int(rec.AwayX)
	pos.AwayO = int(rec.AwayO)

	return pos
}

func computePipCountX(pos *PositionState) uint16 {
	var pip int
	for i := 0; i < 24; i++ {
		if pos.Board[i] > 0 {
			pip += pos.Board[i] * (i + 1)
		}
	}
	pip += pos.BarX * 25
	return uint16(pip)
}

func computePipCountO(pos *PositionState) uint16 {
	var pip int
	for i := 0; i < 24; i++ {
		if pos.Board[i] < 0 {
			count := -pos.Board[i]
			pip += count * (24 - i)
		}
	}
	pip += pos.BarO * 25
	return uint16(pip)
}

func validateCheckerCounts(pos *PositionState, rec *BaseRecord) error {
	var totalX, totalO int
	for i := 0; i < 24; i++ {
		if pos.Board[i] > 0 {
			totalX += pos.Board[i]
		} else if pos.Board[i] < 0 {
			totalO += -pos.Board[i]
		}
	}
	totalX += pos.BarX + pos.BorneOffX
	totalO += pos.BarO + pos.BorneOffO

	if totalX != MaxCheckers {
		return fmt.Errorf("player X has %d checkers, expected %d", totalX, MaxCheckers)
	}
	if totalO != MaxCheckers {
		return fmt.Errorf("player O has %d checkers, expected %d", totalO, MaxCheckers)
	}

	for i := 0; i < 24; i++ {
		count := int(rec.PointCounts[i])
		for layer := 0; layer < 4; layer++ {
			hasX := rec.LayersX[layer]&(1<<uint(i)) != 0
			hasO := rec.LayersO[layer]&(1<<uint(i)) != 0
			if count > layer {
				if !hasX && !hasO {
					return fmt.Errorf("point %d: layer %d should be set (count=%d)", i, layer+1, count)
				}
			} else {
				if hasX || hasO {
					return fmt.Errorf("point %d: layer %d should not be set (count=%d)", i, layer+1, count)
				}
			}
		}
	}

	return nil
}

// MarshalBaseRecord serializes a BaseRecord to exactly BaseRecordSize bytes.
func MarshalBaseRecord(rec *BaseRecord) []byte {
	buf := make([]byte, BaseRecordSize)
	offset := 0

	for i := 0; i < 4; i++ {
		binary.LittleEndian.PutUint32(buf[offset:], rec.LayersX[i])
		offset += 4
	}
	for i := 0; i < 4; i++ {
		binary.LittleEndian.PutUint32(buf[offset:], rec.LayersO[i])
		offset += 4
	}

	for i := 0; i < 24; i += 2 {
		low := rec.PointCounts[i] & 0x0F
		high := uint8(0)
		if i+1 < 24 {
			high = rec.PointCounts[i+1] & 0x0F
		}
		buf[offset] = low | (high << 4)
		offset++
	}

	buf[offset] = rec.BarX
	offset++
	buf[offset] = rec.BarO
	offset++
	buf[offset] = rec.BorneOffX
	offset++
	buf[offset] = rec.BorneOffO
	offset++

	buf[offset] = rec.SideToMove
	offset++
	buf[offset] = rec.CubeLog2
	offset++
	buf[offset] = rec.CubeOwner
	offset++

	buf[offset] = rec.AwayX
	offset++
	buf[offset] = rec.AwayO
	offset++

	binary.LittleEndian.PutUint16(buf[offset:], rec.PipX)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], rec.PipO)
	offset += 2

	binary.LittleEndian.PutUint64(buf[offset:], rec.Zobrist)
	offset += 8

	buf[offset] = rec.BlockCount
	// Remaining bytes are padding (already zero)

	return buf
}

// UnmarshalBaseRecord deserializes a BaseRecord from exactly BaseRecordSize bytes.
func UnmarshalBaseRecord(data []byte) (*BaseRecord, error) {
	if len(data) < BaseRecordSize {
		return nil, fmt.Errorf("data too short: need %d bytes, got %d", BaseRecordSize, len(data))
	}

	rec := &BaseRecord{}
	offset := 0

	for i := 0; i < 4; i++ {
		rec.LayersX[i] = binary.LittleEndian.Uint32(data[offset:])
		offset += 4
	}
	for i := 0; i < 4; i++ {
		rec.LayersO[i] = binary.LittleEndian.Uint32(data[offset:])
		offset += 4
	}

	for i := 0; i < 24; i += 2 {
		b := data[offset]
		rec.PointCounts[i] = b & 0x0F
		if i+1 < 24 {
			rec.PointCounts[i+1] = (b >> 4) & 0x0F
		}
		offset++
	}

	rec.BarX = data[offset]
	offset++
	rec.BarO = data[offset]
	offset++
	rec.BorneOffX = data[offset]
	offset++
	rec.BorneOffO = data[offset]
	offset++

	rec.SideToMove = data[offset]
	offset++
	rec.CubeLog2 = data[offset]
	offset++
	rec.CubeOwner = data[offset]
	offset++

	rec.AwayX = data[offset]
	offset++
	rec.AwayO = data[offset]
	offset++

	rec.PipX = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	rec.PipO = binary.LittleEndian.Uint16(data[offset:])
	offset += 2

	rec.Zobrist = binary.LittleEndian.Uint64(data[offset:])
	offset += 8

	rec.BlockCount = data[offset]

	return rec, nil
}

// MarshalRecord serializes a complete Record (base + analysis blocks).
func MarshalRecord(rec *Record) ([]byte, error) {
	rec.Base.BlockCount = uint8(len(rec.Blocks))

	var buf bytes.Buffer
	buf.Write(MarshalBaseRecord(&rec.Base))

	for _, block := range rec.Blocks {
		buf.WriteByte(block.BlockType)
		buf.WriteByte(block.Version)
		length := make([]byte, 2)
		binary.LittleEndian.PutUint16(length, block.BlockLength)
		buf.Write(length)
		buf.Write(block.Payload)
	}

	return buf.Bytes(), nil
}

// UnmarshalRecord deserializes a complete Record from binary data.
func UnmarshalRecord(data []byte) (*Record, error) {
	if len(data) < BaseRecordSize {
		return nil, fmt.Errorf("data too short for base record")
	}

	base, err := UnmarshalBaseRecord(data[:BaseRecordSize])
	if err != nil {
		return nil, err
	}

	rec := &Record{Base: *base}
	offset := BaseRecordSize

	for i := 0; i < int(base.BlockCount); i++ {
		if offset+4 > len(data) {
			return nil, fmt.Errorf("truncated block header at offset %d", offset)
		}
		block := AnalysisBlock{
			BlockType:   data[offset],
			Version:     data[offset+1],
			BlockLength: binary.LittleEndian.Uint16(data[offset+2:]),
		}
		offset += 4

		end := offset + int(block.BlockLength)
		if end > len(data) {
			return nil, fmt.Errorf("truncated block payload at offset %d", offset)
		}
		block.Payload = make([]byte, block.BlockLength)
		copy(block.Payload, data[offset:end])
		offset = end

		rec.Blocks = append(rec.Blocks, block)
	}

	return rec, nil
}

// WriteRecords writes multiple GBF records to a writer.
func WriteRecords(w io.Writer, records []*Record) error {
	for i, rec := range records {
		data, err := MarshalRecord(rec)
		if err != nil {
			return fmt.Errorf("record %d: %w", i, err)
		}
		if _, err := w.Write(data); err != nil {
			return fmt.Errorf("record %d write: %w", i, err)
		}
	}
	return nil
}

// MarshalCheckerPlayAnalysis encodes a CheckerPlayAnalysis into a block payload.
func MarshalCheckerPlayAnalysis(cpa *CheckerPlayAnalysis) []byte {
	size := 1 + int(cpa.MoveCount)*28
	buf := make([]byte, size)
	buf[0] = cpa.MoveCount
	offset := 1

	for i := 0; i < int(cpa.MoveCount); i++ {
		m := &cpa.Moves[i]
		binary.LittleEndian.PutUint32(buf[offset:], uint32(m.Equity))
		offset += 4
		binary.LittleEndian.PutUint16(buf[offset:], m.WinRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], m.GammonRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], m.BackgammonRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], m.OppWinRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], m.OppGammonRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], m.OppBackgammonRate)
		offset += 2
		binary.LittleEndian.PutUint16(buf[offset:], uint16(m.EquityDiff))
		offset += 2
		buf[offset] = m.PlyDepth
		offset++
		buf[offset] = m.Reserved
		offset++
		for j := 0; j < 4; j++ {
			buf[offset] = m.Move.Submoves[j][0]
			offset++
			buf[offset] = m.Move.Submoves[j][1]
			offset++
		}
	}

	return buf
}

// UnmarshalCheckerPlayAnalysis decodes a block payload into CheckerPlayAnalysis.
func UnmarshalCheckerPlayAnalysis(data []byte) (*CheckerPlayAnalysis, error) {
	if len(data) < 1 {
		return nil, fmt.Errorf("empty checker play analysis")
	}

	cpa := &CheckerPlayAnalysis{MoveCount: data[0]}
	offset := 1

	for i := 0; i < int(cpa.MoveCount); i++ {
		if offset+28 > len(data) {
			return nil, fmt.Errorf("truncated move analysis at index %d", i)
		}
		m := CheckerMoveAnalysis{}
		m.Equity = int32(binary.LittleEndian.Uint32(data[offset:]))
		offset += 4
		m.WinRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.GammonRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.BackgammonRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.OppWinRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.OppGammonRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.OppBackgammonRate = binary.LittleEndian.Uint16(data[offset:])
		offset += 2
		m.EquityDiff = int16(binary.LittleEndian.Uint16(data[offset:]))
		offset += 2
		m.PlyDepth = data[offset]
		offset++
		m.Reserved = data[offset]
		offset++
		for j := 0; j < 4; j++ {
			m.Move.Submoves[j][0] = data[offset]
			offset++
			m.Move.Submoves[j][1] = data[offset]
			offset++
		}
		cpa.Moves = append(cpa.Moves, m)
	}

	return cpa, nil
}

// MarshalCubeDecisionAnalysis encodes a CubeDecisionAnalysis into a block payload.
func MarshalCubeDecisionAnalysis(cda *CubeDecisionAnalysis) []byte {
	buf := make([]byte, 33)
	offset := 0

	binary.LittleEndian.PutUint16(buf[offset:], cda.WinRate)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], cda.GammonRate)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], cda.BackgammonRate)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], cda.OppWinRate)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], cda.OppGammonRate)
	offset += 2
	binary.LittleEndian.PutUint16(buf[offset:], cda.OppBackgammonRate)
	offset += 2

	binary.LittleEndian.PutUint32(buf[offset:], uint32(cda.CubelessNoDouble))
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], uint32(cda.CubelessDouble))
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], uint32(cda.CubefulNoDouble))
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], uint32(cda.CubefulDoubleTake))
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], uint32(cda.CubefulDoublePass))
	offset += 4

	buf[offset] = cda.BestAction

	return buf
}

// UnmarshalCubeDecisionAnalysis decodes a block payload into CubeDecisionAnalysis.
func UnmarshalCubeDecisionAnalysis(data []byte) (*CubeDecisionAnalysis, error) {
	if len(data) < 33 {
		return nil, fmt.Errorf("cube decision data too short: need 33, got %d", len(data))
	}

	cda := &CubeDecisionAnalysis{}
	offset := 0

	cda.WinRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	cda.GammonRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	cda.BackgammonRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	cda.OppWinRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	cda.OppGammonRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2
	cda.OppBackgammonRate = binary.LittleEndian.Uint16(data[offset:])
	offset += 2

	cda.CubelessNoDouble = int32(binary.LittleEndian.Uint32(data[offset:]))
	offset += 4
	cda.CubelessDouble = int32(binary.LittleEndian.Uint32(data[offset:]))
	offset += 4
	cda.CubefulNoDouble = int32(binary.LittleEndian.Uint32(data[offset:]))
	offset += 4
	cda.CubefulDoubleTake = int32(binary.LittleEndian.Uint32(data[offset:]))
	offset += 4
	cda.CubefulDoublePass = int32(binary.LittleEndian.Uint32(data[offset:]))
	offset += 4

	cda.BestAction = data[offset]

	return cda, nil
}

// MarshalEngineMetadata encodes an EngineMetadata into a block payload.
func MarshalEngineMetadata(em *EngineMetadata) []byte {
	var buf bytes.Buffer
	writeString := func(s string) {
		if len(s) > 255 {
			s = s[:255]
		}
		buf.WriteByte(byte(len(s)))
		buf.WriteString(s)
	}
	writeString(em.EngineName)
	writeString(em.EngineVersion)
	writeString(em.METName)
	buf.WriteByte(em.AnalysisType)
	return buf.Bytes()
}

// UnmarshalEngineMetadata decodes a block payload into EngineMetadata.
func UnmarshalEngineMetadata(data []byte) (*EngineMetadata, error) {
	em := &EngineMetadata{}
	offset := 0

	readString := func() (string, error) {
		if offset >= len(data) {
			return "", fmt.Errorf("truncated string length")
		}
		length := int(data[offset])
		offset++
		if offset+length > len(data) {
			return "", fmt.Errorf("truncated string data")
		}
		s := string(data[offset : offset+length])
		offset += length
		return s, nil
	}

	var err error
	em.EngineName, err = readString()
	if err != nil {
		return nil, err
	}
	em.EngineVersion, err = readString()
	if err != nil {
		return nil, err
	}
	em.METName, err = readString()
	if err != nil {
		return nil, err
	}
	if offset >= len(data) {
		return nil, fmt.Errorf("truncated analysis type")
	}
	em.AnalysisType = data[offset]

	return em, nil
}

// MarshalMatchMetadata encodes a MatchMetadata into a block payload.
func MarshalMatchMetadata(md *MatchMetadata) []byte {
	var buf bytes.Buffer
	writeString := func(s string) {
		if len(s) > 255 {
			s = s[:255]
		}
		buf.WriteByte(byte(len(s)))
		buf.WriteString(s)
	}
	writeString(md.Player1Name)
	writeString(md.Player2Name)
	writeString(md.Event)
	writeString(md.Location)
	writeString(md.Round)
	writeString(md.Date)
	writeString(md.Annotator)
	writeString(md.EngineName)
	writeString(md.EngineVersion)
	writeString(md.METName)
	length := make([]byte, 2)
	binary.LittleEndian.PutUint16(length, uint16(md.MatchLength))
	buf.Write(length)
	return buf.Bytes()
}

// UnmarshalMatchMetadata decodes a block payload into MatchMetadata.
func UnmarshalMatchMetadata(data []byte) (*MatchMetadata, error) {
	md := &MatchMetadata{}
	offset := 0

	readString := func() (string, error) {
		if offset >= len(data) {
			return "", fmt.Errorf("truncated string length")
		}
		length := int(data[offset])
		offset++
		if offset+length > len(data) {
			return "", fmt.Errorf("truncated string data")
		}
		s := string(data[offset : offset+length])
		offset += length
		return s, nil
	}

	var err error
	md.Player1Name, err = readString()
	if err != nil {
		return nil, err
	}
	md.Player2Name, err = readString()
	if err != nil {
		return nil, err
	}
	md.Event, err = readString()
	if err != nil {
		return nil, err
	}
	md.Location, err = readString()
	if err != nil {
		return nil, err
	}
	md.Round, err = readString()
	if err != nil {
		return nil, err
	}
	md.Date, err = readString()
	if err != nil {
		return nil, err
	}
	md.Annotator, err = readString()
	if err != nil {
		return nil, err
	}
	md.EngineName, err = readString()
	if err != nil {
		return nil, err
	}
	md.EngineVersion, err = readString()
	if err != nil {
		return nil, err
	}
	md.METName, err = readString()
	if err != nil {
		return nil, err
	}
	if offset+2 > len(data) {
		return nil, fmt.Errorf("truncated match length")
	}
	md.MatchLength = int(binary.LittleEndian.Uint16(data[offset:]))

	return md, nil
}

// MarshalGameBoundary encodes a GameBoundary into a block payload (11 bytes).
func MarshalGameBoundary(gb *GameBoundary) []byte {
	buf := make([]byte, 11)
	binary.LittleEndian.PutUint16(buf[0:], gb.GameNumber)
	binary.LittleEndian.PutUint16(buf[2:], gb.ScoreX)
	binary.LittleEndian.PutUint16(buf[4:], gb.ScoreO)
	buf[6] = byte(gb.Winner)
	buf[7] = gb.PointsWon
	buf[8] = gb.Crawford
	binary.LittleEndian.PutUint16(buf[9:], gb.MoveCount)
	return buf
}

// UnmarshalGameBoundary decodes a block payload into GameBoundary.
func UnmarshalGameBoundary(data []byte) (*GameBoundary, error) {
	if len(data) < 11 {
		return nil, fmt.Errorf("game boundary data too short: need 11, got %d", len(data))
	}
	gb := &GameBoundary{}
	gb.GameNumber = binary.LittleEndian.Uint16(data[0:])
	gb.ScoreX = binary.LittleEndian.Uint16(data[2:])
	gb.ScoreO = binary.LittleEndian.Uint16(data[4:])
	gb.Winner = int8(data[6])
	gb.PointsWon = data[7]
	gb.Crawford = data[8]
	gb.MoveCount = binary.LittleEndian.Uint16(data[9:])
	return gb, nil
}

// NewCheckerPlayBlock creates an AnalysisBlock for checker play analysis.
func NewCheckerPlayBlock(cpa *CheckerPlayAnalysis) AnalysisBlock {
	payload := MarshalCheckerPlayAnalysis(cpa)
	return AnalysisBlock{BlockType: BlockTypeCheckerPlay, Version: 1, BlockLength: uint16(len(payload)), Payload: payload}
}

// NewCubeDecisionBlock creates an AnalysisBlock for cube decision analysis.
func NewCubeDecisionBlock(cda *CubeDecisionAnalysis) AnalysisBlock {
	payload := MarshalCubeDecisionAnalysis(cda)
	return AnalysisBlock{BlockType: BlockTypeCubeDecision, Version: 1, BlockLength: uint16(len(payload)), Payload: payload}
}

// NewEngineMetadataBlock creates an AnalysisBlock for engine metadata.
func NewEngineMetadataBlock(em *EngineMetadata) AnalysisBlock {
	payload := MarshalEngineMetadata(em)
	return AnalysisBlock{BlockType: BlockTypeEngineMetadata, Version: 1, BlockLength: uint16(len(payload)), Payload: payload}
}

// NewMatchMetadataBlock creates an AnalysisBlock for match metadata.
func NewMatchMetadataBlock(md *MatchMetadata) AnalysisBlock {
	payload := MarshalMatchMetadata(md)
	return AnalysisBlock{BlockType: BlockTypeMatchMetadata, Version: 1, BlockLength: uint16(len(payload)), Payload: payload}
}

// NewGameBoundaryBlock creates an AnalysisBlock for a game boundary.
func NewGameBoundaryBlock(gb *GameBoundary) AnalysisBlock {
	payload := MarshalGameBoundary(gb)
	return AnalysisBlock{BlockType: BlockTypeGameBoundary, Version: 1, BlockLength: uint16(len(payload)), Payload: payload}
}

// DecodeBlock decodes an AnalysisBlock's payload into the corresponding typed struct.
func DecodeBlock(block *AnalysisBlock) (interface{}, error) {
	switch block.BlockType {
	case BlockTypeCheckerPlay:
		return UnmarshalCheckerPlayAnalysis(block.Payload)
	case BlockTypeCubeDecision:
		return UnmarshalCubeDecisionAnalysis(block.Payload)
	case BlockTypeEngineMetadata:
		return UnmarshalEngineMetadata(block.Payload)
	case BlockTypeMatchMetadata:
		return UnmarshalMatchMetadata(block.Payload)
	case BlockTypeGameBoundary:
		return UnmarshalGameBoundary(block.Payload)
	default:
		return nil, fmt.Errorf("unknown block type: %d", block.BlockType)
	}
}
