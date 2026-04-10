"""
materialise.py — Offline batch pre-computation for the GBF dashboard.

Run once after all S0–S3 analysis scripts have produced their Parquet/CSV
outputs. Builds materialised aggregation tables and (optionally) the UMAP
tile pyramid for View 7.

Usage:
    python -m backend.materialise [--data-dir ./data] [--no-tiles]
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def run(data_dir: Path, no_tiles: bool = False) -> None:
    mat_dir = data_dir / "materialized"
    mat_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "gbf.duckdb"
    conn = duckdb.connect(str(db_path))

    t_start = time.time()
    manifest: dict = {"built_at": datetime.now(timezone.utc).isoformat(), "tables": {}}

    print("── Registering Parquet views ──────────────────────────")
    _register_views(conn, data_dir)

    steps = [
        ("heatmap_cells",        _build_heatmap_cells),
        ("player_profiles_agg",  _build_player_profiles_agg),
        ("cluster_summaries",    _build_cluster_summaries),
        ("cube_thresholds_agg",  _build_cube_thresholds_agg),
        ("rankings",             _build_rankings),
        ("temporal_series",      _build_temporal_series),
        ("error_distribution",   _build_error_distribution),
    ]

    for name, fn in steps:
        print(f"  Building {name}…", end=" ", flush=True)
        t0 = time.time()
        rows = fn(conn, data_dir, mat_dir)
        elapsed = time.time() - t0
        print(f"{rows} rows  ({elapsed:.1f}s)")
        manifest["tables"][name] = {"rows": rows, "elapsed_s": round(elapsed, 2)}

    if not no_tiles:
        print("  Building tile pyramid…", end=" ", flush=True)
        t0 = time.time()
        n = _build_tiles(conn, mat_dir)
        elapsed = time.time() - t0
        print(f"{n} tiles  ({elapsed:.1f}s)")
        manifest["tables"]["tiles"] = {"count": n, "elapsed_s": round(elapsed, 2)}

    manifest["total_elapsed_s"] = round(time.time() - t_start, 1)
    manifest_path = mat_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n✓ Done in {manifest['total_elapsed_s']}s  →  {mat_dir}")
    conn.close()


# ── View registration ──────────────────────────────────────────────────────────

def _register_views(conn: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    views = {
        "positions": f"read_parquet('{data_dir}/positions_enriched/*.parquet')",
        "pos_clusters": f"read_parquet('{data_dir}/position_clusters.parquet')",
        "player_profiles": f"read_parquet('{data_dir}/player_profiles.parquet')",
        "player_rankings_raw": f"read_parquet('{data_dir}/player_ranking.parquet')",
        "matches": f"read_parquet('{data_dir}/matches.parquet')",
    }
    for name, src in views.items():
        try:
            conn.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {src}")
        except Exception as e:
            print(f"    [warn] {name}: {e}")


# ── Build functions ────────────────────────────────────────────────────────────

def _build_heatmap_cells(conn, data_dir, mat_dir) -> int:
    out = mat_dir / "heatmap_cells.parquet"
    conn.execute(f"""
        COPY (
            SELECT away_p1, away_p2,
                   COALESCE(match_length, -1) AS match_length,
                   COUNT(*)                   AS n_decisions,
                   AVG(move_played_error)      AS avg_error,
                   STDDEV(move_played_error)   AS std_error,
                   AVG(CASE WHEN is_missed_double THEN 1.0 ELSE 0.0 END) AS missed_double_rate,
                   AVG(CASE WHEN is_wrong_take    THEN 1.0 ELSE 0.0 END) AS wrong_take_rate,
                   AVG(CASE WHEN is_wrong_pass    THEN 1.0 ELSE 0.0 END) AS wrong_pass_rate
            FROM positions
            WHERE decision_type = 'cube'
            GROUP BY away_p1, away_p2, match_length
            HAVING COUNT(*) >= 20
        ) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_player_profiles_agg(conn, data_dir, mat_dir) -> int:
    out = mat_dir / "player_profiles_agg.parquet"
    conn.execute(f"""
        COPY (
            SELECT p.*,
                   r.pr_rating, r.pr_rank, r.pr_ci_low, r.pr_ci_high,
                   r.checker_rating, r.cube_rating,
                   r.contact_rating, r.race_rating, r.bearoff_rating
            FROM player_profiles p
            LEFT JOIN player_rankings_raw r USING (player_name)
        ) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_cluster_summaries(conn, data_dir, mat_dir) -> int:
    out = mat_dir / "cluster_summaries.parquet"
    conn.execute(f"""
        COPY (
            SELECT cluster_id,
                   ANY_VALUE(archetype_label)  AS archetype_label,
                   COUNT(*)                    AS position_count,
                   AVG(move_played_error)       AS avg_error,
                   STDDEV(move_played_error)    AS std_error,
                   MODE(match_phase)            AS dominant_phase,
                   AVG(CASE WHEN match_phase = 0 THEN 1.0 ELSE 0.0 END) AS contact_pct,
                   AVG(CASE WHEN match_phase = 1 THEN 1.0 ELSE 0.0 END) AS race_pct,
                   AVG(CASE WHEN match_phase = 2 THEN 1.0 ELSE 0.0 END) AS bearoff_pct
            FROM pos_clusters
            GROUP BY cluster_id
        ) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_cube_thresholds_agg(conn, data_dir, mat_dir) -> int:
    """Copy S3.3 CSV thresholds into Parquet for fast lookup."""
    src = data_dir / "cube_thresholds.csv"
    out = mat_dir / "cube_thresholds_agg.parquet"
    if not src.exists():
        return 0
    conn.execute(f"""
        COPY (SELECT * FROM read_csv_auto('{src}')) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_rankings(conn, data_dir, mat_dir) -> int:
    out = mat_dir / "rankings.parquet"
    conn.execute(f"""
        COPY (
            SELECT *,
                   ROW_NUMBER() OVER (ORDER BY pr_rating ASC NULLS LAST) AS pr_rank_computed
            FROM player_rankings_raw
        ) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_temporal_series(conn, data_dir, mat_dir) -> int:
    src = data_dir / "temporal_series.csv"
    out = mat_dir / "temporal_series.parquet"
    if not src.exists():
        return 0
    conn.execute(f"""
        COPY (SELECT * FROM read_csv_auto('{src}')) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_error_distribution(conn, data_dir, mat_dir) -> int:
    out = mat_dir / "error_distribution.parquet"
    conn.execute(f"""
        COPY (
            SELECT decision_type,
                   width_bucket(move_played_error, 0.0, 2.0, 40) AS bucket,
                   COUNT(*) AS count,
                   MIN(move_played_error) AS bin_min,
                   MAX(move_played_error) AS bin_max
            FROM positions
            GROUP BY decision_type, bucket
            ORDER BY decision_type, bucket
        ) TO '{out}' (FORMAT PARQUET)
    """)
    return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]


def _build_tiles(conn, mat_dir) -> int:
    """
    Generate PNG density tile pyramid (zoom 0–7) from UMAP coordinates.
    Requires: positions_with_hash.parquet with umap_x / umap_y columns.
    Falls back gracefully if UMAP data or pillow is unavailable.
    """
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except ImportError:
        print("  [skip] pillow/numpy not installed — tile pyramid skipped")
        return 0

    umap_path = mat_dir.parent / "positions_with_hash.parquet"
    if not umap_path.exists():
        return 0

    rows = conn.execute(
        f"SELECT umap_x, umap_y FROM read_parquet('{umap_path}') LIMIT 1000000"
    ).fetchall()
    if not rows:
        return 0

    xs = np.array([r[0] for r in rows], dtype=np.float32)
    ys = np.array([r[1] for r in rows], dtype=np.float32)
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())

    tiles_dir = mat_dir / "tiles"
    total = 0

    for zoom in range(8):  # 0–7
        n = 2 ** zoom
        tile_size = 256
        z_dir = tiles_dir / str(zoom)

        for tx in range(n):
            for ty in range(n):
                # World bounds for this tile
                wx0 = x_min + (x_max - x_min) * tx / n
                wx1 = x_min + (x_max - x_min) * (tx + 1) / n
                wy0 = y_min + (y_max - y_min) * ty / n
                wy1 = y_min + (y_max - y_min) * (ty + 1) / n

                mask = (xs >= wx0) & (xs < wx1) & (ys >= wy0) & (ys < wy1)
                px = ((xs[mask] - wx0) / (wx1 - wx0) * tile_size).astype(int)
                py = ((ys[mask] - wy0) / (wy1 - wy0) * tile_size).astype(int)

                img = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
                if len(px):
                    heat = np.zeros((tile_size, tile_size), dtype=np.float32)
                    np.add.at(heat, (py.clip(0, tile_size-1), px.clip(0, tile_size-1)), 1)
                    heat = np.log1p(heat)
                    heat /= heat.max() if heat.max() > 0 else 1
                    r = (heat * 255).astype(np.uint8)
                    g = ((1 - heat) * 100).astype(np.uint8)
                    alpha = (np.where(heat > 0, 200, 0)).astype(np.uint8)
                    arr = np.stack([r, g, np.zeros_like(r), alpha], axis=-1)
                    img = Image.fromarray(arr, "RGBA")

                out_path = z_dir / str(tx)
                out_path.mkdir(parents=True, exist_ok=True)
                img.save(out_path / f"{ty}.png", "PNG")
                total += 1

    return total


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GBF Dashboard — pre-computation")
    parser.add_argument("--data-dir", default="data", help="Path to data directory")
    parser.add_argument("--no-tiles", action="store_true", help="Skip tile pyramid generation")
    args = parser.parse_args()
    run(Path(args.data_dir), no_tiles=args.no_tiles)
