  Gammon Binary Format (GBF)
Version 0.3
Status: Draft Specification

# 1. Purpose

GBF is a deterministic, compact binary format for representing backgammon
positions, matches, and associated engine analysis. It is designed for
large-scale storage, fast structural detection (blots, points, primes,
spares), deterministic hashing, and integer-only numeric precision.

GBF serves as the canonical format for importing, storing, and exchanging
backgammon data. All source formats (eXtreme Gammon, GNU Backgammon,
BGBlitz) are parsed into GBF structures before storage or processing.

# 2. Endianness

All multi-byte integers are Little Endian.

Signed integers use two's complement representation.

# 3. File Structure

A GBF file consists of a sequence of **records**, each starting with an
80-byte base record optionally followed by analysis blocks.

## 3.1 Structured Match File

A structured GBF match file uses the following layout:

1. **Header record**: A zeroed base record with a single MatchMetadata
   block (block_type=4). Contains player names, match length, event,
   date, engine info, and other metadata.

2. **For each game**:
   a. **Game boundary record**: A zeroed base record with a single
      GameBoundary block (block_type=5). Contains game number, initial
      scores, winner, points won, Crawford flag, and move count.
   b. **Move records**: Standard records with position data in the base
      record and optional analysis blocks.

## 3.2 Legacy Flat File

For backward compatibility, a GBF file may also be a flat sequence of
move records without header or game boundary records. In this case, all
records are treated as belonging to a single game.

# 4. Base Record Overview

The GBF base record represents a single backgammon position without
analysis blocks.

The base record contains:
- Checker structure (bitboards + exact counts)
- Bar and borne-off
- Side to move
- Cube state
- Away scores
- Pip counts
- Zobrist hash

Fixed size: **80 bytes** (66 payload + 14 padding).

All padding bytes must be zero.

# 5. Point Indexing

Points are indexed from 0 to 23.

Index convention:
- 0 = Player X 1-point (home side)
- 23 = Player X 24-point

All bitboards use this indexing.

# 6. Player Convention

- PlayerX = 0 (bottom player, moving from 24-point toward 1-point)
- PlayerO = 1 (top player, moving from 1-point toward 24-point)

Player X checkers are stored as positive values, Player O as negative.

# 7. Checker Representation

GBF uses a hybrid representation:

- 4 bitboards per player (first 4 checker layers)
- Exact count per point
- Bar and borne-off counters

This enables fast detection of:
- Blots (Layer1=1 AND Layer2=0)
- Points (Layer2=1)
- Primes (5+ consecutive points with Layer2=1)
- Spare checkers (Layer3=1 OR Layer4=1)

## 7.1 Layer Bitboards

For each player, 4 layers are stored.

- Layer 1: checker #1 presence
- Layer 2: checker #2 presence
- Layer 3: checker #3 presence
- Layer 4: checker #4 presence

Each layer:
- 24 significant bits
- Stored inside uint32
- Bits 24-31 must be zero

Per player: 4 layers × 4 bytes = 16 bytes
Both players: **32 bytes total**

## 7.2 Exact Checker Counts

Each of the 24 points stores a 4-bit unsigned integer (0-15).

24 × 4 bits = 96 bits = **12 bytes** (packed contiguously, 2 points per byte)

## 7.3 Bar and Borne-Off

Per player:
- Bar: uint8 (0-15)
- BorneOff: uint8 (0-15)

Total for both players: **4 bytes**

# 8. Side to Move

uint8

- 0 = Player X
- 1 = Player O

**1 byte**

# 9. Cube State

Cube value:
- Stored as uint8 log2 value
- 0 → cube = 1, 1 → cube = 2, 2 → cube = 4, etc.

Cube owner:
- uint8
- 0 = centered, 1 = X, 2 = O

**2 bytes total**

# 10. Away Scores

Away X: uint8
Away O: uint8

Match length is NOT stored in the base record (stored in MatchMetadata block).

**2 bytes total**

# 11. Pip Counts

Stored (not derived at query time).

Per player: uint16
Maximum theoretical pip count: 15 × 25 = 375

**4 bytes total**

# 12. Zobrist Hash

uint64 deterministic hash.

The hash includes:
- All checker layers
- Exact counts
- Bar, BorneOff
- Side to move
- Cube state
- Away scores

The hash excludes:
- Pip counts
- Analysis blocks
- Match metadata

**8 bytes**

