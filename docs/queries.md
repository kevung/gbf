# GBF — Standard Query Reference

All queries run on SQLite. PostgreSQL variants noted where the dialect differs.

Benchmark environment: AMD Ryzen 7 PRO 6850U, SQLite WAL, 1.57M positions.

---

## 1. Position Lookup

### 1.1 By context-aware Zobrist hash (exact match)

```sql
SELECT id, base_record, pip_x, pip_o, away_x, away_o, pos_class
FROM positions
WHERE zobrist_hash = ?;
```

- Index: `idx_positions_zobrist` (UNIQUE)
- Latency: **~21 µs** (p50), uses index seek
- Go API: `store.QueryByZobrist(ctx, hash)`

### 1.2 By board-only hash (all contexts for the same board)

```sql
SELECT id, base_record, away_x, away_o, cube_log2, cube_owner
FROM positions
WHERE board_hash = ?;
```

- Index: `idx_positions_board`
- Returns multiple rows when the same board appears at different scores/cube states

### 1.3 By multiple hashes (bulk lookup)

```sql
-- SQLite: use a VALUES list
SELECT p.id, p.zobrist_hash, p.base_record
FROM positions p
JOIN (VALUES (?), (?), (?)) AS h(z) ON p.zobrist_hash = h.z;
```

---

## 2. Error Analysis

### 2.1 Hardest positions (highest average equity loss)

```sql
SELECT p.id, p.pos_class, p.pip_diff,
       AVG(m.equity_diff) AS avg_loss,
       COUNT(*) AS occurrences
FROM positions p
JOIN moves m ON m.position_id = p.id
WHERE m.equity_diff > 0
GROUP BY p.id
ORDER BY avg_loss DESC
LIMIT 20;
```

- Uses `idx_moves_equity_diff`
- equity_diff is stored ×10000; divide by 10000 to get equity units

### 2.2 Contact positions with significant errors

```sql
SELECT p.id, p.pip_diff, p.prime_len_x, p.prime_len_o,
       m.equity_diff, m.move_string
FROM positions p
JOIN moves m ON m.position_id = p.id
WHERE p.pos_class = 0          -- contact
  AND m.equity_diff > 500      -- > 0.05 equity loss
ORDER BY m.equity_diff DESC
LIMIT 100;
```

- Uses `idx_positions_class` + `idx_moves_error` (partial index)
- Fastest path for difficulty analysis (M5 finding: contact is 10× harder)

### 2.3 Error distribution by position class

```sql
SELECT p.pos_class,
       COUNT(*) AS n,
       AVG(m.equity_diff) / 10000.0 AS avg_equity_loss,
       MAX(m.equity_diff) / 10000.0 AS max_equity_loss
FROM moves m
JOIN positions p ON p.id = m.position_id
WHERE m.equity_diff IS NOT NULL
GROUP BY p.pos_class
ORDER BY p.pos_class;
```

Expected results (BMAB 1.57M positions):
- contact (0): avg ~0.0040, max varies
- race (1):    avg ~0.0004
- bearoff (2): avg ~0.0001

---

## 3. Structural Pattern Queries

### 3.1 Prime positions (X has prime of length ≥ 5)

```sql
SELECT id, prime_len_x, prime_len_o, pip_diff, away_x, away_o
FROM positions
WHERE pos_class = 0        -- contact only
  AND prime_len_x >= 5
ORDER BY prime_len_x DESC
LIMIT 100;
```

### 3.2 Mutual prime positions

```sql
SELECT id, prime_len_x, prime_len_o, pip_diff
FROM positions
WHERE pos_class = 0
  AND prime_len_x >= 4
  AND prime_len_o >= 4
LIMIT 100;
```

### 3.3 Backgame indicators (X trailing by a lot in pip, contact)

```sql
SELECT p.id, p.pip_diff, p.prime_len_o, p.away_x, p.away_o
FROM positions p
WHERE p.pos_class = 0       -- contact
  AND p.pip_diff < -50      -- X significantly behind in pip
  AND p.prime_len_o >= 4    -- O has a prime
LIMIT 50;
```

---

## 4. Score-State Analysis

### 4.1 DMP (Double Match Point) positions

```sql
-- away_x = 1 AND away_o = 1
SELECT id, pos_class, pip_diff, prime_len_x, prime_len_o
FROM positions
WHERE away_x = 1 AND away_o = 1
ORDER BY pip_diff;
```

- Uses `idx_positions_class_away` (composite)

### 4.2 Contact positions at specific match score

```sql
SELECT id, pip_diff, prime_len_x, prime_len_o
FROM positions
WHERE pos_class = 0
  AND away_x = 2
  AND away_o = 3
LIMIT 200;
```

- Uses `idx_positions_class_away` — covers (pos_class, away_x, away_o) in one seek
- Latency: **~33 µs** for typical result sets

### 4.3 Positions across all scores for the same board

```sql
SELECT p.away_x, p.away_o, p.cube_log2, p.cube_owner, p.pip_x, p.pip_o
FROM positions p
WHERE p.board_hash = ?
ORDER BY p.away_x, p.away_o;
```

