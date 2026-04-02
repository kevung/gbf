package gbf

import (
	"bytes"
	"testing"
)

// standardStartPosition returns the standard backgammon starting position.
func standardStartPosition() *PositionState {
	pos := &PositionState{
		SideToMove: PlayerX,
		CubeValue:  1,
		CubeOwner:  CubeCenter,
		AwayX:      7,
		AwayO:      7,
	}
	// Player X (positive): 6pt×5, 8pt×3, 13pt×5, 24pt×2
	pos.Board[5] = 5
	pos.Board[7] = 3
	pos.Board[12] = 5
	pos.Board[23] = 2
	// Player O (negative): 6pt×-5, 8pt×-3, 13pt×-5, 24pt×-2
	pos.Board[18] = -5
	pos.Board[16] = -3
	pos.Board[11] = -5
	pos.Board[0] = -2
	return pos
}

func TestBaseRecordRoundTrip(t *testing.T) {
	pos := standardStartPosition()

	rec, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatalf("PositionToBaseRecord: %v", err)
	}

	// Verify Zobrist is non-zero
	if rec.Zobrist == 0 {
		t.Error("Zobrist hash is zero")
	}

	// Verify pip counts
	// X pips: 5×6 + 3×8 + 5×13 + 2×24 = 30+24+65+48 = 167
	if rec.PipX != 167 {
		t.Errorf("PipX = %d, want 167", rec.PipX)
	}
	// O pips: 5×(24-18) + 3×(24-16) + 5×(24-11) + 2×(24-0) = 30+24+65+48 = 167
	if rec.PipO != 167 {
		t.Errorf("PipO = %d, want 167", rec.PipO)
	}

	// Marshal and unmarshal
	data := MarshalBaseRecord(rec)
	if len(data) != BaseRecordSize {
		t.Errorf("marshaled size = %d, want %d", len(data), BaseRecordSize)
	}

	rec2, err := UnmarshalBaseRecord(data)
	if err != nil {
		t.Fatalf("UnmarshalBaseRecord: %v", err)
	}

	// Verify round-trip
	if rec2.Zobrist != rec.Zobrist {
		t.Errorf("Zobrist mismatch: %x vs %x", rec2.Zobrist, rec.Zobrist)
	}
	if rec2.PipX != rec.PipX {
		t.Errorf("PipX mismatch: %d vs %d", rec2.PipX, rec.PipX)
	}
	if rec2.PipO != rec.PipO {
		t.Errorf("PipO mismatch: %d vs %d", rec2.PipO, rec.PipO)
	}
	if rec2.SideToMove != rec.SideToMove {
		t.Errorf("SideToMove mismatch")
	}
	if rec2.CubeLog2 != rec.CubeLog2 {
		t.Errorf("CubeLog2 mismatch")
	}
	if rec2.CubeOwner != rec.CubeOwner {
		t.Errorf("CubeOwner mismatch")
	}

	// Convert back to position
	pos2 := BaseRecordToPosition(rec2)
	for i := 0; i < 24; i++ {
		if pos2.Board[i] != pos.Board[i] {
			t.Errorf("Board[%d] = %d, want %d", i, pos2.Board[i], pos.Board[i])
		}
	}
	if pos2.CubeValue != pos.CubeValue {
		t.Errorf("CubeValue = %d, want %d", pos2.CubeValue, pos.CubeValue)
	}
}

func TestZobristDeterminism(t *testing.T) {
	pos := standardStartPosition()
	pos.CubeValue = 2
	pos.CubeOwner = CubeX
	pos.AwayX = 5
	pos.AwayO = 3

	rec1, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatal(err)
	}

	rec2, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatal(err)
	}

	if rec1.Zobrist != rec2.Zobrist {
		t.Errorf("Zobrist not deterministic: %x vs %x", rec1.Zobrist, rec2.Zobrist)
	}

	// Different position should have different hash
	pos.Board[5] = 4
	pos.Board[4] = 1
	rec3, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatal(err)
	}

	if rec3.Zobrist == rec1.Zobrist {
		t.Error("Different positions produce same Zobrist hash")
	}
}

