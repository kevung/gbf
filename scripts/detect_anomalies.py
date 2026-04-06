#!/usr/bin/env python3
"""
S1.4 — Anomaly Detection & Trap Positions
Find positions where human error is systematically highest.

Approach:
1. Blunder identification: error > --blunder-threshold (default 0.100)
2. Cluster-based recurring patterns: blunder frequency per cluster
3. Feature-pattern extraction per cluster (dominant features)
4. Isolation Forest for structural outliers (unusual positions)
5. Top-N blunder patterns catalogue
"""

import argparse
import time
import sys
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

CLUSTER_FEATURES = [
    "pip_count_p1", "pip_count_p2", "pip_count_diff",
    "num_blots_p1", "num_blots_p2",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "home_board_strength_p1",
    "longest_prime_p1", "longest_prime_p2",
    "back_anchor_p1", "num_checkers_back_p1",
    "num_builders_p1", "outfield_blots_p1",
    "num_on_bar_p1", "num_on_bar_p2",
    "num_borne_off_p1", "num_borne_off_p2",
    "match_phase",
    "gammon_threat", "gammon_risk", "net_gammon",
    "cube_leverage",
    "score_away_p1", "score_away_p2",
]


def load_enriched(enriched_dir: str, decision_type: str, sample: int) -> pl.DataFrame:
    paths = list(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    want_cols = list(dict.fromkeys(CLUSTER_FEATURES + [
        "position_id", "game_id", "match_id", "move_number",
        "move_played_error", "eval_equity", "eval_win",
        "move_played", "best_move", "decision_type",
    ]))

    frames = []
    total = 0
    for p in sorted(paths):
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols = [c for c in want_cols if c in probe.columns]
            df = pl.read_parquet(p, columns=cols)
        except Exception:
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == decision_type)
        available = [f for f in CLUSTER_FEATURES if f in df.columns]
        df = df.drop_nulls(available)
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        return pl.DataFrame()
    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def load_clusters(clusters_dir: str, decision_type: str) -> pl.DataFrame | None:
    path = Path(clusters_dir) / f"clusters_{decision_type}.parquet"
    if not path.exists():
        print(f"  [warn] No cluster file at {path} — skipping cluster analysis")
        return None
    return pl.read_parquet(path)


def classify_error(error: float) -> str:
    if error < 0.025:
        return "tiny"
    if error < 0.050:
        return "small"
    if error < 0.100:
        return "medium"
    return "blunder"


def describe_cluster(profile: dict) -> str:
    """Human-readable description of a cluster from its mean features."""
    def g(key, default=0.0):
        v = profile.get(key)
        return default if v is None else v

    phase = g("mean_match_phase")
    pip1 = g("mean_pip_count_p1", 100)
    pip2 = g("mean_pip_count_p2", 100)
    bar1 = g("mean_num_on_bar_p1")
    off1 = g("mean_num_borne_off_p1")
    back = g("mean_back_anchor_p1")
    prime1 = g("mean_longest_prime_p1")
    prime2 = g("mean_longest_prime_p2")
    blots1 = g("mean_num_blots_p1")
    back_p1 = g("mean_num_checkers_back_p1")
    gammon = g("mean_gammon_threat")

    if phase > 1.5:
        return f"bearoff (pip≈{pip1:.0f}/{pip2:.0f}, off≈{off1:.1f})"
    if phase > 0.5:
        return f"race (pip≈{pip1:.0f}/{pip2:.0f})"
    # contact
    desc = []
    if back_p1 > 2 and back < 20:
        desc.append("back-game")
    elif prime1 >= 4:
        desc.append(f"prime({prime1:.1f})")
    elif prime2 >= 4:
        desc.append(f"opp-prime({prime2:.1f})")
    elif bar1 > 0.3:
        desc.append("blitz")
    else:
        desc.append("holding")
    if gammon > 0.2:
        desc.append(f"gammon-threat={gammon:.2f}")
    desc.append(f"pip≈{pip1:.0f}/{pip2:.0f}")
    return ", ".join(desc)


def run_blunder_analysis(df: pl.DataFrame, blunder_threshold: float) -> pl.DataFrame:
    """Return blunder rows with error classification."""
    if "move_played_error" not in df.columns:
        return pl.DataFrame()
    blunders = df.filter(pl.col("move_played_error") >= blunder_threshold)
    return blunders