---

## 5. Player Analysis

### 5.1 All positions played by a specific player

```sql
SELECT DISTINCT mv.position_id, p.pos_class, p.pip_diff
FROM matches m
JOIN games g  ON g.match_id   = m.id
JOIN moves mv ON mv.game_id   = g.id
JOIN positions p ON p.id      = mv.position_id
WHERE (m.player1 = ? OR m.player2 = ?)
ORDER BY p.pos_class, p.pip_diff;
```

- Uses `idx_matches_player1` / `idx_matches_player2`

### 5.2 Position class distribution per player

```sql
SELECT m.player1 AS player, p.pos_class, COUNT(*) AS n
FROM matches m
JOIN games g  ON g.match_id = m.id
JOIN moves mv ON mv.game_id = g.id
JOIN positions p ON p.id    = mv.position_id
WHERE mv.position_id IS NOT NULL
GROUP BY m.player1, p.pos_class
ORDER BY n DESC;
```

### 5.3 Average equity loss per player

```sql
SELECT m.player1, AVG(mv.equity_diff) / 10000.0 AS avg_loss, COUNT(*) AS n
FROM matches m
JOIN games g  ON g.match_id = m.id
JOIN moves mv ON mv.game_id = g.id
WHERE mv.equity_diff IS NOT NULL
GROUP BY m.player1
HAVING COUNT(*) > 1000
ORDER BY avg_loss DESC
LIMIT 20;
```

---

## 6. Statistical Aggregation

### 6.1 Pip difference distribution

```sql
SELECT pip_diff, COUNT(*) AS n
FROM positions
WHERE pos_class IN (0, 1)   -- contact + race only
GROUP BY pip_diff
ORDER BY pip_diff;
```

- Uses `idx_positions_pip_diff` for the GROUP BY; latency ~35 µs for range scans

### 6.2 Prime length histogram

```sql
SELECT prime_len_x, COUNT(*) AS n
FROM positions
WHERE pos_class = 0
GROUP BY prime_len_x
ORDER BY prime_len_x;
```

### 6.3 Equity loss percentiles

```sql
-- SQLite (no PERCENTILE_CONT; use ntile approximation)
WITH ranked AS (
    SELECT equity_diff,
           NTILE(100) OVER (ORDER BY equity_diff) AS pct
    FROM moves
    WHERE equity_diff IS NOT NULL AND equity_diff > 0
)
SELECT pct, MIN(equity_diff) / 10000.0 AS equity
FROM ranked
WHERE pct IN (50, 75, 90, 95, 99)
GROUP BY pct;
```

---

## 7. Visualization Queries

### 7.1 Feature projection sample (for UMAP / PCA input)

```sql
SELECT id, base_record, pos_class, pip_diff, away_x, away_o,
       prime_len_x, prime_len_o
FROM positions
ORDER BY RANDOM()
LIMIT 100000;
```

- Full table scan; run once, save to .npy via `cmd/export-features`
- For filtered projections, add WHERE clause before ORDER BY RANDOM()

### 7.2 Difficulty projection (equity_diff per position)

```sql
SELECT p.id, p.pos_class, p.pip_diff,
       AVG(m.equity_diff) / 10000.0 AS avg_loss
FROM positions p
JOIN moves m ON m.position_id = p.id
WHERE m.equity_diff IS NOT NULL
GROUP BY p.id
ORDER BY p.id;
```

### 7.3 Contact positions in pip_diff range (race analysis window)

```sql
SELECT id, base_record, pip_diff, prime_len_x, prime_len_o
FROM positions
WHERE pos_class = 0
  AND pip_diff BETWEEN -20 AND 20
LIMIT 10000;
```

- Latency: **~35 µs** for BETWEEN queries via `idx_positions_pip_diff`

---

## Performance Summary

| Query type                     | Index used                    | Latency |
|-------------------------------|-------------------------------|---------|
| Zobrist exact lookup           | idx_positions_zobrist         | ~21 µs  |
| Class + away score filter      | idx_positions_class_away      | ~33 µs  |
| pip_diff range                 | idx_positions_pip_diff        | ~35 µs  |
| Error tail (equity_diff > 500) | idx_moves_error (partial)     | fast    |
| Player lookup                  | idx_matches_player1/2         | varies  |

Benchmarked on SQLite WAL, 1.57M positions, AMD Ryzen 7 PRO 6850U.
Import throughput (M3 validation): ~10,000 pos/s with batch transactions.

---

## PostgreSQL Dialect Notes

| Feature          | SQLite                  | PostgreSQL                          |
|------------------|-------------------------|-------------------------------------|
| Partial index    | `WHERE expr`            | Same syntax ✓                       |
| Hash index       | Not supported           | `USING HASH` on zobrist_hash        |
| RANDOM sample    | `ORDER BY RANDOM()`     | `TABLESAMPLE SYSTEM(10)` (faster)   |
| uint64 storage   | int64 (bit-identical)   | Same via BIGINT                     |
| NTILE window     | Supported (SQLite 3.25) | Same ✓                              |
