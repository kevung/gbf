# Gammon Binary Format (GBF)

Version: 1.0-draft
Status: Draft Specification

> This specification supersedes `legacy/SPEC.md` (v0.3). The legacy file is
> retained for historical reference only.

## 1. Purpose

GBF is a deterministic, compact binary format for representing backgammon
positions, matches, and associated engine analysis. It is designed for:

- Large-scale storage (20M+ positions)
- Fast structural detection (blots, points, primes, spares)
- Deterministic hashing (both context-aware and board-only)
- Integer-only numeric precision (no floating-point)
- Multi-format import (eXtreme Gammon, GNU Backgammon, BGBlitz)

GBF records serve as the canonical serialization format. They are stored as
BLOBs inside a database (SQLite or PostgreSQL) with extracted columns for
indexing and querying. See ARCHITECTURE.md for the database layer.

## 2. Endianness

All multi-byte integers are **Little Endian**.

Signed integers use two's complement representation.

## 3. Point Indexing

Points are indexed 0 to 23.

- 0 = Player X 1-point (home side)
- 23 = Player X 24-point

All bitboards and point counts use this indexing.

## 4. Player Convention

- Player X = 0 (bottom player, moving from 24-point toward 1-point)
- Player O = 1 (top player, moving from 1-point toward 24-point)

Player X checkers are stored as positive values, Player O as negative.

## 5. Base Record Layout

Fixed size: **80 bytes** (66 payload + 14 padding).

| Offset | Size | Field              | Description                       |
|--------|------|--------------------|-----------------------------------|
| 0      | 16   | LayersX[0..3]      | 4 x uint32, Player X bitboards    |
| 16     | 16   | LayersO[0..3]      | 4 x uint32, Player O bitboards    |
| 32     | 12   | PointCounts[0..23] | Packed nibbles, 2 points per byte |
| 44     | 1    | BarX               | uint8, 0-15                       |
| 45     | 1    | BarO               | uint8, 0-15                       |
| 46     | 1    | BorneOffX          | uint8, 0-15                       |
| 47     | 1    | BorneOffO          | uint8, 0-15                       |
| 48     | 1    | SideToMove         | uint8, 0=X, 1=O                   |
| 49     | 1    | CubeLog2           | uint8, log2 of cube value         |
| 50     | 1    | CubeOwner          | uint8, 0=center, 1=X, 2=O        |
| 51     | 1    | AwayX              | uint8, points needed to win       |
| 52     | 1    | AwayO              | uint8                             |
| 53     | 2    | PipX               | uint16 LE                         |
| 55     | 2    | PipO               | uint16 LE                         |
| 57     | 8    | Zobrist            | uint64 LE, context-aware hash     |
| 65     | 1    | BlockCount         | uint8, analysis blocks following  |
| 66     | 14   | Padding            | Must be zero                      |

> Status: The 80-byte layout is inherited from v0.3 and will be re-evaluated
> after Phase 1 data exploration. Candidates for change: removing derived
> fields (PipX/O, Zobrist) from the record, reducing padding.

### 5.1 Checker Layer Bitboards

For each player, 4 layers are stored. Each layer is a uint32 with 24
significant bits (bit i = point i). Bits 24-31 must be zero.

- Layer 1: checker #1 presence
- Layer 2: checker #2 presence
- Layer 3: checker #3 presence
- Layer 4: checker #4 presence

Per player: 4 layers x 4 bytes = 16 bytes. Both players: **32 bytes**.

### 5.2 Exact Checker Counts

24 points x 4-bit unsigned integer (0-15), packed contiguously.
2 points per byte (low nibble = even point, high nibble = odd point).

**12 bytes** total.

### 5.3 Bar and Borne-Off

Per player: Bar (uint8, 0-15), BorneOff (uint8, 0-15).

**4 bytes** total for both players.

### 5.4 Cube State

- CubeLog2: uint8, log2 of the cube value (0=1, 1=2, 2=4, ..., 6=64)
- CubeOwner: uint8 (0=centered, 1=X, 2=O)

**2 bytes**.

### 5.5 Away Scores

AwayX and AwayO: uint8 each. Match length is NOT stored in the base record
(it belongs in the MatchMetadata block).

**2 bytes**.

### 5.6 Pip Counts

Stored (not derived at query time). Per player: uint16 LE.
Maximum theoretical pip count: 15 x 25 = 375.

**4 bytes**.

### 5.7 Pip Count Formula

Player X: Sum(count(P) x (P + 1)) for X-occupied points + BarX x 25

Player O: Sum(count(P) x (24 - P)) for O-occupied points + BarO x 25

Stored pip counts must match the recomputed value.

## 6. Structural Semantics

The layer bitboards enable fast detection of:

| Pattern | Condition                                  |
|---------|--------------------------------------------|
| Blot    | Layer1 = 1 AND Layer2 = 0                  |
| Point   | Layer2 = 1 (2+ checkers)                   |
| Spare   | Layer3 = 1 OR Layer4 = 1 (3+ checkers)     |
| Prime   | 5+ consecutive points with Layer2 = 1      |

Layers must agree with counts: for each point P, for N in 1..4,
LayerN(P) = 1 iff count(P) >= N.

## 7. Zobrist Hashing

### 7.1 Context-Aware Zobrist (existing)

A deterministic uint64 hash computed via XOR of pre-computed keys.
Fixed PRNG seed: `0x12345678DEADBEEF` (xorshift64).

**Includes**: all checker layers, exact counts, bar, borne-off,
side to move, cube state (CubeLog2, CubeOwner), away scores.

**Excludes**: pip counts, analysis blocks, match metadata.

Two identical game states (same board + cube + score + side) always
produce the same hash, across platforms and compilers.

### 7.2 Board-Only Zobrist (new in v1.0)