# 13. Base Record Layout

| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 | LayersX[0..3] (4 × uint32) |
| 16 | 16 | LayersO[0..3] (4 × uint32) |
| 32 | 12 | PointCounts[0..23] (packed nibbles) |
| 44 | 1 | BarX |
| 45 | 1 | BarO |
| 46 | 1 | BorneOffX |
| 47 | 1 | BorneOffO |
| 48 | 1 | SideToMove |
| 49 | 1 | CubeLog2 |
| 50 | 1 | CubeOwner |
| 51 | 1 | AwayX |
| 52 | 1 | AwayO |
| 53 | 2 | PipX (uint16 LE) |
| 55 | 2 | PipO (uint16 LE) |
| 57 | 8 | Zobrist (uint64 LE) |
| 65 | 1 | BlockCount (uint8) |
| 66 | 14 | Padding (zeros) |

**Total: 80 bytes**

The BlockCount field stores the number of analysis blocks that follow
this base record. This enables readers to parse exactly the right
number of blocks per record when multiple records are concatenated
in a file.

# 14. Numeric Encoding Rules

No floating-point values are allowed in the binary format.

All rates and equities are stored as scaled integers.

## 14.1 Percentages

Stored as uint16.

Scale: 10000 = 100%

Examples:
- 43.45% → 4345
- 100% → 10000

Valid range: 0 to 10000 inclusive.

## 14.2 Equity

Stored as int32.

Scale: 10000

Examples:
- +1.5233 → 15233
- -0.3940 → -3940

Signed values allowed.

# 15. Analysis Blocks

After the base record, optional analysis blocks may follow.

Each block begins with a **4-byte header**:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | block_type (uint8) |
| 1 | 1 | version (uint8) |
| 2 | 2 | block_length (uint16 LE) |

`block_length` specifies the size of the payload only (excludes header).

## 15.1 Checker Play Analysis Block (block_type = 1)

Payload structure:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | move_count (uint8) |

For each move (28 bytes per move):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | equity (int32 LE, ×10000) |
| 4 | 2 | win_rate (uint16 LE, ×10000) |
| 6 | 2 | gammon_rate (uint16 LE) |
| 8 | 2 | backgammon_rate (uint16 LE) |
| 10 | 2 | opp_win_rate (uint16 LE) |
| 12 | 2 | opp_gammon_rate (uint16 LE) |
| 14 | 2 | opp_backgammon_rate (uint16 LE) |
| 16 | 2 | equity_diff (int16 LE, ×10000) |
| 18 | 1 | ply_depth (uint8) |
| 19 | 1 | reserved (uint8) |
| 20 | 8 | move_encoding (4 × 2 bytes) |

### Move Encoding

Up to 4 checker sub-moves. Each sub-move is a (from, to) pair:
- from_point: 0-23 = board point, 24 = bar
- to_point: 0-23 = board point, 24 = bear off
- Unused slots: from=to=255

Fixed size: **8 bytes** (4 sub-moves × 2 bytes each).

## 15.2 Cube Decision Analysis Block (block_type = 2)

Payload structure (33 bytes):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 2 | win_rate (uint16 LE) |
| 2 | 2 | gammon_rate |
| 4 | 2 | backgammon_rate |
| 6 | 2 | opp_win_rate |
| 8 | 2 | opp_gammon_rate |
| 10 | 2 | opp_backgammon_rate |
| 12 | 4 | cubeless_no_double (int32 LE) |
| 16 | 4 | cubeless_double |
| 20 | 4 | cubeful_no_double |
| 24 | 4 | cubeful_double_take |
| 28 | 4 | cubeful_double_pass |
| 32 | 1 | best_action |

best_action values:
- 0 = No Double
- 1 = Double/Take
- 2 = Double/Pass

## 15.3 Engine Metadata Block (block_type = 3)

Variable-length payload. All strings are length-prefixed (uint8 length
followed by UTF-8 bytes, max 255 bytes per string).

| Field | Encoding |
|-------|----------|
| engine_name | length-prefixed string |
| engine_version | length-prefixed string |
| met_name | length-prefixed string |
| analysis_type | uint8 |

## 15.4 Match Metadata Block (block_type = 4)

Variable-length payload. All strings are length-prefixed (uint8 length
followed by UTF-8 bytes). The block ends with a uint16 match_length.

