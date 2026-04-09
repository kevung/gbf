#!/usr/bin/env python3
"""
S2.2 — Player Clustering by Profile

Group players into archetypes based on the ~20 metrics computed by S2.1.
Uses Z-score normalisation → PCA → K-means / HDBSCAN.

Outputs
-------
  <output>/player_clusters.parquet      player × cluster_id × archetype_name
  <output>/cluster_profiles.csv         mean metrics per cluster (radar data)
  <output>/cluster_pca.csv              first 2 PCA components per player
  <output>/archetype_descriptions.txt   human-readable cluster summaries

Usage
-----
  python scripts/cluster_players.py \\
      --profiles data/player_profiles/player_profiles.parquet \\
      --output   data/player_profiles \\
      [--n-clusters 6] [--method kmeans|hdbscan] [--min-players 5]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

# ---------------------------------------------------------------------------
# Metric columns used for clustering (available from S2.1 output)
# ---------------------------------------------------------------------------
CLUSTER_METRICS = [
    "avg_error_checker",
    "avg_error_cube",
    "error_rate",
    "blunder_rate",
    "avg_error_contact",
    "avg_error_race",
    "avg_error_bearoff",
    "aggression_index",
    "risk_appetite",
    "error_std",
    "streak_tendency",
    "missed_double_rate",
    "wrong_take_rate",
    "wrong_pass_rate",
]

# Archetype hypothesis labels (indexed by cluster id after sorting by avg PR)
ARCHETYPE_HYPOTHESES = [
    "The Steady",
    "The Technician",
    "The Cubist",
    "The Sprinter",
    "The Warrior",
    "The Erratic",
]


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def load_profiles(path: str) -> pl.DataFrame:
    p = Path(path)
    if not p.exists():
        sys.exit(f"player_profiles not found: {path}")
    return pl.read_parquet(p) if path.endswith(".parquet") else pl.read_csv(p)


def select_features(profiles: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Return profiles filtered to rows with enough data, and the feature list."""
    available = [c for c in CLUSTER_METRICS if c in profiles.columns]
    if len(available) < 4:
        sys.exit(f"Too few clustering features available ({available}). "
                 "Run S2.1 first.")
    # Keep only rows where at least 80% of features are non-null
    threshold = int(len(available) * 0.8)
    df = profiles.with_columns([
        pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in available])
        .alias("_n_valid")
    ]).filter(pl.col("_n_valid") >= threshold).drop("_n_valid")
    # Fill remaining nulls with column median
    for col in available:
        if df[col].null_count() > 0:
            median = df[col].drop_nulls().median()
            df = df.with_columns(pl.col(col).fill_null(median))
    return df, available


