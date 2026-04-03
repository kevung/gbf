package gbf

import "strings"

// BuildFeatureQuery constructs a parameterized SQL query from a QueryFilter.
// Returns the SQL string and the corresponding argument slice.
// The query is safe against SQL injection: all filter values use ? placeholders;
// column names are hardcoded and never derived from user input.
func BuildFeatureQuery(f QueryFilter) (string, []any) {
	needsMovies := f.EquityDiffMin != nil

	limit := f.Limit
	if limit <= 0 {
		limit = 100
	}

	var sb strings.Builder
	var args []any

	if needsMovies {
		sb.WriteString(`
SELECT DISTINCT
    p.id, p.zobrist_hash, p.board_hash, p.base_record,
    p.pip_x, p.pip_o, p.away_x, p.away_o,
    p.cube_log2, p.cube_owner,
    p.bar_x, p.bar_o, p.borne_off_x, p.borne_off_o, p.side_to_move,
    COALESCE(p.pos_class,0), COALESCE(p.pip_diff,0),
    COALESCE(p.prime_len_x,0), COALESCE(p.prime_len_o,0)
FROM positions p
JOIN moves m ON m.position_id = p.id`)
	} else {
		sb.WriteString(`
SELECT
    id, zobrist_hash, board_hash, base_record,
    pip_x, pip_o, away_x, away_o,
    cube_log2, cube_owner,
    bar_x, bar_o, borne_off_x, borne_off_o, side_to_move,
    COALESCE(pos_class,0), COALESCE(pip_diff,0),
    COALESCE(prime_len_x,0), COALESCE(prime_len_o,0)
FROM positions`)
	}

	var conds []string
	pref := "" // column prefix: "" without join, "p." with join
	if needsMovies {
		pref = "p."
	}

	if f.PosClass != nil {
		conds = append(conds, pref+"pos_class = ?")
		args = append(args, *f.PosClass)
	}
	if f.AwayX != nil && *f.AwayX >= 0 {
		conds = append(conds, pref+"away_x = ?")
		args = append(args, *f.AwayX)
	}
	if f.AwayO != nil && *f.AwayO >= 0 {
		conds = append(conds, pref+"away_o = ?")
		args = append(args, *f.AwayO)
	}
	if f.PipDiffMin != nil {
		conds = append(conds, pref+"pip_diff >= ?")
		args = append(args, *f.PipDiffMin)
	}
	if f.PipDiffMax != nil {
		conds = append(conds, pref+"pip_diff <= ?")
		args = append(args, *f.PipDiffMax)
	}
	if f.PrimeLenXMin != nil {
		conds = append(conds, pref+"prime_len_x >= ?")
		args = append(args, *f.PrimeLenXMin)
	}
	if f.PrimeLenOMin != nil {
		conds = append(conds, pref+"prime_len_o >= ?")
		args = append(args, *f.PrimeLenOMin)
	}
	if f.CubeLog2 != nil {
		conds = append(conds, pref+"cube_log2 = ?")
		args = append(args, *f.CubeLog2)
	}
	if f.CubeOwner != nil {
		conds = append(conds, pref+"cube_owner = ?")
		args = append(args, *f.CubeOwner)
	}
	if f.BarXMin != nil {
		conds = append(conds, pref+"bar_x >= ?")
		args = append(args, *f.BarXMin)
	}
	if f.BarOMin != nil {
		conds = append(conds, pref+"bar_o >= ?")
		args = append(args, *f.BarOMin)
	}
	if needsMovies {
		conds = append(conds, "m.equity_diff >= ?")
		args = append(args, *f.EquityDiffMin)
	}

	if len(conds) > 0 {
		sb.WriteString(" WHERE ")
		sb.WriteString(strings.Join(conds, " AND "))
	}
	sb.WriteString(" LIMIT ?")
	args = append(args, limit)

	return sb.String(), args
}
