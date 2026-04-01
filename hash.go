package gbf

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
)

// maxCanonicalDicePerGame is the number of dice rolls per game used for
// canonical hash computation. 10 dice × 21 possible outcomes × 7+ games
// gives astronomically low collision probability.
const maxCanonicalDicePerGame = 10

// ComputeMatchHash computes a SHA256 hash of the full match transcription
// for duplicate detection within the same format. The hash includes metadata,
// game results, and all move details.
func ComputeMatchHash(m *Match) string {
	var b strings.Builder

	p1 := strings.TrimSpace(strings.ToLower(m.Metadata.Player1Name))
	p2 := strings.TrimSpace(strings.ToLower(m.Metadata.Player2Name))
	b.WriteString(fmt.Sprintf("meta:%s|%s|%d|", p1, p2, m.Metadata.MatchLength))

	for gi, game := range m.Games {
		b.WriteString(fmt.Sprintf("g%d:%d,%d,%d,%d|",
			gi, game.InitialScore[0], game.InitialScore[1], game.Winner, game.PointsWon))

		for mi, move := range game.Moves {
			b.WriteString(fmt.Sprintf("m%d:%s,", mi, move.MoveType))

			if move.MoveType == MoveTypeChecker {
				b.WriteString(fmt.Sprintf("d%d%d,p%s|",
					move.Dice[0], move.Dice[1], move.MoveString))
			}

			if move.MoveType == MoveTypeCube || move.MoveType == MoveTypeTake ||
				move.MoveType == MoveTypePass {
				b.WriteString(fmt.Sprintf("c%s|", move.CubeAction))
			}
		}
	}

	hash := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(hash[:])
}

// ComputeCanonicalMatchHash computes a format-independent match hash.
// This hash uses only the first N dice per game (physical events that are
// identical across all export formats) plus normalized player names, match
// length, and game count, making it identical whether the match was imported
// from XG, GnuBG (SGF/MAT), or BGBlitz (BGF) format.
func ComputeCanonicalMatchHash(m *Match) string {
	var b strings.Builder

	// Normalize and sort player names for consistency
	p1 := strings.TrimSpace(strings.ToLower(m.Metadata.Player1Name))
	p2 := strings.TrimSpace(strings.ToLower(m.Metadata.Player2Name))
	if p1 > p2 {
		p1, p2 = p2, p1
	}
	b.WriteString(fmt.Sprintf("canonical2:%s|%s|%d|%d|",
		p1, p2, m.Metadata.MatchLength, len(m.Games)))

	for gi, game := range m.Games {
		b.WriteString(fmt.Sprintf("g%d|", gi))
		diceCount := 0
		for _, move := range game.Moves {
			if diceCount >= maxCanonicalDicePerGame {
				break
			}
			if move.MoveType == MoveTypeChecker && move.Dice[0] > 0 {
				d1, d2 := move.Dice[0], move.Dice[1]
				if d1 > d2 {
					d1, d2 = d2, d1
				}
				b.WriteString(fmt.Sprintf("d%d%d|", d1, d2))
				diceCount++
			}
		}
	}

	hash := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(hash[:])
}
