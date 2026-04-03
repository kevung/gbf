package gbf

import (
	"context"
	"database/sql"
	"fmt"
)

// BackfillResult summarises the outcome of a BackfillDerivedColumns run.
type BackfillResult struct {
	Total    int // rows inspected
	Updated  int // rows that had NULL derived columns and were updated
	Skipped  int // rows already populated
	Errors   int // rows that could not be processed
}

// BackfillDerivedColumns populates the four M9 derived columns
// (pos_class, pip_diff, prime_len_x, prime_len_o) for existing rows that
// still have NULL values (imported before the M9 schema change).
//
// Processing is done in batches of batchSize rows to bound memory usage.
// Pass 0 for batchSize to use the default (1000).
func BackfillDerivedColumns(ctx context.Context, db *sql.DB, batchSize int) (BackfillResult, error) {
	if batchSize <= 0 {
		batchSize = 1000
	}

	var res BackfillResult
	// Cursor-based pagination: always fetch from id > lastID to avoid the
	// "shifting result set" problem that occurs when using OFFSET on a column
	// that is being updated by the same loop.
	var lastID int64 = 0

	for {
		select {
		case <-ctx.Done():
			return res, ctx.Err()
		default:
		}

		rows, err := db.QueryContext(ctx,
			`SELECT id, base_record FROM positions
			 WHERE pos_class IS NULL AND id > ?
			 ORDER BY id
			 LIMIT ?`,
			lastID, batchSize,
		)
		if err != nil {
			return res, fmt.Errorf("query batch after id=%d: %w", lastID, err)
		}

		type pending struct {
			id         int64
			posClass   int
			pipDiff    int
			primeLenX  int
			primeLenO  int
		}
		var batch []pending

		for rows.Next() {
			var id int64
			var blob []byte
			if err := rows.Scan(&id, &blob); err != nil {
				rows.Close()
				return res, fmt.Errorf("scan: %w", err)
			}
			rec, err := UnmarshalBaseRecord(blob)
			if err != nil {
				res.Errors++
				continue
			}
			derived := ExtractDerivedFeatures(*rec)
			batch = append(batch, pending{
				id:        id,
				posClass:  int(derived[9]),
				pipDiff:   int(derived[8]),
				primeLenX: int(derived[4]),
				primeLenO: int(derived[5]),
			})
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return res, fmt.Errorf("rows error: %w", err)
		}

		if len(batch) == 0 {
			break
		}

		tx, err := db.BeginTx(ctx, nil)
		if err != nil {
			return res, fmt.Errorf("begin tx: %w", err)
		}

		stmt, err := tx.PrepareContext(ctx,
			`UPDATE positions
			 SET pos_class=?, pip_diff=?, prime_len_x=?, prime_len_o=?
			 WHERE id=?`)
		if err != nil {
			tx.Rollback()
			return res, fmt.Errorf("prepare: %w", err)
		}

		for _, p := range batch {
			if _, err := stmt.ExecContext(ctx,
				p.posClass, p.pipDiff, p.primeLenX, p.primeLenO, p.id,
			); err != nil {
				stmt.Close()
				tx.Rollback()
				return res, fmt.Errorf("update id=%d: %w", p.id, err)
			}
		}
		stmt.Close()

		if err := tx.Commit(); err != nil {
			return res, fmt.Errorf("commit: %w", err)
		}

		res.Updated += len(batch)
		res.Total   += len(batch)
		lastID = batch[len(batch)-1].id
	}

	// Count already-populated rows.
	var populated int
	if err := db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM positions WHERE pos_class IS NOT NULL`).Scan(&populated); err == nil {
		res.Skipped = populated - res.Updated
		if res.Skipped < 0 {
			res.Skipped = 0
		}
		res.Total += res.Skipped
	}

	return res, nil
}