| Field | Encoding |
|-------|----------|
| player1_name | length-prefixed string |
| player2_name | length-prefixed string |
| event | length-prefixed string |
| location | length-prefixed string |
| round | length-prefixed string |
| date | length-prefixed string |
| annotator | length-prefixed string |
| engine_name | length-prefixed string |
| engine_version | length-prefixed string |
| met_name | length-prefixed string |
| match_length | uint16 LE (0 = money game) |

This block appears once per file, in the first record (header record).

## 15.5 Game Boundary Block (block_type = 5)

Fixed-length payload (11 bytes):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 2 | game_number (uint16 LE) |
| 2 | 2 | score_x (uint16 LE, points won at start) |
| 4 | 2 | score_o (uint16 LE) |
| 6 | 1 | winner (int8: 0=PlayerX, 1=PlayerO, -1=unfinished) |
| 7 | 1 | points_won (uint8) |
| 8 | 1 | crawford (uint8: 1=Crawford game) |
| 9 | 2 | move_count (uint16 LE) |

This block marks the start of a new game within a match. It appears in
a record with a zeroed base record, before the game's move records.

# 16. Structural Semantics

Blot: Layer1 = 1 AND Layer2 = 0

Point: Layer2 = 1

Spare: Layer3 = 1 OR Layer4 = 1

Prime: Five or more consecutive points with Layer2 = 1

Exact counts must agree with layers:
- For each point P, for N in 1..4:
  - If count(P) ≥ N then LayerN(P) = 1
  - If count(P) < N then LayerN(P) = 0

# 17. Pip Count Formula

For Player X:
  Pip = Σ (count(P) × (P + 1)) for all points P with X checkers
      + BarX × 25

For Player O:
  Pip = Σ (count(P) × (24 - P)) for all points P with O checkers
      + BarO × 25

Stored pip count must match recomputed value.

# 18. Integrity Rules

For each player:
1. Total checkers = Σ counts + bar + borneOff = 15
2. Pip count must match recomputed value
3. Layer bitboards must match counts
4. Zobrist must match recomputed value

If any rule fails, the record is invalid.

# 19. Format Compatibility

GBF supports reversible conversion from:
- eXtreme Gammon (.xg) binary files
- GNU Backgammon (.sgf, .mat) files
- BGBlitz (.bgf) binary files and (.txt) text exports

All source formats are parsed into the GBF `Match` structure. Imported
positions are normalized before hashing.

# 20. Determinism Requirements

Two identical logical positions must produce:
- Identical binary encoding
- Identical Zobrist hash
- Identical pip counts
- Identical layer bitboards

Across different machines, operating systems, and compilers.

# 21. Serialization/Deserialization Flow

## 21.1 Writing a GBF File

1. Create a `Match` with `MatchMetadata` and `Game` list
2. Call `WriteGBF(writer, match)`:
   a. Marshal and write header record with MatchMetadata block
   b. For each Game:
      - Marshal and write game boundary record with GameBoundary block
      - For each Move with a Position:
        - Convert PositionState → BaseRecord (validate, compute Zobrist)
        - Attach analysis blocks (checker play, cube decision, engine metadata)
        - Marshal and write the record

## 21.2 Reading a GBF File

1. Call `ReadGBF(data)`:
   a. Read records sequentially
   b. If a record contains a MatchMetadata block: extract match metadata
   c. If a record contains a GameBoundary block: start a new Game
   d. Otherwise: convert to Move and append to current Game
   e. If no metadata/boundary blocks found: treat as legacy flat format

## 21.3 Source Format Import

1. `ParseFile(filename)` auto-detects format from extension
2. Dispatches to format-specific parser (XG, SGF, MAT, BGF, TXT)
3. Returns a unified `Match` structure with normalized positions
4. The `Match` can then be:
   - Written to a GBF file via `WriteGBF`
   - Stored in a database
   - Processed for analysis display

# 22. Storage Estimate

Base record: 80 bytes aligned.
Typical move record with analysis: ~200-400 bytes.

10 million positions → ~2-4 GB
100 million → ~20-40 GB
1 billion → ~200-400 GB

# 23. Version History

- v0.1: Initial draft with base record and analysis blocks
- v0.2: Added engine metadata block, hash functions, file I/O
- v0.3: Added match metadata block (type=4) and game boundary block
  (type=5) for structured match serialization. Updated file layout to
  preserve match structure (player names, match length, game scores,
  Crawford flag) through the GBF binary format.
