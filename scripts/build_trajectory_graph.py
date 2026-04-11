#!/usr/bin/env python3
"""S0.7 — Trajectory graph construction for the backgammon mining study.

Models games as trajectories through position space. Each unique canonical
position (from S0.6) is a node; consecutive positions within a game are
connected by directed edges.

Outputs
-------
graph_edges.parquet         raw transitions (one row per consecutive pair)
    from_hash, to_hash, game_id, match_id, move_number,
    move_played, error, decision_type

graph_edges_agg.parquet     aggregated edges (unique from→to transitions)
    from_hash, to_hash, frequency, proportion,
    avg_error, top_move (most common move_played)

graph_nodes.parquet         per-node metrics (nodes with ≥ threshold matches)
    position_hash, occurrence_count, distinct_games, distinct_matches,
    in_degree, out_degree, avg_error, avg_equity,
    move_entropy (Shannon entropy of outgoing move distribution)

graph_trajectories.parquet  full hash sequence per game (one row per game)
    game_id, match_id, trajectory (list of position_hash)

Usage::

    python scripts/build_trajectory_graph.py \\
        --parquet-dir data/parquet \\
        --output data/parquet \\
        [--node-threshold 3] [--chunk-rows 200000]
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# Edge construction
# ---------------------------------------------------------------------------

_EDGE_SCHEMA = pa.schema([
    pa.field("from_hash",     pa.int64()),
    pa.field("to_hash",       pa.int64()),
    pa.field("game_id",       pa.string()),
    pa.field("match_id",      pa.string()),
    pa.field("move_number",   pa.int16()),
    pa.field("move_played",   pa.string()),
    pa.field("error",         pa.float32()),
    pa.field("decision_type", pa.string()),
])


def build_edges(
    conn: duckdb.DuckDBPyConnection,
    out_path: str,
    chunk_rows: int,
) -> int:
    """Build raw edges via single DuckDB COPY TO (avoids O(n²) LIMIT/OFFSET)."""
    total_games = conn.execute("SELECT COUNT(DISTINCT game_id) FROM hashes").fetchone()[0]
    print(f"  building edges for {total_games:,} games ...")
    t0 = time.time()

    conn.execute(f"""
        COPY (
            SELECT
                CAST(h.position_hash AS BIGINT)   AS from_hash,
                CAST(LEAD(h.position_hash) OVER (
                    PARTITION BY h.game_id ORDER BY h.move_number
                ) AS BIGINT)                       AS to_hash,
                h.game_id,
                h.match_id,
                CAST(h.move_number AS SMALLINT)    AS move_number,
                p.move_played,
                CAST(p.move_played_error AS FLOAT) AS error,
                p.decision_type
            FROM hashes h
            LEFT JOIN positions p ON p.position_id = h.position_id
            QUALIFY to_hash IS NOT NULL
            ORDER BY h.game_id, h.move_number
        ) TO '{out_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)

    n_edges = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    print(f"  {n_edges:,} raw edges in {time.time()-t0:.1f}s")
    return n_edges


# ---------------------------------------------------------------------------
# Aggregated edges
# ---------------------------------------------------------------------------

def build_edges_agg(
    conn: duckdb.DuckDBPyConnection,
    edges_path: str,
    out_path: Path,
) -> int:
    """GROUP BY (from_hash, to_hash) → frequency, proportion, avg_error, top_move."""
    conn.execute(
        f"CREATE OR REPLACE VIEW raw_edges AS SELECT * FROM read_parquet('{edges_path}')"
    )

    df = conn.execute("""
        WITH counts AS (
            SELECT
                from_hash,
                to_hash,
                COUNT(*)                    AS frequency,
                AVG(COALESCE(error, 0.0))   AS avg_error,
                -- Most common move for this transition.
                MODE(move_played)           AS top_move
            FROM raw_edges
            GROUP BY from_hash, to_hash
        ),
        totals AS (
            SELECT from_hash, SUM(frequency) AS total_out
            FROM counts GROUP BY from_hash
        )
        SELECT
            c.from_hash,
            c.to_hash,
            c.frequency,
            ROUND(c.frequency * 1.0 / t.total_out, 4) AS proportion,
            ROUND(c.avg_error, 6)                       AS avg_error,
            c.top_move
        FROM counts c
        JOIN totals t ON t.from_hash = c.from_hash
        ORDER BY c.frequency DESC
    """).pl()

    df = df.with_columns([
        pl.col("frequency").cast(pl.Int32),
        pl.col("avg_error").cast(pl.Float32),
        pl.col("proportion").cast(pl.Float32),
    ])
    df.write_parquet(str(out_path), compression="snappy")
    return len(df)