func TestCheckerPlayAnalysisRoundTrip(t *testing.T) {
	cpa := &CheckerPlayAnalysis{
		MoveCount: 2,
		Moves: []CheckerMoveAnalysis{
			{
				Equity:            15233,
				WinRate:           7500,
				GammonRate:        1200,
				BackgammonRate:    50,
				OppWinRate:        2500,
				OppGammonRate:     300,
				OppBackgammonRate: 10,
				EquityDiff:        0,
				PlyDepth:          3,
				Move: MoveEncoding{
					Submoves: [4][2]uint8{
						{23, 20}, {23, 18},
						{MoveUnused, MoveUnused}, {MoveUnused, MoveUnused},
					},
				},
			},
			{
				Equity:            14500,
				WinRate:           7300,
				GammonRate:        1100,
				BackgammonRate:    40,
				OppWinRate:        2700,
				OppGammonRate:     350,
				OppBackgammonRate: 15,
				EquityDiff:        -733,
				PlyDepth:          3,
				Move: MoveEncoding{
					Submoves: [4][2]uint8{
						{12, 9}, {12, 7},
						{MoveUnused, MoveUnused}, {MoveUnused, MoveUnused},
					},
				},
			},
		},
	}

	block := NewCheckerPlayBlock(cpa)
	if block.BlockType != BlockTypeCheckerPlay {
		t.Errorf("BlockType = %d, want %d", block.BlockType, BlockTypeCheckerPlay)
	}

	cpa2, err := UnmarshalCheckerPlayAnalysis(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if cpa2.MoveCount != cpa.MoveCount {
		t.Errorf("MoveCount = %d, want %d", cpa2.MoveCount, cpa.MoveCount)
	}

	for i := 0; i < int(cpa.MoveCount); i++ {
		if cpa2.Moves[i].Equity != cpa.Moves[i].Equity {
			t.Errorf("Move[%d].Equity = %d, want %d", i, cpa2.Moves[i].Equity, cpa.Moves[i].Equity)
		}
		if cpa2.Moves[i].WinRate != cpa.Moves[i].WinRate {
			t.Errorf("Move[%d].WinRate = %d, want %d", i, cpa2.Moves[i].WinRate, cpa.Moves[i].WinRate)
		}
		if cpa2.Moves[i].Move.Submoves != cpa.Moves[i].Move.Submoves {
			t.Errorf("Move[%d].Submoves mismatch", i)
		}
	}
}

func TestCubeDecisionAnalysisRoundTrip(t *testing.T) {
	cda := &CubeDecisionAnalysis{
		WinRate:           6800,
		GammonRate:        1500,
		BackgammonRate:    100,
		OppWinRate:        3200,
		OppGammonRate:     500,
		OppBackgammonRate: 20,
		CubelessNoDouble:  5000,
		CubelessDouble:    6000,
		CubefulNoDouble:   4500,
		CubefulDoubleTake: 5500,
		CubefulDoublePass: 10000,
		BestAction:        CubeActionDoubleTake,
	}

	block := NewCubeDecisionBlock(cda)
	cda2, err := UnmarshalCubeDecisionAnalysis(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if cda2.WinRate != cda.WinRate {
		t.Errorf("WinRate = %d, want %d", cda2.WinRate, cda.WinRate)
	}
	if cda2.CubefulNoDouble != cda.CubefulNoDouble {
		t.Errorf("CubefulNoDouble = %d, want %d", cda2.CubefulNoDouble, cda.CubefulNoDouble)
	}
	if cda2.BestAction != cda.BestAction {
		t.Errorf("BestAction = %d, want %d", cda2.BestAction, cda.BestAction)
	}
}

func TestEngineMetadataRoundTrip(t *testing.T) {
	em := &EngineMetadata{
		EngineName:    "eXtreme Gammon",
		EngineVersion: "2.19.1",
		METName:       "Kazaross-XG2",
		AnalysisType:  1,
	}

	block := NewEngineMetadataBlock(em)
	em2, err := UnmarshalEngineMetadata(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if em2.EngineName != em.EngineName {
		t.Errorf("EngineName = %q, want %q", em2.EngineName, em.EngineName)
	}
	if em2.EngineVersion != em.EngineVersion {
		t.Errorf("EngineVersion = %q, want %q", em2.EngineVersion, em.EngineVersion)
	}
	if em2.METName != em.METName {
		t.Errorf("METName = %q, want %q", em2.METName, em.METName)
	}
}

func TestRecordRoundTrip(t *testing.T) {
	pos := standardStartPosition()
	pos.MatchLength = 7

	base, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatal(err)
	}

	cpa := &CheckerPlayAnalysis{
		MoveCount: 1,
		Moves: []CheckerMoveAnalysis{{
			Equity:  10000,
			WinRate: 5000,
			Move: MoveEncoding{
				Submoves: [4][2]uint8{
					{23, 20},
					{MoveUnused, MoveUnused},
					{MoveUnused, MoveUnused},
					{MoveUnused, MoveUnused},
				},
			},
		}},
	}

	em := &EngineMetadata{
		EngineName:    "TestEngine",
		EngineVersion: "1.0",
		METName:       "TestMET",
	}

	rec := &Record{
		Base: *base,
		Blocks: []AnalysisBlock{
			NewCheckerPlayBlock(cpa),
			NewEngineMetadataBlock(em),
		},
	}

	data, err := MarshalRecord(rec)
	if err != nil {
		t.Fatal(err)
	}

	rec2, err := UnmarshalRecord(data)
	if err != nil {
		t.Fatal(err)
	}

	if rec2.Base.Zobrist != rec.Base.Zobrist {
		t.Error("Zobrist mismatch after round-trip")
	}
	if len(rec2.Blocks) != 2 {
		t.Fatalf("Blocks count = %d, want 2", len(rec2.Blocks))
	}
	if rec2.Blocks[0].BlockType != BlockTypeCheckerPlay {
		t.Errorf("Block[0].Type = %d, want %d", rec2.Blocks[0].BlockType, BlockTypeCheckerPlay)
	}
	if rec2.Blocks[1].BlockType != BlockTypeEngineMetadata {
		t.Errorf("Block[1].Type = %d, want %d", rec2.Blocks[1].BlockType, BlockTypeEngineMetadata)
	}
}

func TestWriteReadRecords(t *testing.T) {
	pos1 := standardStartPosition()
	base1, err := PositionToBaseRecord(pos1)
	if err != nil {
		t.Fatal(err)
	}

	pos2 := standardStartPosition()
	pos2.Board[5] = 4
	pos2.Board[4] = 1
	pos2.SideToMove = PlayerO
	pos2.CubeValue = 2
	pos2.CubeOwner = CubeX
	pos2.AwayX = 5
	base2, err := PositionToBaseRecord(pos2)
	if err != nil {
		t.Fatal(err)
	}

	records := []*Record{
		{Base: *base1},
		{Base: *base2},
	}

	var buf bytes.Buffer
	if err := WriteRecords(&buf, records); err != nil {
		t.Fatal(err)
	}

	// Verify we can read them back
	data := buf.Bytes()
	if len(data) != 2*BaseRecordSize {
		t.Errorf("data length = %d, want %d", len(data), 2*BaseRecordSize)
	}

	rec1, err := UnmarshalRecord(data[:BaseRecordSize])
	if err != nil {
		t.Fatal(err)
	}
	rec2, err := UnmarshalRecord(data[BaseRecordSize:])
	if err != nil {
		t.Fatal(err)
	}

	if rec1.Base.Zobrist == rec2.Base.Zobrist {
		t.Error("Different positions should have different hashes")
	}
}

func TestLayerBitboardSemantics(t *testing.T) {
	pos := &PositionState{
		SideToMove: PlayerX,
		CubeValue:  1,
		CubeOwner:  CubeCenter,
	}
	// Point 5: 1 checker (blot)
	// Point 7: 2 checkers (point)
	// Point 8: 3 checkers (spare)
	// Point 9: 5 checkers (spare with 4+ layers)
	pos.Board[5] = 1
	pos.Board[7] = 2
	pos.Board[8] = 3
	pos.Board[9] = 5
	// Need 15 total: 1+2+3+5 = 11, need 4 more
	pos.Board[12] = 4

	// Player O
	pos.Board[18] = -5
	pos.Board[16] = -3
	pos.Board[11] = -5
	pos.Board[0] = -2

	rec, err := PositionToBaseRecord(pos)
	if err != nil {
		t.Fatal(err)
	}

	// Test blot detection: Layer1=1 AND Layer2=0
	isBlot := (rec.LayersX[0]&(1<<5) != 0) && (rec.LayersX[1]&(1<<5) == 0)
	if !isBlot {
		t.Error("Point 5 should be a blot")
	}

	// Test point detection: Layer2=1
	isPoint := (rec.LayersX[1]&(1<<7) != 0)
	if !isPoint {
		t.Error("Point 7 should be a made point")
	}

	// Test spare detection: Layer3=1
	hasSpare := (rec.LayersX[2]&(1<<8) != 0)
	if !hasSpare {
		t.Error("Point 8 should have a spare checker")
	}

	// Layer4 for 5 checkers
	hasLayer4 := (rec.LayersX[3]&(1<<9) != 0)
	if !hasLayer4 {
		t.Error("Point 9 should have layer 4 set")
	}
}

func TestCubeLog2(t *testing.T) {
	tests := []struct {
		cubeValue int
		wantLog2  uint8
	}{
		{1, 0},
		{2, 1},
		{4, 2},
		{8, 3},
		{16, 4},
		{32, 5},
		{64, 6},
	}

	for _, tt := range tests {
		pos := standardStartPosition()
		pos.CubeValue = tt.cubeValue

		rec, err := PositionToBaseRecord(pos)
		if err != nil {
			t.Fatalf("CubeValue %d: %v", tt.cubeValue, err)
		}
		if rec.CubeLog2 != tt.wantLog2 {
			t.Errorf("CubeValue %d: CubeLog2 = %d, want %d", tt.cubeValue, rec.CubeLog2, tt.wantLog2)
		}

		// Verify decode
		pos2 := BaseRecordToPosition(rec)
		if pos2.CubeValue != tt.cubeValue {
			t.Errorf("CubeValue %d: decoded = %d", tt.cubeValue, pos2.CubeValue)
		}
	}
}

func TestIntegrityValidation(t *testing.T) {
	// Too many checkers for X
	pos := standardStartPosition()
	pos.Board[5] = 10 // 10 + 3 + 5 + 2 = 20 > 15

	_, err := PositionToBaseRecord(pos)
	if err == nil {
		t.Error("Expected error for too many checkers")
	}
}

func TestMatchMetadataRoundTrip(t *testing.T) {
	md := &MatchMetadata{
		Player1Name:   "Alice",
		Player2Name:   "Bob",
		MatchLength:   7,
		Event:         "World Championship",
		Location:      "Monte Carlo",
		Round:         "Final",
		Date:          "2024-07-15",
		Annotator:     "Expert",
		EngineName:    "eXtreme Gammon",
		EngineVersion: "2.19.211",
		METName:       "Kazaross-XG2",
	}

	block := NewMatchMetadataBlock(md)
	if block.BlockType != BlockTypeMatchMetadata {
		t.Errorf("BlockType = %d, want %d", block.BlockType, BlockTypeMatchMetadata)
	}

	md2, err := UnmarshalMatchMetadata(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if md2.Player1Name != md.Player1Name {
		t.Errorf("Player1Name = %q, want %q", md2.Player1Name, md.Player1Name)
	}
	if md2.Player2Name != md.Player2Name {
		t.Errorf("Player2Name = %q, want %q", md2.Player2Name, md.Player2Name)
	}
	if md2.MatchLength != md.MatchLength {
		t.Errorf("MatchLength = %d, want %d", md2.MatchLength, md.MatchLength)
	}
	if md2.Event != md.Event {
		t.Errorf("Event = %q, want %q", md2.Event, md.Event)
	}
	if md2.Location != md.Location {
		t.Errorf("Location = %q, want %q", md2.Location, md.Location)
	}
	if md2.Round != md.Round {
		t.Errorf("Round = %q, want %q", md2.Round, md.Round)
	}
	if md2.Date != md.Date {
		t.Errorf("Date = %q, want %q", md2.Date, md.Date)
	}
	if md2.EngineName != md.EngineName {
		t.Errorf("EngineName = %q, want %q", md2.EngineName, md.EngineName)
	}
	if md2.EngineVersion != md.EngineVersion {
		t.Errorf("EngineVersion = %q, want %q", md2.EngineVersion, md.EngineVersion)
	}
	if md2.METName != md.METName {
		t.Errorf("METName = %q, want %q", md2.METName, md.METName)
	}
}

func TestMatchMetadataEmptyFields(t *testing.T) {
	md := &MatchMetadata{
		Player1Name: "X",
		Player2Name: "O",
	}

	block := NewMatchMetadataBlock(md)
	md2, err := UnmarshalMatchMetadata(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if md2.Player1Name != "X" {
		t.Errorf("Player1Name = %q, want %q", md2.Player1Name, "X")
	}
	if md2.MatchLength != 0 {
		t.Errorf("MatchLength = %d, want 0", md2.MatchLength)
	}
	if md2.Event != "" {
		t.Errorf("Event = %q, want empty", md2.Event)
	}
}

func TestGameBoundaryRoundTrip(t *testing.T) {
	gb := &GameBoundary{
		GameNumber: 3,
		ScoreX:     5,
		ScoreO:     2,
		Winner:     0,
		PointsWon:  2,
		Crawford:   1,
		MoveCount:  42,
	}

	block := NewGameBoundaryBlock(gb)
	if block.BlockType != BlockTypeGameBoundary {
		t.Errorf("BlockType = %d, want %d", block.BlockType, BlockTypeGameBoundary)
	}

	gb2, err := UnmarshalGameBoundary(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if gb2.GameNumber != gb.GameNumber {
		t.Errorf("GameNumber = %d, want %d", gb2.GameNumber, gb.GameNumber)
	}
	if gb2.ScoreX != gb.ScoreX {
		t.Errorf("ScoreX = %d, want %d", gb2.ScoreX, gb.ScoreX)
	}
	if gb2.ScoreO != gb.ScoreO {
		t.Errorf("ScoreO = %d, want %d", gb2.ScoreO, gb.ScoreO)
	}
	if gb2.Winner != gb.Winner {
		t.Errorf("Winner = %d, want %d", gb2.Winner, gb.Winner)
	}
	if gb2.PointsWon != gb.PointsWon {
		t.Errorf("PointsWon = %d, want %d", gb2.PointsWon, gb.PointsWon)
	}
	if gb2.Crawford != gb.Crawford {
		t.Errorf("Crawford = %d, want %d", gb2.Crawford, gb.Crawford)
	}
	if gb2.MoveCount != gb.MoveCount {
		t.Errorf("MoveCount = %d, want %d", gb2.MoveCount, gb.MoveCount)
	}
}

func TestGameBoundaryUnfinished(t *testing.T) {
	gb := &GameBoundary{
		GameNumber: 1,
		Winner:     -1,
		PointsWon:  0,
	}

	block := NewGameBoundaryBlock(gb)
	gb2, err := UnmarshalGameBoundary(block.Payload)
	if err != nil {
		t.Fatal(err)
	}

	if gb2.Winner != -1 {
		t.Errorf("Winner = %d, want -1", gb2.Winner)
	}
	if gb2.PointsWon != 0 {
		t.Errorf("PointsWon = %d, want 0", gb2.PointsWon)
	}
}

func TestWriteReadGBFMatch(t *testing.T) {
	// Build a match with 2 games, each with 2 moves
	match := &Match{
		Metadata: MatchMetadata{
			Player1Name:   "Alice",
			Player2Name:   "Bob",
			MatchLength:   5,
			EngineName:    "TestEngine",
			EngineVersion: "1.0",
			METName:       "TestMET",
		},
		Games: []Game{
			{
				GameNumber:   1,
				InitialScore: [2]int{0, 0},
				Winner:       0,
				PointsWon:    1,
				Crawford:     false,
				Moves: []Move{
					makeTestMove(PlayerX, [2]int{3, 1}),
					makeTestMove(PlayerO, [2]int{6, 4}),
				},
			},
			{
				GameNumber:   2,
				InitialScore: [2]int{1, 0},
				Winner:       1,
				PointsWon:    2,
				Crawford:     false,
				Moves: []Move{
					makeTestMove(PlayerX, [2]int{5, 5}),
					makeTestMove(PlayerO, [2]int{2, 1}),
				},
			},
		},
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	// Verify metadata
	if match2.Metadata.Player1Name != "Alice" {
		t.Errorf("Player1Name = %q, want %q", match2.Metadata.Player1Name, "Alice")
	}
	if match2.Metadata.Player2Name != "Bob" {
		t.Errorf("Player2Name = %q, want %q", match2.Metadata.Player2Name, "Bob")
	}
	if match2.Metadata.MatchLength != 5 {
		t.Errorf("MatchLength = %d, want 5", match2.Metadata.MatchLength)
	}
	if match2.Metadata.EngineName != "TestEngine" {
		t.Errorf("EngineName = %q, want %q", match2.Metadata.EngineName, "TestEngine")
	}

	// Verify game count
	if len(match2.Games) != 2 {
		t.Fatalf("Games count = %d, want 2", len(match2.Games))
	}

	// Verify game 1
	g1 := match2.Games[0]
	if g1.GameNumber != 1 {
		t.Errorf("Game[0].GameNumber = %d, want 1", g1.GameNumber)
	}
	if g1.InitialScore[0] != 0 || g1.InitialScore[1] != 0 {
		t.Errorf("Game[0].InitialScore = %v, want [0 0]", g1.InitialScore)
	}
	if g1.Winner != 0 {
		t.Errorf("Game[0].Winner = %d, want 0", g1.Winner)
	}
	if g1.PointsWon != 1 {
		t.Errorf("Game[0].PointsWon = %d, want 1", g1.PointsWon)
	}
	if len(g1.Moves) != 2 {
		t.Errorf("Game[0].Moves count = %d, want 2", len(g1.Moves))
	}

	// Verify game 2
	g2 := match2.Games[1]
	if g2.GameNumber != 2 {
		t.Errorf("Game[1].GameNumber = %d, want 2", g2.GameNumber)
	}
	if g2.InitialScore[0] != 1 || g2.InitialScore[1] != 0 {
		t.Errorf("Game[1].InitialScore = %v, want [1 0]", g2.InitialScore)
	}
	if g2.Winner != 1 {
		t.Errorf("Game[1].Winner = %d, want 1", g2.Winner)
	}
	if g2.PointsWon != 2 {
		t.Errorf("Game[1].PointsWon = %d, want 2", g2.PointsWon)
	}
	if g2.Crawford != false {
		t.Errorf("Game[1].Crawford = %v, want false", g2.Crawford)
	}
	if len(g2.Moves) != 2 {
		t.Errorf("Game[1].Moves count = %d, want 2", len(g2.Moves))
	}
}

func TestWriteReadGBFWithAnalysis(t *testing.T) {
	cpa := &CheckerPlayAnalysis{
		MoveCount: 2,
		Moves: []CheckerMoveAnalysis{
			{
				Equity:     15000,
				WinRate:    7200,
				GammonRate: 1000,
				EquityDiff: 0,
				PlyDepth:   3,
				Move: MoveEncoding{
					Submoves: [4][2]uint8{
						{23, 20}, {23, 18},
						{MoveUnused, MoveUnused}, {MoveUnused, MoveUnused},
					},
				},
			},
			{
				Equity:     14200,
				WinRate:    7000,
				GammonRate: 900,
				EquityDiff: -800,
				PlyDepth:   3,
				Move: MoveEncoding{
					Submoves: [4][2]uint8{
						{12, 9}, {12, 7},
						{MoveUnused, MoveUnused}, {MoveUnused, MoveUnused},
					},
				},
			},
		},
	}

	cda := &CubeDecisionAnalysis{
		WinRate:           6800,
		GammonRate:        1500,
		CubelessNoDouble:  5000,
		CubelessDouble:    6000,
		CubefulNoDouble:   4500,
		CubefulDoubleTake: 5500,
		CubefulDoublePass: 10000,
		BestAction:        CubeActionDoubleTake,
	}

	match := &Match{
		Metadata: MatchMetadata{
			Player1Name:   "X",
			Player2Name:   "O",
			MatchLength:   7,
			EngineName:    "XG",
			EngineVersion: "2.19",
		},
		Games: []Game{
			{
				GameNumber:   1,
				InitialScore: [2]int{0, 0},
				Winner:       0,
				PointsWon:    1,
				Moves: []Move{
					{
						MoveType:        MoveTypeChecker,
						Player:          PlayerX,
						Dice:            [2]int{3, 5},
						Position:        standardStartPosition(),
						CheckerAnalysis: cpa,
					},
					{
						MoveType:     MoveTypeCube,
						Player:       PlayerO,
						Position:     standardStartPosition(),
						CubeAnalysis: cda,
					},
				},
			},
		},
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	if len(match2.Games) != 1 {
		t.Fatalf("Games count = %d, want 1", len(match2.Games))
	}
	if len(match2.Games[0].Moves) != 2 {
		t.Fatalf("Moves count = %d, want 2", len(match2.Games[0].Moves))
	}

	// Verify checker play analysis
	mv1 := match2.Games[0].Moves[0]
	if mv1.CheckerAnalysis == nil {
		t.Fatal("Move[0] missing CheckerAnalysis")
	}
	if mv1.CheckerAnalysis.MoveCount != 2 {
		t.Errorf("CheckerAnalysis.MoveCount = %d, want 2", mv1.CheckerAnalysis.MoveCount)
	}
	if mv1.CheckerAnalysis.Moves[0].Equity != 15000 {
		t.Errorf("CheckerAnalysis.Moves[0].Equity = %d, want 15000", mv1.CheckerAnalysis.Moves[0].Equity)
	}
	if mv1.CheckerAnalysis.Moves[0].Move.Submoves[0] != [2]uint8{23, 20} {
		t.Errorf("CheckerAnalysis.Moves[0].Submoves[0] = %v, want [23 20]", mv1.CheckerAnalysis.Moves[0].Move.Submoves[0])
	}
	if mv1.CheckerAnalysis.Moves[1].EquityDiff != -800 {
		t.Errorf("CheckerAnalysis.Moves[1].EquityDiff = %d, want -800", mv1.CheckerAnalysis.Moves[1].EquityDiff)
	}

	// Verify cube decision analysis
	mv2 := match2.Games[0].Moves[1]
	if mv2.CubeAnalysis == nil {
		t.Fatal("Move[1] missing CubeAnalysis")
	}
	if mv2.CubeAnalysis.BestAction != CubeActionDoubleTake {
		t.Errorf("CubeAnalysis.BestAction = %d, want %d", mv2.CubeAnalysis.BestAction, CubeActionDoubleTake)
	}
	if mv2.CubeAnalysis.CubefulDoubleTake != 5500 {
		t.Errorf("CubeAnalysis.CubefulDoubleTake = %d, want 5500", mv2.CubeAnalysis.CubefulDoubleTake)
	}

	// Verify engine metadata is available on moves
	if mv1.EngineMetadata == nil {
		t.Fatal("Move[0] missing EngineMetadata")
	}
	if mv1.EngineMetadata.EngineName != "XG" {
		t.Errorf("EngineMetadata.EngineName = %q, want %q", mv1.EngineMetadata.EngineName, "XG")
	}
}

func TestWriteReadGBFSinglePosition(t *testing.T) {
	// Single position match (no analysis)
	pos := standardStartPosition()
	pos.MatchLength = 5

	match := &Match{
		Metadata: MatchMetadata{
			Player1Name: "P1",
			Player2Name: "P2",
			MatchLength: 5,
		},
		Games: []Game{
			{
				GameNumber: 1,
				Moves: []Move{
					{
						MoveType: MoveTypeChecker,
						Player:   PlayerX,
						Position: pos,
					},
				},
			},
		},
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	if match2.Metadata.Player1Name != "P1" {
		t.Errorf("Player1Name = %q, want %q", match2.Metadata.Player1Name, "P1")
	}
	if len(match2.Games) != 1 {
		t.Fatalf("Games count = %d, want 1", len(match2.Games))
	}
	if len(match2.Games[0].Moves) != 1 {
		t.Fatalf("Moves count = %d, want 1", len(match2.Games[0].Moves))
	}

	// Verify the position survived the round-trip
	mv := match2.Games[0].Moves[0]
	if mv.Position == nil {
		t.Fatal("Position is nil")
	}
	for i := 0; i < 24; i++ {
		if mv.Position.Board[i] != pos.Board[i] {
			t.Errorf("Board[%d] = %d, want %d", i, mv.Position.Board[i], pos.Board[i])
		}
	}
}

func TestWriteReadGBFCrawfordGame(t *testing.T) {
	match := &Match{
		Metadata: MatchMetadata{
			Player1Name: "X",
			Player2Name: "O",
			MatchLength: 5,
		},
		Games: []Game{
			{
				GameNumber:   3,
				InitialScore: [2]int{4, 2},
				Winner:       1,
				PointsWon:    2,
				Crawford:     true,
				Moves: []Move{
					makeTestMove(PlayerX, [2]int{3, 1}),
				},
			},
		},
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	if len(match2.Games) != 1 {
		t.Fatalf("Games count = %d, want 1", len(match2.Games))
	}
	g := match2.Games[0]
	if !g.Crawford {
		t.Error("Crawford = false, want true")
	}
	if g.InitialScore[0] != 4 || g.InitialScore[1] != 2 {
		t.Errorf("InitialScore = %v, want [4 2]", g.InitialScore)
	}
	if g.Winner != 1 {
		t.Errorf("Winner = %d, want 1", g.Winner)
	}
	if g.PointsWon != 2 {
		t.Errorf("PointsWon = %d, want 2", g.PointsWon)
	}
}

func TestWriteReadGBFMultipleGames(t *testing.T) {
	match := &Match{
		Metadata: MatchMetadata{
			Player1Name: "Alice",
			Player2Name: "Bob",
			MatchLength: 9,
		},
	}

	// Create 5 games with varying properties
	for i := 0; i < 5; i++ {
		winner := i % 2
		game := Game{
			GameNumber:   i + 1,
			InitialScore: [2]int{i, i / 2},
			Winner:       winner,
			PointsWon:    i%3 + 1,
			Crawford:     i == 3,
		}
		for j := 0; j < 3; j++ {
			game.Moves = append(game.Moves, makeTestMove(j%2, [2]int{j + 1, j + 2}))
		}
		match.Games = append(match.Games, game)
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	if len(match2.Games) != 5 {
		t.Fatalf("Games count = %d, want 5", len(match2.Games))
	}

	for i, g := range match2.Games {
		if g.GameNumber != i+1 {
			t.Errorf("Game[%d].GameNumber = %d, want %d", i, g.GameNumber, i+1)
		}
		if g.InitialScore[0] != i {
			t.Errorf("Game[%d].ScoreX = %d, want %d", i, g.InitialScore[0], i)
		}
		if g.Winner != i%2 {
			t.Errorf("Game[%d].Winner = %d, want %d", i, g.Winner, i%2)
		}
		if len(g.Moves) != 3 {
			t.Errorf("Game[%d].Moves count = %d, want 3", i, len(g.Moves))
		}
		if i == 3 && !g.Crawford {
			t.Errorf("Game[3].Crawford = false, want true")
		}
	}
}

func TestWriteReadGBFLegacyCompatibility(t *testing.T) {
	// Simulate a legacy flat format: just raw records without metadata/boundary headers
	pos1 := standardStartPosition()
	base1, err := PositionToBaseRecord(pos1)
	if err != nil {
		t.Fatal(err)
	}

	pos2 := standardStartPosition()
	pos2.Board[5] = 4
	pos2.Board[4] = 1
	pos2.SideToMove = PlayerO
	base2, err := PositionToBaseRecord(pos2)
	if err != nil {
		t.Fatal(err)
	}

	em := &EngineMetadata{
		EngineName:    "LegacyEngine",
		EngineVersion: "0.9",
		METName:       "OldMET",
	}

	records := []*Record{
		{Base: *base1, Blocks: []AnalysisBlock{NewEngineMetadataBlock(em)}},
		{Base: *base2},
	}

	var buf bytes.Buffer
	if err := WriteRecords(&buf, records); err != nil {
		t.Fatal(err)
	}

	match, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF (legacy): %v", err)
	}

	// Legacy format should put everything in game 1
	if len(match.Games) != 1 {
		t.Fatalf("Games count = %d, want 1 (legacy)", len(match.Games))
	}
	if len(match.Games[0].Moves) != 2 {
		t.Fatalf("Moves count = %d, want 2", len(match.Games[0].Moves))
	}

	// Legacy format should extract engine metadata
	if match.Metadata.EngineName != "LegacyEngine" {
		t.Errorf("EngineName = %q, want %q", match.Metadata.EngineName, "LegacyEngine")
	}
}

func TestWriteReadGBFFileRoundTrip(t *testing.T) {
	match := &Match{
		Metadata: MatchMetadata{
			Player1Name: "FileTest1",
			Player2Name: "FileTest2",
			MatchLength: 3,
		},
		Games: []Game{
			{
				GameNumber:   1,
				InitialScore: [2]int{0, 0},
				Winner:       0,
				PointsWon:    1,
				Moves: []Move{
					makeTestMove(PlayerX, [2]int{4, 2}),
				},
			},
		},
	}

	tmpFile := t.TempDir() + "/test.gbf"

	if err := WriteGBFFile(tmpFile, match); err != nil {
		t.Fatalf("WriteGBFFile: %v", err)
	}

	match2, err := ReadGBFFile(tmpFile)
	if err != nil {
		t.Fatalf("ReadGBFFile: %v", err)
	}

	if match2.Metadata.Player1Name != "FileTest1" {
		t.Errorf("Player1Name = %q, want %q", match2.Metadata.Player1Name, "FileTest1")
	}
	if len(match2.Games) != 1 {
		t.Fatalf("Games count = %d, want 1", len(match2.Games))
	}
	if match2.Games[0].Winner != 0 {
		t.Errorf("Winner = %d, want 0", match2.Games[0].Winner)
	}
}

func TestWriteReadGBFEmptyMatch(t *testing.T) {
	match := &Match{
		Metadata: MatchMetadata{
			Player1Name: "Empty1",
			Player2Name: "Empty2",
		},
	}

	var buf bytes.Buffer
	if err := WriteGBF(&buf, match); err != nil {
		t.Fatalf("WriteGBF: %v", err)
	}

	match2, err := ReadGBF(buf.Bytes())
	if err != nil {
		t.Fatalf("ReadGBF: %v", err)
	}

	if match2.Metadata.Player1Name != "Empty1" {
		t.Errorf("Player1Name = %q, want %q", match2.Metadata.Player1Name, "Empty1")
	}
	if len(match2.Games) != 0 {
		t.Errorf("Games count = %d, want 0", len(match2.Games))
	}
}

// makeTestMove creates a simple test Move with the standard opening position.
func makeTestMove(player int, dice [2]int) Move {
	pos := standardStartPosition()
	pos.SideToMove = player
	pos.Dice = dice
	return Move{
		MoveType: MoveTypeChecker,
		Player:   player,
		Dice:     dice,
		Position: pos,
	}
}