def run_pca(X: np.ndarray, n_components: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Return PCA-projected coords and explained variance ratios."""
    n_comp = min(n_components, X.shape[1], X.shape[0] - 1)
    pca = PCA(n_components=n_comp, random_state=42)
    coords = pca.fit_transform(X)
    return coords, pca.explained_variance_ratio_


def cluster_kmeans(coords: np.ndarray, n_clusters: int) -> np.ndarray:
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=20)
    return km.fit_predict(coords)


def cluster_hdbscan(coords: np.ndarray, min_cluster_size: int) -> np.ndarray:
    try:
        import hdbscan
    except ImportError:
        sys.exit("hdbscan not installed. Run: pip install hdbscan")
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size,
                                 min_samples=5, prediction_data=True)
    return clusterer.fit_predict(coords)


def name_clusters(profiles_with_clusters: pl.DataFrame,
                  features: list[str],
                  n_clusters: int,
                  n_hypotheses: int = 6) -> dict[int, str]:
    """
    Assign archetype names based on cluster centroid characteristics.
    Sort clusters by avg_error_checker (ascending = best first) and map
    to hypothetical archetype names.
    """
    cluster_means = (
        profiles_with_clusters
        .group_by("cluster_id")
        .agg([pl.col(f).mean().alias(f) for f in features
              if f in profiles_with_clusters.columns])
        .sort("cluster_id")
    )

    # Sort clusters by overall PR (avg_error_checker) — best cluster first
    if "avg_error_checker" in cluster_means.columns:
        sorted_clusters = (
            cluster_means.sort("avg_error_checker", descending=False)
            .select("cluster_id")
            .to_series()
            .to_list()
        )
    else:
        sorted_clusters = list(range(n_clusters))

    names: dict[int, str] = {}
    for rank, cid in enumerate(sorted_clusters):
        if rank < len(ARCHETYPE_HYPOTHESES):
            names[cid] = ARCHETYPE_HYPOTHESES[rank]
        else:
            names[cid] = f"Archetype {rank + 1}"

    # Override with data-driven refinements: if a cluster has notably high
    # error_std it's erratic; if cube error >> checker error it's a cube weakness
    for row in cluster_means.iter_rows(named=True):
        cid = row["cluster_id"]
        if cid not in names:
            names[cid] = "Noise/Unclassified"  # HDBSCAN -1
        if row.get("error_std") is not None and row.get("avg_error_checker") is not None:
            std = row["error_std"]
            err = row["avg_error_checker"]
            if std > 0 and std / max(err, 0.001) > 1.2:
                names[cid] = "The Erratic"

    return names


def build_cluster_profiles(df: pl.DataFrame, features: list[str]) -> pl.DataFrame:
    """Mean + std of each feature per cluster, plus player count."""
    agg_exprs = [pl.len().alias("n_players")]
    for f in features:
        if f in df.columns:
            agg_exprs.append(pl.col(f).mean().alias(f"mean_{f}"))
            agg_exprs.append(pl.col(f).std().alias(f"std_{f}"))
    return df.group_by(["cluster_id", "archetype"]).agg(agg_exprs).sort("cluster_id")


def print_cluster_summary(profiles: pl.DataFrame, cluster_profiles: pl.DataFrame) -> None:
    section("Cluster Summary")
    for row in cluster_profiles.sort("cluster_id").iter_rows(named=True):
        cid = row["cluster_id"]
        arch = row["archetype"]
        n = row["n_players"]
        pr = row.get("mean_avg_error_checker")
        err_std = row.get("mean_error_std")
        blunder = row.get("mean_blunder_rate")
        print(f"\n  Cluster {cid}: {arch}  (N={n})")
        if pr is not None:
            print(f"    avg_error_checker (PR proxy) : {pr:.4f}")
        if err_std is not None:
            print(f"    error_std (consistency)      : {err_std:.4f}")
        if blunder is not None:
            print(f"    blunder_rate                 : {blunder:.4f}")

        # Show top 5 players in cluster
        top5 = (
            profiles.filter(pl.col("cluster_id") == cid)
            .sort("avg_error_checker", descending=False)
            .head(5)
        )
        names_list = top5.select("player").to_series().to_list()
        print(f"    top players (by PR): {', '.join(str(n) for n in names_list)}")


def write_archetype_descriptions(cluster_profiles: pl.DataFrame,
                                 output_path: Path,
                                 features: list[str]) -> None:
    lines = ["S2.2 — Player Archetype Descriptions", "=" * 60, ""]
    for row in cluster_profiles.sort("cluster_id").iter_rows(named=True):
        cid = row["cluster_id"]
        arch = row["archetype"]
        n = row["n_players"]
        lines.append(f"Cluster {cid}: {arch}  (N={n})")
        lines.append("-" * 40)
        for f in features:
            mean_key = f"mean_{f}"
            if mean_key in row and row[mean_key] is not None:
                lines.append(f"  {f:<32} : {row[mean_key]:>8.4f}")
        lines.append("")
    output_path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="S2.2 — Player Clustering by Profile")
    ap.add_argument("--profiles", required=True,
                    help="Path to player_profiles.parquet or .csv (S2.1 output)")
    ap.add_argument("--output", default="data/player_profiles",
                    help="Output directory")
    ap.add_argument("--n-clusters", type=int, default=6,
                    help="Number of clusters for K-means (default: 6)")
    ap.add_argument("--method", choices=["kmeans", "hdbscan"], default="kmeans",
                    help="Clustering method (default: kmeans)")
    ap.add_argument("--min-players", type=int, default=5,
                    help="Min players per cluster to keep (HDBSCAN only)")
    ap.add_argument("--pca-components", type=int, default=10,
                    help="PCA components before clustering (default: 10)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S2.2 — Player Clustering by Profile")
    print("=" * 60)
    print(f"  profiles    : {args.profiles}")
    print(f"  output      : {output_dir}")
    print(f"  method      : {args.method}")
    if args.method == "kmeans":
        print(f"  n-clusters  : {args.n_clusters}")
    print(f"  pca-comps   : {args.pca_components}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load profiles
    # ------------------------------------------------------------------
    section("Loading player profiles")
    profiles = load_profiles(args.profiles)
    print(f"  {len(profiles):,} players loaded")

    df, features = select_features(profiles)
    print(f"  {len(df):,} players with sufficient data")
    print(f"  Features used ({len(features)}): {', '.join(features)}")

    if len(df) < 10:
        sys.exit("Not enough players for clustering (need >= 10).")

    # ------------------------------------------------------------------
    # Normalise → PCA
    # ------------------------------------------------------------------
    section("Normalisation & PCA")
    X_raw = df.select(features).to_numpy().astype(np.float64)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    pca_coords, var_ratios = run_pca(X_scaled, n_components=args.pca_components)
    cumvar = np.cumsum(var_ratios)
    print(f"  PCA variance explained:")
    for i, (v, cv) in enumerate(zip(var_ratios[:5], cumvar[:5])):
        print(f"    PC{i+1}: {v*100:.1f}%  (cumulative: {cv*100:.1f}%)")

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------
    section(f"Clustering ({args.method})")
    if args.method == "kmeans":
        labels = cluster_kmeans(pca_coords, args.n_clusters)
    else:
        labels = cluster_hdbscan(pca_coords, min_cluster_size=args.min_players)

    n_clusters_found = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    print(f"  Clusters found : {n_clusters_found}")
    if n_noise > 0:
        print(f"  Noise points   : {n_noise} (HDBSCAN unclassified)")

    # ------------------------------------------------------------------
    # Name clusters & build output tables
    # ------------------------------------------------------------------
    section("Naming archetypes")
    df = df.with_columns(pl.Series("cluster_id", labels.tolist(), dtype=pl.Int32))
    archetype_map = name_clusters(df, features, n_clusters_found)
    # HDBSCAN noise → "Unclassified"
    archetype_map[-1] = "Unclassified"
    df = df.with_columns(
        pl.col("cluster_id")
        .map_elements(lambda c: archetype_map.get(c, f"Cluster {c}"),
                      return_dtype=pl.String)
        .alias("archetype")
    )

    for cid, name in sorted(archetype_map.items()):
        if cid == -1:
            continue
        count = (labels == cid).sum()
        print(f"  Cluster {cid}: {name}  (N={count})")

    cluster_profiles = build_cluster_profiles(df, features)

    # PCA coordinates (first 2 components for visualisation)
    pca_df = pl.DataFrame({
        "player": df.select("player").to_series(),
        "cluster_id": pl.Series(labels.tolist(), dtype=pl.Int32),
        "archetype": df.select("archetype").to_series(),
        "pc1": pca_coords[:, 0].tolist(),
        "pc2": pca_coords[:, 1].tolist(),
    })
    if pca_coords.shape[1] > 2:
        pca_df = pca_df.with_columns(
            pl.Series(pca_coords[:, 2].tolist(), dtype=pl.Float64).alias("pc3")
        )

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    section("Saving outputs")

    # player_clusters (player + cluster_id + archetype, joined to key metrics)
    key_metrics = ["total_matches", "avg_error_checker", "pr_rating",
                   "blunder_rate", "error_std"]
    keep_cols = (["player", "cluster_id", "archetype"] +
                 [c for c in key_metrics if c in df.columns])
    player_clusters = df.select([c for c in keep_cols if c in df.columns])

    clusters_parquet = output_dir / "player_clusters.parquet"
    player_clusters.write_parquet(clusters_parquet)
    print(f"  → {clusters_parquet}  ({len(player_clusters):,} rows)")

    profiles_path = output_dir / "cluster_profiles.csv"
    cluster_profiles.write_csv(profiles_path)
    print(f"  → {profiles_path}  ({len(cluster_profiles):,} clusters)")

    pca_path = output_dir / "cluster_pca.csv"
    pca_df.write_csv(pca_path)
    print(f"  → {pca_path}  ({len(pca_df):,} rows)")

    desc_path = output_dir / "archetype_descriptions.txt"
    write_archetype_descriptions(cluster_profiles, desc_path, features)
    print(f"  → {desc_path}")

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    print_cluster_summary(df, cluster_profiles)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