# ---------------------------------------------------------------------------
# Node metrics
# ---------------------------------------------------------------------------

def _move_entropy(conn: duckdb.DuckDBPyConnection, edges_path: str) -> pl.DataFrame:
    """Compute Shannon entropy of outgoing move distribution per node."""
    conn.execute(
        f"CREATE OR REPLACE VIEW raw_edges AS SELECT * FROM read_parquet('{edges_path}')"
    )
    # Get from_hash → move_played frequency.
    move_dist = conn.execute("""
        SELECT from_hash, move_played, COUNT(*) AS n
        FROM raw_edges
        WHERE move_played IS NOT NULL
        GROUP BY from_hash, move_played
    """).pl()

    totals = move_dist.group_by("from_hash").agg(pl.col("n").sum().alias("total"))
    move_dist = move_dist.join(totals, on="from_hash")

    # Entropy: -sum(p * log2(p)).
    move_dist = move_dist.with_columns(
        (pl.col("n") / pl.col("total")).alias("p")
    ).with_columns(
        (-pl.col("p") * pl.col("p").log(base=2.0)).alias("contrib")
    )

    entropy = move_dist.group_by("from_hash").agg(
        pl.col("contrib").sum().alias("move_entropy")
    )
    return entropy


def build_nodes(
    conn: duckdb.DuckDBPyConnection,
    conv_path: str,
    edges_path: str,
    positions_glob: str,
    out_path: Path,
    threshold: int,
) -> int:
    """Compute per-node metrics for nodes with distinct_matches >= threshold."""
    conn.execute(
        f"CREATE OR REPLACE VIEW convergence AS SELECT * FROM read_parquet('{conv_path}')"
    )
    conn.execute(
        f"CREATE OR REPLACE VIEW raw_edges AS SELECT * FROM read_parquet('{edges_path}')"
    )

    # Candidate nodes above threshold.
    nodes_base = conn.execute(f"""
        SELECT position_hash, occurrence_count, distinct_games, distinct_matches
        FROM convergence
        WHERE distinct_matches >= {threshold}
    """).pl()

    if nodes_base.is_empty():
        print(f"  no nodes with distinct_matches >= {threshold}")
        nodes_base.write_parquet(str(out_path), compression="snappy")
        return 0

    # In/out degree.
    out_deg = conn.execute("""
        SELECT from_hash AS position_hash, COUNT(DISTINCT to_hash) AS out_degree
        FROM raw_edges GROUP BY from_hash
    """).pl()

    in_deg = conn.execute("""
        SELECT to_hash AS position_hash, COUNT(DISTINCT from_hash) AS in_degree
        FROM raw_edges GROUP BY to_hash
    """).pl()

    # Avg error and avg equity at each node.
    pos_stats = conn.execute(f"""
        SELECT h.position_hash,
               AVG(COALESCE(p.move_played_error, 0)) AS avg_error,
               AVG(p.eval_equity)                     AS avg_equity
        FROM hashes h
        JOIN positions p ON p.position_id = h.position_id
        GROUP BY h.position_hash
    """).pl()

    # Move entropy.
    entropy = _move_entropy(conn, edges_path)

    # Join all metrics.
    nodes = (
        nodes_base
        .join(out_deg, on="position_hash", how="left")
        .join(in_deg,  on="position_hash", how="left")
        .join(pos_stats, on="position_hash", how="left")
        .join(entropy, left_on="position_hash", right_on="from_hash", how="left")
        .with_columns([
            pl.col("in_degree").fill_null(0).cast(pl.Int32),
            pl.col("out_degree").fill_null(0).cast(pl.Int32),
            pl.col("avg_error").cast(pl.Float32),
            pl.col("avg_equity").cast(pl.Float64),
            pl.col("move_entropy").fill_null(0.0).cast(pl.Float32),
        ])
        .sort("occurrence_count", descending=True)
    )

    nodes.write_parquet(str(out_path), compression="snappy")
    return len(nodes)


# ---------------------------------------------------------------------------
# Trajectory sequences
# ---------------------------------------------------------------------------

