package gbf

import (
	"context"
	"database/sql"
	"fmt"
)

// MigrateResult summarises a completed MigrateStore run.
type MigrateResult struct {
	Positions int
	Matches   int
	Games     int
	Moves     int
	Analyses  int
}

// MigrateStore copies all data from a SQLite database (src) into any Store
// (dst). It uses batched transactions when dst implements Batcher.
//
// Row counts on src and dst should match after migration:
//
//	SELECT COUNT(*) FROM positions  -- must be equal
//	SELECT COUNT(*) FROM matches    -- must be equal
//	SELECT COUNT(*) FROM games      -- must be equal
//	SELECT COUNT(*) FROM moves      -- must be equal
func MigrateStore(ctx context.Context, src *sql.DB, dst Store, batchSize int) (MigrateResult, error) {
	if batchSize <= 0 {
		batchSize = 1000
	}

	var res MigrateResult
	batcher, hasBatch := dst.(Batcher)

	// ── Positions ─────────────────────────────────────────────────────────────
	// posIDMap maps old (src) position id → new (dst) position id.
	posIDMap := make(map[int64]int64)

	rows, err := src.QueryContext(ctx,
		`SELECT id, base_record, board_hash FROM positions ORDER BY id`)
	if err != nil {
		return res, fmt.Errorf("query positions: %w", err)
	}
	defer rows.Close()

	type srcPos struct {
		id        int64
		blob      []byte
		boardHash int64
	}
	var buf []srcPos

	flush := func() error {
		if len(buf) == 0 {
			return nil
		}
		if hasBatch {
			if err := batcher.BeginBatch(ctx); err != nil {
				return err
			}
		}
		for _, sp := range buf {
			rec, err := UnmarshalBaseRecord(sp.blob)
			if err != nil {
				if hasBatch {
					batcher.RollbackBatch()
				}
				return fmt.Errorf("unmarshal pos id=%d: %w", sp.id, err)
			}
			newID, err := dst.UpsertPosition(ctx, *rec, uint64(sp.boardHash))
			if err != nil {
				if hasBatch {
					batcher.RollbackBatch()
				}
				return fmt.Errorf("upsert pos id=%d: %w", sp.id, err)
			}
			posIDMap[sp.id] = newID
			res.Positions++
		}
		buf = buf[:0]
		if hasBatch {
			return batcher.CommitBatch()
		}
		return nil
	}

	for rows.Next() {
		var sp srcPos
		if err := rows.Scan(&sp.id, &sp.blob, &sp.boardHash); err != nil {
			return res, fmt.Errorf("scan pos: %w", err)
		}
		buf = append(buf, sp)
		if len(buf) >= batchSize {
			if err := flush(); err != nil {
				return res, err
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return res, err
	}
	if err := flush(); err != nil {
		return res, err
	}

	// ── Analyses ──────────────────────────────────────────────────────────────
	arows, err := src.QueryContext(ctx,
		`SELECT position_id, block_type, COALESCE(engine_name,''), payload
		 FROM analyses ORDER BY position_id, block_type`)
	if err != nil {
		return res, fmt.Errorf("query analyses: %w", err)
	}
	defer arows.Close()

	for arows.Next() {
		var srcPosID int64
		var blockType uint8
		var engineName string
		var payload []byte
		if err := arows.Scan(&srcPosID, &blockType, &engineName, &payload); err != nil {
			return res, fmt.Errorf("scan analysis: %w", err)
		}
		dstPosID, ok := posIDMap[srcPosID]
		if !ok {
			continue // position was skipped (already existed in dst)
		}
		if err := dst.AddAnalysis(ctx, dstPosID, blockType, engineName, payload); err != nil {
			return res, fmt.Errorf("add analysis for pos %d: %w", dstPosID, err)
		}
		res.Analyses++
	}
	arows.Close()

	// ── Matches → Games → Moves ───────────────────────────────────────────────
	mrows, err := src.QueryContext(ctx, `
		SELECT id, match_hash, canonical_hash,
		       COALESCE(source_format,''), COALESCE(player1,''), COALESCE(player2,''),
		       COALESCE(match_length,0)
		FROM matches ORDER BY id`)
	if err != nil {
		return res, fmt.Errorf("query matches: %w", err)
	}
	defer mrows.Close()

	for mrows.Next() {
		var srcMatchID int64
		var m Match
		var matchHash, canonHash, sourceFormat string
		if err := mrows.Scan(
			&srcMatchID, &matchHash, &canonHash,
			&sourceFormat,
			&m.Metadata.Player1Name, &m.Metadata.Player2Name,
			&m.Metadata.MatchLength,
		); err != nil {
			return res, fmt.Errorf("scan match: %w", err)
		}
		_ = sourceFormat // source_format not in MatchMetadata

		dstMatchID, err := dst.UpsertMatch(ctx, m, matchHash, canonHash)
		if err != nil {
			return res, fmt.Errorf("upsert match: %w", err)
		}
		res.Matches++

		// Games for this match.
		grows, err := src.QueryContext(ctx,
			`SELECT id, game_number, score_x, score_o, winner, points_won, crawford
			 FROM games WHERE match_id = ? ORDER BY game_number`,
			srcMatchID)
		if err != nil {
			return res, fmt.Errorf("query games for match %d: %w", srcMatchID, err)
		}
		for grows.Next() {
			var srcGameID int64
			var g Game
			if err := grows.Scan(
				&srcGameID, &g.GameNumber,
				&g.InitialScore[0], &g.InitialScore[1],
				&g.Winner, &g.PointsWon, &g.Crawford,
			); err != nil {
				grows.Close()
				return res, fmt.Errorf("scan game: %w", err)
			}
			dstGameID, err := dst.InsertGame(ctx, dstMatchID, g)
			if err != nil {
				grows.Close()
				return res, fmt.Errorf("insert game: %w", err)
			}
			res.Games++

			// Moves for this game.
			mvrows, err := src.QueryContext(ctx,
				`SELECT move_number, position_id, player, move_type,
				        dice_1, dice_2, move_string,
				        equity_diff, best_equity, played_equity
				 FROM moves WHERE game_id = ? ORDER BY move_number`,
				srcGameID)
			if err != nil {
				grows.Close()
				return res, fmt.Errorf("query moves for game %d: %w", srcGameID, err)
			}
			for mvrows.Next() {
				var mv Move
				var moveNumber int
				var srcPosID sql.NullInt64
				var ed, be, pe sql.NullInt64
				if err := mvrows.Scan(
					&moveNumber, &srcPosID, &mv.Player, &mv.MoveType,
					&mv.Dice[0], &mv.Dice[1], &mv.MoveString,
					&ed, &be, &pe,
				); err != nil {
					mvrows.Close()
					grows.Close()
					return res, fmt.Errorf("scan move: %w", err)
				}
				if ed.Valid {
					mv.EquityDiff = int32(ed.Int64)
				}
				if be.Valid {
					mv.BestEquity = int32(be.Int64)
				}
				if pe.Valid {
					mv.PlayedEquity = int32(pe.Int64)
				}

				var dstPosID int64
				if srcPosID.Valid {
					dstPosID = posIDMap[srcPosID.Int64]
				}
				if err := dst.InsertMove(ctx, dstGameID, moveNumber, dstPosID, mv); err != nil {
					mvrows.Close()
					grows.Close()
					return res, fmt.Errorf("insert move: %w", err)
				}
				res.Moves++
			}
			mvrows.Close()
		}
		grows.Close()
	}

	return res, nil
}