def cluster_blunder_stats(blunders: pl.DataFrame, all_df: pl.DataFrame) -> pl.DataFrame:
    """Per-cluster blunder rate and mean error."""
    if "cluster" not in blunders.columns or "cluster" not in all_df.columns:
        return pl.DataFrame()

    total_per_cluster = (
        all_df.group_by("cluster")
        .agg(pl.len().alias("total_count"))
    )
    blunder_per_cluster = (
        blunders.group_by("cluster")
        .agg([
            pl.len().alias("blunder_count"),
            pl.col("move_played_error").mean().alias("mean_blunder_error"),
            pl.col("move_played_error").max().alias("max_error"),
        ])
    )
    return (
        blunder_per_cluster.join(total_per_cluster, on="cluster", how="left")
        .with_columns(
            (pl.col("blunder_count") / pl.col("total_count")).alias("blunder_rate")
        )
        .sort("blunder_rate", descending=True)
    )


def run_isolation_forest(df: pl.DataFrame, contamination: float,
                         n_estimators: int) -> pl.Series:
    """Isolation Forest to detect structurally unusual positions."""
    available = [f for f in CLUSTER_FEATURES if f in df.columns]
    X = df.select(available).to_numpy().astype(np.float32)
    col_means = np.nanmean(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_means, inds[1])

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    iso = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    labels = iso.fit_predict(X_scaled)  # -1 = outlier, 1 = inlier
    scores = iso.score_samples(X_scaled)  # lower = more anomalous
    return pl.Series("is_outlier", labels == -1), pl.Series("anomaly_score", scores)


def print_top_patterns(df: pl.DataFrame, top_n: int, cluster_profiles: dict) -> None:
    """Print top blunder patterns."""
    if df.is_empty():
        return

    group_cols = ["cluster"] if "cluster" in df.columns else []

    if group_cols and "move_played_error" in df.columns:
        agg = (
            df.group_by(group_cols)
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
                pl.col("move_played_error").max().alias("max_error"),
            ])
            .sort("count", descending=True)
            .head(top_n)
        )
        print(f"\n  {'Cluster':>8} {'Count':>7} {'MeanErr':>9} {'MaxErr':>8}  Description")
        print("  " + "-" * 75)
        for row in agg.iter_rows(named=True):
            cid = row["cluster"]
            desc = cluster_profiles.get(cid, f"cluster {cid}")
            print(f"  {cid:>8} {row['count']:>7,} {row['mean_error']:>9.4f} "
                  f"{row['max_error']:>8.4f}  {desc}")
    elif "move_played_error" in df.columns:
        top = df.sort("move_played_error", descending=True).head(top_n)
        print(f"\n  {'Position':<30} {'Error':>8}")
        print("  " + "-" * 42)
        for row in top.iter_rows(named=True):
            pid = row.get("position_id", "?")
            err = row.get("move_played_error", float("nan"))
            print(f"  {str(pid):<30} {err:>8.4f}")