def build_trajectories(
    conn: duckdb.DuckDBPyConnection,
    out_path: Path,
) -> int:
    """Build full hash sequence per game as a list column."""
    df = conn.execute("""
        SELECT game_id, match_id,
               LIST(position_hash ORDER BY move_number) AS trajectory
        FROM hashes
        GROUP BY game_id, match_id
        ORDER BY game_id
    """).pl()

    df.write_parquet(str(out_path), compression="snappy")
    return len(df)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(
    nodes: pl.DataFrame,
    n_edges_raw: int,
    n_edges_agg: int,
    n_trajectories: int,
    threshold: int,
):
    print("\n" + "=" * 60)
    print("  S0.7 — Trajectory Graph Report")
    print("=" * 60)
    print(f"\n  Nodes (distinct_matches ≥ {threshold}): {len(nodes):,}")
    print(f"  Raw edges (transitions):              {n_edges_raw:,}")
    print(f"  Aggregated edges (unique from→to):    {n_edges_agg:,}")
    print(f"  Game trajectories:                    {n_trajectories:,}")

    if not nodes.is_empty():
        print(f"\n  Node statistics:")
        print(f"    avg in_degree:    {nodes['in_degree'].mean():.2f}")
        print(f"    avg out_degree:   {nodes['out_degree'].mean():.2f}")
        print(f"    avg move_entropy: {nodes['move_entropy'].mean():.3f} bits")
        print(f"    avg error:        {nodes['avg_error'].mean():.4f}")

        print(f"\n  Top 10 nodes by occurrence_count:")
        print(f"  {'hash':>20}  {'occur':>7}  {'games':>6}  {'matches':>7}  {'entropy':>7}  {'err':>6}")
        for row in nodes.head(10).iter_rows(named=True):
            print(
                f"  {row['position_hash']:>20}  {row['occurrence_count']:>7,}"
                f"  {row['distinct_games']:>6,}  {row['distinct_matches']:>7,}"
                f"  {row.get('move_entropy', 0) or 0:>7.3f}  {row.get('avg_error', 0) or 0:>6.4f}"
            )
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="S0.7: Build trajectory graph from position hashes"
    )
    parser.add_argument("--parquet-dir", default="data/parquet",
                        help="Parquet directory (S0.2 + S0.6 outputs)")
    parser.add_argument("--output", default="data/parquet",
                        help="Output directory (default: same as --parquet-dir)")
    parser.add_argument("--node-threshold", type=int, default=3,
                        help="Min distinct matches to include a node (default: 3)")
    parser.add_argument("--chunk-rows", type=int, default=200_000,
                        help="Rows per chunk for edge construction (default: 200000)")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prefer deduplicated positions if available.
    pos_dir = parquet_dir / "positions_dedup"
    if not pos_dir.exists() or not list(pos_dir.glob("part-*.parquet")):
        pos_dir = parquet_dir / "positions"
    pos_glob     = str(pos_dir / "part-*.parquet")
    hash_path    = str(parquet_dir / "position_hashes.parquet")
    conv_path    = str(parquet_dir / "convergence_index.parquet")

    for label, p in [
        ("position_hashes.parquet", hash_path),
        ("convergence_index.parquet", conv_path),
        (pos_dir.name + "/", str(pos_dir)),
    ]:
        if not Path(p).exists():
            print(f"ERROR: {label} not found at {p}", file=sys.stderr)
            sys.exit(1)

    print(f"Using {pos_dir.name}/ for positions")
    conn = duckdb.connect()
    conn.execute("SET memory_limit='8GB'")
    conn.execute(f"CREATE VIEW positions AS SELECT * FROM read_parquet('{pos_glob}')")
    conn.execute(f"CREATE VIEW hashes AS SELECT * FROM read_parquet('{hash_path}')")

    edges_path    = str(out_dir / "graph_edges.parquet")
    edges_agg_path = out_dir / "graph_edges_agg.parquet"
    nodes_path    = out_dir / "graph_nodes.parquet"
    traj_path     = out_dir / "graph_trajectories.parquet"

    # Step 1 — raw edges.
    print("Step 1: building raw edges ...")
    n_edges = build_edges(conn, edges_path, args.chunk_rows)

    # Step 2 — aggregated edges.
    print("\nStep 2: aggregating edges ...")
    n_edges_agg = build_edges_agg(conn, edges_path, edges_agg_path)
    print(f"  → graph_edges_agg.parquet: {n_edges_agg:,} unique transitions")

    # Step 3 — node metrics.
    print(f"\nStep 3: computing node metrics (threshold={args.node_threshold}) ...")
    n_nodes = build_nodes(
        conn, conv_path, edges_path, pos_glob, nodes_path, args.node_threshold
    )
    print(f"  → graph_nodes.parquet: {n_nodes:,} nodes")

    # Step 4 — trajectory sequences.
    print("\nStep 4: building trajectory sequences ...")
    n_traj = build_trajectories(conn, traj_path)
    print(f"  → graph_trajectories.parquet: {n_traj:,} game trajectories")

    # Report.
    nodes_df = pl.read_parquet(str(nodes_path)) if n_nodes > 0 else pl.DataFrame()
    print_report(nodes_df, n_edges, n_edges_agg, n_traj, args.node_threshold)

    conn.close()


if __name__ == "__main__":
    main()
