#!/usr/bin/env bash
# Quick pipeline status: batches done, positions so far, ETA.
PARQUET_DIR="${1:-data/parquet}"
JOURNAL="$PARQUET_DIR/.batch_journal"
TOTAL_BATCHES=167

if [[ ! -f "$JOURNAL" ]]; then
  echo "No journal found at $JOURNAL (pipeline not started yet)"
  exit 0
fi

DONE=$(wc -l < "$JOURNAL")
REMAINING=$(( TOTAL_BATCHES - DONE ))

echo "=== Pipeline Status ==="
echo "Batches done:    $DONE / $TOTAL_BATCHES"
echo "Batches left:    $REMAINING"

# Count positions from completed batches only (skip files being written)
POS=$(python3 -c "
import pyarrow.parquet as pq
from pathlib import Path

# Read completed batch IDs from journal
journal = Path('$JOURNAL')
done_batches = set(int(l.strip()) for l in journal.read_text().splitlines() if l.strip().isdigit())

total = 0
for f in sorted(Path('$PARQUET_DIR/positions').glob('part-*.parquet')):
    # Extract batch id from filename part-{batch}-{partition}.parquet
    parts = f.stem.split('-')
    if len(parts) >= 2:
        try:
            batch_id = int(parts[1])
            if batch_id not in done_batches:
                continue
        except ValueError:
            pass
    try:
        total += pq.read_metadata(str(f)).num_rows
    except Exception:
        pass
print(f'{total:,}')
" 2>/dev/null || echo "n/a")
echo "Positions so far: $POS"

# Parquet disk usage
echo "Parquet size:     $(du -sh $PARQUET_DIR 2>/dev/null | cut -f1)"

# ETA (37s/batch)
ETA_MIN=$(( REMAINING * 37 / 60 ))
echo "ETA (S0.1+S0.2):  ~${ETA_MIN} min"

# Last log line
if [[ -f logs/pipeline.log ]]; then
  echo "Last log:         $(tail -1 logs/pipeline.log)"
fi
