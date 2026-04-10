"""Application configuration — reads from environment variables."""
import os
from pathlib import Path

DATA_DIR   = Path(os.getenv("DATA_DIR",   "data"))
DB_PATH    = Path(os.getenv("DB_PATH",    str(DATA_DIR / "gbf.duckdb")))
CACHE_TTL  = int(os.getenv("CACHE_TTL",  "3600"))   # seconds
MAX_ROWS   = int(os.getenv("MAX_ROWS",   "200"))     # hard limit for list endpoints
STATIC_DIR = Path(os.getenv("STATIC_DIR", "static"))

# Parquet paths (glob patterns for DuckDB read_parquet)
POSITIONS_GLOB   = str(DATA_DIR / "positions_enriched" / "*.parquet")
CLUSTERS_FILE    = str(DATA_DIR / "position_clusters.parquet")
PLAYERS_FILE     = str(DATA_DIR / "player_profiles.parquet")
MATCHES_FILE     = str(DATA_DIR / "matches.parquet")
RANKINGS_FILE    = str(DATA_DIR / "player_ranking.parquet")
HEATMAP_FILE     = str(DATA_DIR / "materialized" / "heatmap_cells.parquet")
THRESHOLDS_FILE  = str(DATA_DIR / "cube_thresholds.csv")
GAMMON_GV_FILE   = str(DATA_DIR / "gammon_value_by_score.csv")
HEURISTICS_FILE  = str(DATA_DIR / "heuristics.csv")
TRAJECTORIES_FILE = str(DATA_DIR / "trajectory_graph.parquet")
UMAP_FILE        = str(DATA_DIR / "positions_with_hash.parquet")
STATS_FILE       = str(DATA_DIR / "descriptive_stats.json")
TEMPORAL_FILE    = str(DATA_DIR / "temporal_series.csv")
OVERUNDER_FILE   = str(DATA_DIR / "over_under_performers.csv")