def process(decision_type: str, enriched_dir: str, clusters_dir: str,
            output_dir: Path, sample: int, blunder_threshold: float,
            contamination: float, top_n: int, n_estimators: int) -> None:
    print(f"\n{'─'*60}")
    print(f"  Anomaly Detection — {decision_type.upper()} decisions")
    print(f"{'─'*60}")

    t0 = time.time()
    df = load_enriched(enriched_dir, decision_type, sample)
    if df.is_empty():
        print(f"  No data for {decision_type}")
        return
    print(f"  Loaded {len(df):,} rows ({time.time()-t0:.1f}s)")

    # Merge cluster labels if available
    cluster_df = load_clusters(clusters_dir, decision_type)
    cluster_profiles_map: dict = {}
    if cluster_df is not None and "position_id" in df.columns:
        df = df.join(cluster_df.select(["position_id", "cluster"]),
                     on="position_id", how="left")
        print(f"  Cluster labels merged")

    # Blunder analysis
    blunders = run_blunder_analysis(df, blunder_threshold)
    blunder_pct = len(blunders) / max(len(df), 1) * 100
    print(f"  Blunders (>{blunder_threshold:.3f}): {len(blunders):,} ({blunder_pct:.1f}%)")

    # Cluster blunder stats
    if "cluster" in df.columns and not blunders.is_empty():
        cluster_stats = cluster_blunder_stats(blunders, df)

        # Build cluster description map
        profiles_path = Path(clusters_dir) / f"cluster_profiles_{decision_type}.csv"
        if profiles_path.exists():
            prof_df = pl.read_csv(profiles_path)
            for row in prof_df.iter_rows(named=True):
                cid = row.get("cluster", -99)
                cluster_profiles_map[cid] = describe_cluster(row)

        print(f"\n  Blunder rate by cluster:")
        print_top_patterns(blunders, top_n, cluster_profiles_map)

        stats_path = output_dir / f"blunder_by_cluster_{decision_type}.csv"
        cluster_stats.write_csv(stats_path)
        print(f"  → {stats_path}")

    # Isolation Forest
    print(f"\n  Running Isolation Forest (contamination={contamination})...")
    t1 = time.time()
    is_outlier, anomaly_score = run_isolation_forest(df, contamination, n_estimators)
    print(f"  → {is_outlier.sum():,} outliers detected ({time.time()-t1:.1f}s)")

    # Save outliers with error info
    out_cols = ["position_id", "move_played_error", "eval_equity"]
    if "cluster" in df.columns:
        out_cols.append("cluster")
    out_cols += [f for f in ["match_phase", "gammon_threat", "pip_count_diff"]
                 if f in df.columns]

    outlier_df = (
        df.with_columns([is_outlier, anomaly_score])
        .filter(pl.col("is_outlier"))
        .select([c for c in out_cols + ["anomaly_score"] if c in df.columns
                 or c in ["is_outlier", "anomaly_score"]])
        .sort("anomaly_score")
    )
    outlier_path = output_dir / f"outliers_{decision_type}.csv"
    outlier_df.write_csv(outlier_path)
    print(f"  → {outlier_path}")

    # Blunders catalogue
    if not blunders.is_empty():
        catalogue_cols = [c for c in [
            "position_id", "game_id", "move_number",
            "move_played", "best_move", "move_played_error",
            "eval_equity", "match_phase", "gammon_threat",
            "score_away_p1", "score_away_p2", "cluster",
        ] if c in blunders.columns]
        catalogue = blunders.select(catalogue_cols).sort(
            "move_played_error", descending=True
        ).head(top_n * 10)
        cat_path = output_dir / f"blunder_catalogue_{decision_type}.csv"
        catalogue.write_csv(cat_path)
        print(f"  → {cat_path} (top {len(catalogue)} blunders)")

    # Summary stats by error bucket
    if "move_played_error" in df.columns and df["move_played_error"].drop_nulls().len() > 0:
        bucket_df = df.filter(pl.col("move_played_error").is_not_null()).with_columns(
            pl.col("move_played_error").map_elements(
                classify_error, return_dtype=pl.Utf8
            ).alias("error_bucket")
        )
        bucket_stats = (
            bucket_df.group_by("error_bucket")
            .agg([
                pl.len().alias("count"),
                pl.col("move_played_error").mean().alias("mean_error"),
            ])
            .sort("mean_error")
        )
        print(f"\n  Error bucket distribution:")
        total = len(df)
        for row in bucket_stats.iter_rows(named=True):
            pct = row["count"] / total * 100
            print(f"    {row['error_bucket']:<10} {row['count']:>8,} ({pct:5.1f}%)  "
                  f"mean={row['mean_error']:.4f}")

        bucket_path = output_dir / f"error_buckets_{decision_type}.csv"
        bucket_stats.write_csv(bucket_path)
        print(f"  → {bucket_path}")

    print(f"  Done in {time.time()-t0:.1f}s")


def main():
    ap = argparse.ArgumentParser(description="S1.4 — Anomaly Detection & Trap Positions")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet directory (S0.4)")
    ap.add_argument("--clusters", required=True,
                    help="Path to cluster output directory (S1.3)")
    ap.add_argument("--output", default="data/anomalies",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max rows per decision type (default: 500000)")
    ap.add_argument("--blunder-threshold", type=float, default=0.100,
                    help="Error threshold for blunder (default: 0.100)")
    ap.add_argument("--contamination", type=float, default=0.05,
                    help="Isolation Forest contamination rate (default: 0.05)")
    ap.add_argument("--top-n", type=int, default=50,
                    help="Top N patterns to report (default: 50)")
    ap.add_argument("--n-estimators", type=int, default=100,
                    help="Isolation Forest trees (default: 100)")
    ap.add_argument("--types", nargs="+", default=["checker", "cube"],
                    help="Decision types (default: checker cube)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.4 — Anomaly Detection & Trap Positions")
    print("=" * 60)
    print(f"  enriched    : {args.enriched}")
    print(f"  clusters    : {args.clusters}")
    print(f"  output      : {output_dir}")
    print(f"  sample      : {args.sample:,}")
    print(f"  blunder thr : {args.blunder_threshold}")

    for dtype in args.types:
        process(
            decision_type=dtype,
            enriched_dir=args.enriched,
            clusters_dir=args.clusters,
            output_dir=output_dir,
            sample=args.sample,
            blunder_threshold=args.blunder_threshold,
            contamination=args.contamination,
            top_n=args.top_n,
            n_estimators=args.n_estimators,
        )

    print(f"\n{'='*60}")
    print(f"  Done — outputs in {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