A second uint64 hash that captures only the board configuration.

**Includes**: all checker layers, exact counts, bar, borne-off.

**Excludes**: side to move, cube state, away scores, pip counts,
analysis blocks, match metadata.

Purpose: identify the same board position regardless of match context.
Enables queries like "find all occurrences of this board layout across
all match scores and cube states."

Uses the same PRNG seed and key tables as the context-aware hash, but
omits the XOR contributions from side_to_move, cube, and away keys.

> Note: The board-only hash is NOT stored in the base record. It is
> computed during import and stored as a database column.

## 8. File Structure

### 8.1 Structured Match File

1. **Header record**: zeroed base record + MatchMetadata block (type=4)
2. **For each game**:
   a. Game boundary record: zeroed base + GameBoundary block (type=5)
   b. Move records: position data + optional analysis blocks

### 8.2 Legacy Flat File

A flat sequence of move records without header or game boundary records.
All records belong to a single game. Supported for backward compatibility.

## 9. Analysis Blocks

Each block starts with a **4-byte header**:

| Offset | Size | Field        |
|--------|------|--------------|
| 0      | 1    | block_type   |
| 1      | 1    | version      |
| 2      | 2    | block_length |

`block_length` = payload size only (excludes header).

### 9.1 Checker Play Analysis (type=1)

| Offset | Size | Field      |
|--------|------|------------|
| 0      | 1    | move_count |

Per candidate move (28 bytes):

| Offset | Size | Field              | Encoding           |
|--------|------|--------------------|--------------------|
| 0      | 4    | equity             | int32 LE, x10000   |
| 4      | 2    | win_rate           | uint16 LE, x10000  |
| 6      | 2    | gammon_rate        | uint16 LE, x10000  |
| 8      | 2    | backgammon_rate    | uint16 LE, x10000  |
| 10     | 2    | opp_win_rate       | uint16 LE, x10000  |
| 12     | 2    | opp_gammon_rate    | uint16 LE, x10000  |
| 14     | 2    | opp_backgammon_rate| uint16 LE, x10000  |
| 16     | 2    | equity_diff        | int16 LE, x10000   |
| 18     | 1    | ply_depth          |                    |
| 19     | 1    | reserved           |                    |
| 20     | 8    | move_encoding      | 4 x (from, to)    |

**Move encoding**: up to 4 sub-moves. from/to: 0-23 = board point,
24 = bar (from) or bear-off (to). Unused slots: from=to=255.

### 9.2 Cube Decision Analysis (type=2, 33 bytes)

| Offset | Size | Field                |
|--------|------|----------------------|
| 0      | 12   | Win/gammon/bg rates  |
| 12     | 4    | cubeless_no_double   |
| 16     | 4    | cubeless_double      |
| 20     | 4    | cubeful_no_double    |
| 24     | 4    | cubeful_double_take  |
| 28     | 4    | cubeful_double_pass  |
| 32     | 1    | best_action          |

best_action: 0=No Double, 1=Double/Take, 2=Double/Pass.

### 9.3 Engine Metadata (type=3, variable)

Length-prefixed strings (uint8 length + UTF-8 bytes, max 255):
engine_name, engine_version, met_name, then analysis_type (uint8).

### 9.4 Match Metadata (type=4, variable)

Length-prefixed strings: player1_name, player2_name, event, location,
round, date, annotator, engine_name, engine_version, met_name.
Ends with match_length (uint16 LE, 0 = money game).

### 9.5 Game Boundary (type=5, 11 bytes)

| Offset | Size | Field       |
|--------|------|-------------|
| 0      | 2    | game_number |
| 2      | 2    | score_x     |
| 4      | 2    | score_o     |
| 6      | 1    | winner      |
| 7      | 1    | points_won  |
| 8      | 1    | crawford    |
| 9      | 2    | move_count  |

winner: 0=PlayerX, 1=PlayerO, -1=unfinished.

## 10. Numeric Encoding

No floating-point values in the binary format.

**Percentages**: uint16, scale 10000 = 100%. Range: 0-10000.
Example: 43.45% -> 4345.

**Equity**: int32, scale 10000. Signed.
Example: +1.5233 -> 15233, -0.3940 -> -3940.

## 11. Integrity Rules

For each player:

1. Total checkers = sum(counts) + bar + borneOff = 15
2. Pip count matches recomputed value
3. Layer bitboards match exact counts
4. Context-aware Zobrist matches recomputed value

If any rule fails, the record is invalid.

## 12. Determinism Requirements

Two identical logical positions must produce:
- Identical binary encoding
- Identical context-aware Zobrist hash
- Identical board-only Zobrist hash
- Identical pip counts
- Identical layer bitboards

Across different machines, operating systems, and compilers.

## 13. Format Compatibility

GBF supports import from:

| Format    | Extensions | Source         |
|-----------|------------|----------------|
| XG        | .xg        | eXtreme Gammon |
| GnuBG SGF | .sgf       | GNU Backgammon |
| GnuBG MAT | .mat       | GNU Backgammon |
| BGBlitz   | .bgf       | BGBlitz        |
| BGBlitz   | .txt       | BGBlitz export |

All source formats are parsed into a unified `Match` structure, then
normalized before hashing.

## 14. Version History

- **v0.1**: Base record and analysis blocks
- **v0.2**: Engine metadata block, hash functions, file I/O
- **v0.3**: Match metadata (type=4) and game boundary (type=5) blocks.
  Structured match serialization preserving player names, match length,
  game scores, Crawford flag.
- **v1.0-draft** (this document):
  - Board-only Zobrist hash specification (section 7.2)
  - Explicit "re-evaluate after Phase 1" note on base record layout
  - Separated from database/feature concerns (see ARCHITECTURE.md)
  - Aligned with multi-backend storage architecture
