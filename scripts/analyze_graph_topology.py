#!/usr/bin/env python3
"""
S1.8 — Convergence & Graph Topology

Explores the trajectory graph structure built by S0.7: crossroads,
convergence, divergence, degree distribution, betweenness centrality,
Louvain communities, and frequent move paths.

Analyses:
  1. Top crossroads: most-traversed positions, familiarity vs error
  2. Degree distribution (in/out) — power law check
  3. Betweenness centrality on high-frequency subgraph
  4. Louvain community detection + comparison with S1.3 clusters
  5. Frequent 3-5 move paths (highway vs trail classification)
  6. Divergence analysis: at what horizon do trajectories diverge?
  7. Convergence attractors: positions that many trajectories reach

Dependencies: S0.7 (graph outputs), S1.3 (cluster labels, optional).
Input:  graph_nodes.parquet, graph_edges_agg.parquet,
        graph_trajectories.parquet, position_hashes.parquet (S0.6),
        clusters_checker.parquet (S1.3, optional)
Output: 9 CSV files in --output directory
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import polars as pl
import networkx as nx

HIGHWAY_MIN_FREQ = 10   # edges with frequency >= this are "highways"
TOP_CROSSROADS   = 100  # how many crossroads to report
TOP_PATHS        = 100  # how many frequent paths to report
CENTRALITY_NODES = 5_000  # max nodes in betweenness subgraph
CENTRALITY_K     = 200    # approximate betweenness samples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def load_parquet_optional(path: Path, columns: list[str] | None = None) -> pl.DataFrame | None:
    """Load a Parquet file, returning None if it does not exist."""
    if not path.exists():
        print(f"  [warn] not found: {path}")
        return None
    if columns:
        return pl.read_parquet(path, columns=columns)
    return pl.read_parquet(path)


# ---------------------------------------------------------------------------
# Analysis 1 — Crossroads
# ---------------------------------------------------------------------------

def analyze_crossroads(
    nodes: pl.DataFrame,
    hashes: pl.DataFrame | None,
    clusters: pl.DataFrame | None,
    output_dir: Path,
) -> pl.DataFrame:
    """Top crossroads by distinct_matches, enriched with move_number and cluster."""
    section("Analysis 1 — Top Crossroads")

    top = nodes.sort("distinct_matches", descending=True).head(TOP_CROSSROADS)

    if hashes is not None and "position_hash" in hashes.columns:
        # Average move_number per hash (proxy for game phase)
        mn_df = (
            hashes.group_by("position_hash")
            .agg([
                pl.col("move_number").mean().alias("avg_move_number"),
                pl.col("move_number").min().alias("min_move_number"),
                pl.col("move_number").max().alias("max_move_number"),
            ])
        )
        top = top.join(mn_df, on="position_hash", how="left")

        # Dominant cluster per hash (join hashes → clusters, mode per hash)
        if clusters is not None and "position_id" in hashes.columns:
            hc = hashes.select(["position_hash", "position_id"]).join(
                clusters.select(["position_id", "cluster"]),
                on="position_id",
                how="left",
            )
            # Most common cluster for each hash
            dominant = (
                hc.drop_nulls("cluster")
                .group_by("position_hash")
                .agg(pl.col("cluster").mode().first().alias("dominant_cluster"))
            )
            top = top.join(dominant, on="position_hash", how="left")

    path = output_dir / "top_crossroads.csv"
    top.write_csv(path)
    print(f"  Top {len(top):,} crossroads → {path}")

    # Summary
    print(f"  distinct_matches range: "
          f"{top['distinct_matches'].min():,} – {top['distinct_matches'].max():,}")
    if "avg_move_number" in top.columns:
        print(f"  avg_move_number range : "
              f"{top['avg_move_number'].min():.1f} – {top['avg_move_number'].max():.1f}")
    if "move_entropy" in top.columns:
        print(f"  avg move_entropy      : {top['move_entropy'].mean():.3f} bits")

    return top


def analyze_familiarity_vs_error(
    nodes: pl.DataFrame,
    output_dir: Path,
) -> None:
    """Correlation between familiarity (distinct_matches) and avg_error."""
    section("Analysis 1b — Familiarity vs Error")

    df = nodes.filter(pl.col("avg_error").is_not_null())
    if df.is_empty():
        print("  No data with avg_error — skipping")
        return

    # Bin by distinct_matches
    bins = [1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000, 999_999]
    labels = ["1", "2", "3", "4-5", "6-10", "11-20", "21-50",
              "51-100", "101-200", "201-500", "501+"]
    df = df.with_columns(
        pl.col("distinct_matches")
        .cut(breaks=[2, 3, 5, 10, 20, 50, 100, 200, 500, 1000],
             labels=labels)
        .alias("familiarity_bin")
    )

    agg = (
        df.group_by("familiarity_bin")
        .agg([
            pl.len().alias("count"),
            pl.col("avg_error").mean().alias("mean_error"),
            pl.col("avg_error").median().alias("median_error"),
            pl.col("distinct_matches").mean().alias("mean_distinct_matches"),
        ])
        .sort("mean_distinct_matches")
    )

    path = output_dir / "crossroads_error_correlation.csv"
    agg.write_csv(path)
    print(f"  Familiarity vs error ({len(agg)} bins) → {path}")
    print(f"\n  {'Bin':<10} {'Count':>8} {'MeanErr':>9} {'MedErr':>9}")
    print("  " + "-"*40)
    for row in agg.iter_rows(named=True):
        print(f"  {str(row['familiarity_bin']):<10} {row['count']:>8,} "
              f"{row['mean_error']:>9.4f} {row['median_error']:>9.4f}")

    # Spearman-like monotonic trend
    try:
        from scipy.stats import spearmanr
        x = df["distinct_matches"].to_numpy()
        y = df["avg_error"].to_numpy()
        rho, pval = spearmanr(x, y)
        print(f"\n  Spearman ρ(familiarity, error) = {rho:.4f}  (p={pval:.2e})")
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Analysis 2 — Degree Distribution
# ---------------------------------------------------------------------------

def analyze_degree_distribution(
    nodes: pl.DataFrame,
    output_dir: Path,
) -> None:
    """In/out degree distributions with power-law indicators."""
    section("Analysis 2 — Degree Distribution")

    if "in_degree" not in nodes.columns or "out_degree" not in nodes.columns:
        print("  in_degree/out_degree not in nodes — skipping")
        return

    in_dist = (
        nodes.group_by("in_degree")
        .agg(pl.len().alias("count"))
        .sort("in_degree")
        .with_columns(pl.lit("in").alias("direction"))
        .rename({"in_degree": "degree"})
    )
    out_dist = (
        nodes.group_by("out_degree")
        .agg(pl.len().alias("count"))
        .sort("out_degree")
        .with_columns(pl.lit("out").alias("direction"))
        .rename({"out_degree": "degree"})
    )

    dist = pl.concat([in_dist, out_dist])
    path = output_dir / "degree_distribution.csv"
    dist.write_csv(path)
    print(f"  Degree distribution → {path}")

    for direction in ["in", "out"]:
        sub = dist.filter(pl.col("direction") == direction)
        max_deg = sub["degree"].max()
        mean_deg = (sub["degree"] * sub["count"]).sum() / sub["count"].sum()
        print(f"  {direction:>3}-degree: max={max_deg:,}  mean={mean_deg:.1f}  "
              f"unique_degrees={len(sub):,}")

    # High-degree nodes (top 10)
    if "in_degree" in nodes.columns:
        print(f"\n  Top-10 in-degree nodes:")
        for row in nodes.sort("in_degree", descending=True).head(10).iter_rows(named=True):
            print(f"    hash={row['position_hash']:>22}  in={row['in_degree']:>4}  "
                  f"matches={row['distinct_matches']:>6,}  err={row.get('avg_error', 0) or 0:.4f}")


# ---------------------------------------------------------------------------
# Analysis 3 — Betweenness Centrality
# ---------------------------------------------------------------------------

def build_subgraph(
    edges_agg: pl.DataFrame,
    max_nodes: int,
    min_freq: int = 1,
) -> nx.DiGraph:
    """Build a NetworkX DiGraph from top-frequency edges."""
    filtered = edges_agg.filter(pl.col("frequency") >= min_freq)
    # Restrict to edges between top-degree nodes
    node_freq = (
        pl.concat([
            filtered.select(pl.col("from_hash").alias("h")),
            filtered.select(pl.col("to_hash").alias("h")),
        ])
        .group_by("h").agg(pl.len().alias("n"))
        .sort("n", descending=True)
        .head(max_nodes)
    )
    top_hashes = set(node_freq["h"].to_list())

    G = nx.DiGraph()
    for row in filtered.iter_rows(named=True):
        fh, th = row["from_hash"], row["to_hash"]
        if fh in top_hashes and th in top_hashes:
            G.add_edge(fh, th, weight=row["frequency"], avg_error=row["avg_error"] or 0.0)
    return G


def analyze_betweenness(
    edges_agg: pl.DataFrame,
    nodes: pl.DataFrame,
    output_dir: Path,
) -> None:
    """Approximate betweenness centrality on high-frequency subgraph."""
    section("Analysis 3 — Betweenness Centrality")

    t0 = time.time()
    # Build subgraph with edges that have frequency >= 5
    min_freq = max(1, edges_agg["frequency"].quantile(0.80) or 1)
    G = build_subgraph(edges_agg, max_nodes=CENTRALITY_NODES, min_freq=int(min_freq))
    print(f"  Subgraph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges "
          f"(min_freq={int(min_freq)}, built in {time.time()-t0:.1f}s)")

    if G.number_of_nodes() < 3:
        print("  Subgraph too small — skipping betweenness")
        return

    # Connected components
    n_wcc = nx.number_weakly_connected_components(G)
    n_scc = nx.number_strongly_connected_components(G)
    print(f"  Weakly connected components:  {n_wcc:,}")
    print(f"  Strongly connected components: {n_scc:,}")

    # Approximate betweenness
    k = min(CENTRALITY_K, G.number_of_nodes())
    print(f"  Computing approximate betweenness (k={k})...")
    t1 = time.time()
    bc = nx.betweenness_centrality(G, k=k, normalized=True, weight="weight", seed=42)
    print(f"  Done in {time.time()-t1:.1f}s")

    bc_df = pl.DataFrame({
        "position_hash": list(bc.keys()),
        "betweenness": list(bc.values()),
    }).sort("betweenness", descending=True)

    # Join with node metrics
    bc_df = bc_df.join(
        nodes.select(["position_hash", "distinct_matches", "in_degree",
                      "out_degree", "avg_error", "move_entropy"]),
        on="position_hash", how="left",
    )

    path = output_dir / "betweenness_centrality.csv"
    bc_df.head(50).write_csv(path)
    print(f"  Top 50 by betweenness → {path}")

    print(f"\n  Top-10 by betweenness:")
    print(f"  {'hash':>22}  {'bc':>8}  {'matches':>7}  {'in°':>4}  {'out°':>5}  {'err':>6}")
    for row in bc_df.head(10).iter_rows(named=True):
        print(f"  {row['position_hash']:>22}  {row['betweenness']:>8.5f}  "
              f"{row.get('distinct_matches', 0) or 0:>7,}  "
              f"{row.get('in_degree', 0) or 0:>4}  "
              f"{row.get('out_degree', 0) or 0:>5}  "
              f"{row.get('avg_error', 0) or 0:>6.4f}")


# ---------------------------------------------------------------------------
# Analysis 4 — Louvain Communities
# ---------------------------------------------------------------------------

def analyze_communities(
    edges_agg: pl.DataFrame,
    nodes: pl.DataFrame,
    clusters: pl.DataFrame | None,
    hashes: pl.DataFrame | None,
    output_dir: Path,
) -> None:
    """Louvain community detection + comparison with S1.3 clusters."""
    section("Analysis 4 — Louvain Communities")

    try:
        import community as community_louvain
    except ImportError:
        print("  python-louvain not available — skipping")
        return

    # Build undirected graph on top-frequency edges
    min_freq = max(1, edges_agg["frequency"].quantile(0.85) or 1)
    G_dir = build_subgraph(edges_agg, max_nodes=CENTRALITY_NODES, min_freq=int(min_freq))
    G = G_dir.to_undirected()
    print(f"  Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    if G.number_of_nodes() < 4:
        print("  Graph too small — skipping Louvain")
        return

    t0 = time.time()
    partition = community_louvain.best_partition(G, weight="weight", random_state=42)
    n_communities = len(set(partition.values()))
    print(f"  Louvain: {n_communities} communities ({time.time()-t0:.1f}s)")

    # Community stats
    comm_df = pl.DataFrame({
        "position_hash": list(partition.keys()),
        "community": list(partition.values()),
    })

    comm_stats = (
        comm_df.join(
            nodes.select(["position_hash", "distinct_matches",
                          "avg_error", "move_entropy", "occurrence_count"]),
            on="position_hash", how="left",
        )
        .group_by("community")
        .agg([
            pl.len().alias("size"),
            pl.col("distinct_matches").mean().alias("mean_distinct_matches"),
            pl.col("avg_error").mean().alias("mean_error"),
            pl.col("move_entropy").mean().alias("mean_entropy"),
            pl.col("occurrence_count").sum().alias("total_occurrences"),
        ])
        .sort("size", descending=True)
    )

    path = output_dir / "louvain_communities.csv"
    comm_stats.write_csv(path)
    print(f"  Community stats ({n_communities} communities) → {path}")
    print(f"\n  {'Comm':>5}  {'Size':>6}  {'TotalOcc':>10}  {'MeanErr':>9}  {'MeanEntropy':>12}")
    print("  " + "-"*50)
    for row in comm_stats.head(15).iter_rows(named=True):
        print(f"  {row['community']:>5}  {row['size']:>6,}  "
              f"{int(row['total_occurrences'] or 0):>10,}  "
              f"{row['mean_error'] or 0:>9.4f}  {row['mean_entropy'] or 0:>12.3f}")

    # Cross-table: community vs S1.3 cluster
    if clusters is not None and hashes is not None and "position_id" in hashes.columns:
        hc = (
            hashes.select(["position_hash", "position_id"])
            .join(clusters.select(["position_id", "cluster"]), on="position_id", how="left")
            .drop_nulls("cluster")
        )
        cross = (
            comm_df
            .join(hc.group_by("position_hash").agg(
                pl.col("cluster").mode().first().alias("s13_cluster")
            ), on="position_hash", how="left")
            .drop_nulls("s13_cluster")
            .group_by(["community", "s13_cluster"])
            .agg(pl.len().alias("count"))
            .sort(["community", "count"], descending=[False, True])
        )
        xp = output_dir / "community_vs_cluster.csv"
        cross.write_csv(xp)
        print(f"\n  Community vs S1.3 cluster cross-table → {xp}")


# ---------------------------------------------------------------------------
# Analysis 5 — Frequent Paths
# ---------------------------------------------------------------------------

def analyze_frequent_paths(
    trajectories: pl.DataFrame,
    output_dir: Path,
    max_trajectories: int = 50_000,
) -> None:
    """Extract most frequent n-gram (3-5 move) paths from trajectories."""
    section("Analysis 5 — Frequent Paths")

    if trajectories.is_empty():
        print("  No trajectory data — skipping")
        return

    if len(trajectories) > max_trajectories:
        trajectories = trajectories.sample(n=max_trajectories, seed=42)
    print(f"  Analysing {len(trajectories):,} trajectories ...")

    counts: dict[int, Counter] = {3: Counter(), 4: Counter(), 5: Counter()}
    t0 = time.time()

    for row in trajectories.iter_rows(named=True):
        traj = row.get("trajectory") or []
        if not traj or not isinstance(traj, list):
            continue
        for n in (3, 4, 5):
            for i in range(len(traj) - n + 1):
                ngram = tuple(traj[i: i + n])
                counts[n][ngram] += 1

    results = []
    for n, ctr in counts.items():
        for path_tuple, freq in ctr.most_common(TOP_PATHS):
            results.append({
                "path_length": n,
                "frequency": freq,
                "path": "→".join(str(h) for h in path_tuple),
                "start_hash": path_tuple[0],
                "end_hash": path_tuple[-1],
            })
    print(f"  Path counting done ({time.time()-t0:.1f}s)")

    paths_df = pl.DataFrame(results).sort(["path_length", "frequency"], descending=[False, True])
    path = output_dir / "frequent_paths.csv"
    paths_df.write_csv(path)
    print(f"  Top-{TOP_PATHS} paths per length → {path}")

    for n in (3, 4, 5):
        sub = paths_df.filter(pl.col("path_length") == n)
        if not sub.is_empty():
            top_freq = sub["frequency"].max()
            print(f"  n={n}: top frequency = {top_freq:,}  "
                  f"(total distinct n-grams evaluated)")


# ---------------------------------------------------------------------------
# Analysis 6 — Highway vs Trail Classification
# ---------------------------------------------------------------------------

def analyze_path_categories(
    edges_agg: pl.DataFrame,
    output_dir: Path,
) -> None:
    """Classify edges as highways (high-freq) or trails (low-freq)."""
    section("Analysis 6 — Highway vs Trail")

    total = len(edges_agg)
    highway = edges_agg.filter(pl.col("frequency") >= HIGHWAY_MIN_FREQ)
    trail = edges_agg.filter(pl.col("frequency") < HIGHWAY_MIN_FREQ)

    # Frequency bins
    bins = [1, 2, 3, 5, 10, 20, 50, 100, 500, 999_999]
    labels = ["1", "2", "3", "4-5", "6-10", "11-20", "21-50", "51-100", "101+"]
    freq_dist = (
        edges_agg
        .with_columns(
            pl.col("frequency")
            .cut(breaks=[2, 3, 5, 10, 20, 50, 100, 500],
                 labels=labels)
            .alias("freq_bin")
        )
        .group_by("freq_bin")
        .agg([
            pl.len().alias("edge_count"),
            pl.col("frequency").sum().alias("total_traversals"),
            pl.col("avg_error").mean().alias("mean_error"),
        ])
        .sort("total_traversals", descending=True)
    )
    path = output_dir / "path_categories.csv"
    freq_dist.write_csv(path)
    print(f"  Edge frequency distribution → {path}")

    hw_pct = len(highway) / max(total, 1) * 100
    ht_traversal = highway["frequency"].sum() if not highway.is_empty() else 0
    total_traversal = edges_agg["frequency"].sum()
    print(f"  Total edges: {total:,}")
    print(f"  Highways (freq≥{HIGHWAY_MIN_FREQ}): {len(highway):,} "
          f"({hw_pct:.1f}%) covering "
          f"{ht_traversal/max(total_traversal,1)*100:.1f}% of traversals")
    print(f"  Trails  (freq<{HIGHWAY_MIN_FREQ}): {len(trail):,} "
          f"({100-hw_pct:.1f}%)")
    if not highway.is_empty() and "avg_error" in highway.columns:
        print(f"  Highway avg error: {highway['avg_error'].mean():.4f}  "
              f"Trail avg error: {trail['avg_error'].mean():.4f}")


# ---------------------------------------------------------------------------
# Analysis 7 — Divergence from Crossroads
# ---------------------------------------------------------------------------

def analyze_divergence(
    trajectories: pl.DataFrame,
    top_crossroads: pl.DataFrame,
    clusters: pl.DataFrame | None,
    hashes: pl.DataFrame | None,
    output_dir: Path,
    horizons: tuple[int, ...] = (3, 5, 10),
    max_trajectories: int = 50_000,
    top_n: int = 20,
) -> None:
    """
    For top crossroads, measure how quickly trajectories diverge.

    For each crossroad hash C:
      - Find all trajectories containing C
      - For each, record the hash at position idx+H (H = horizon)
      - Divergence rate = distinct successor hashes / total
      - Cluster divergence = fraction of trajectories still in same cluster
    """
    section("Analysis 7 — Divergence from Crossroads")

    if trajectories.is_empty():
        print("  No trajectory data — skipping")
        return

    if len(trajectories) > max_trajectories:
        trajectories = trajectories.sample(n=max_trajectories, seed=42)

    # Build hash → cluster map if available
    hash_to_cluster: dict[int, int] = {}
    if clusters is not None and hashes is not None and "position_id" in hashes.columns:
        hc = (
            hashes.select(["position_hash", "position_id"])
            .join(clusters.select(["position_id", "cluster"]), on="position_id", how="left")
            .drop_nulls("cluster")
        )
        dominant = (
            hc.group_by("position_hash")
            .agg(pl.col("cluster").mode().first().alias("cluster"))
        )
        for row in dominant.iter_rows(named=True):
            hash_to_cluster[row["position_hash"]] = row["cluster"]

    # Take top N crossroads for divergence analysis
    crossroad_hashes = top_crossroads.head(top_n)["position_hash"].to_list()
    crossroad_set = set(crossroad_hashes)

    # Build index: hash → list of (trajectory_list, position_in_trajectory)
    print(f"  Indexing {len(trajectories):,} trajectories for {len(crossroad_hashes)} crossroads ...")
    t0 = time.time()

    # For each trajectory, find positions matching any crossroad
    # { crossroad_hash: [(trajectory_list, idx), ...] }
    cr_occurrences: dict[int, list[tuple[list, int]]] = defaultdict(list)
    for row in trajectories.iter_rows(named=True):
        traj = row.get("trajectory") or []
        if not traj or not isinstance(traj, list):
            continue
        for idx, h in enumerate(traj):
            if h in crossroad_set:
                cr_occurrences[h].append((traj, idx))

    print(f"  Index built ({time.time()-t0:.1f}s)")

    results = []
    for cr_hash in crossroad_hashes:
        occurrences = cr_occurrences.get(cr_hash, [])
        n_occ = len(occurrences)
        if n_occ < 2:
            continue

        cr_cluster = hash_to_cluster.get(cr_hash)
        row_result: dict = {
            "crossroad_hash": cr_hash,
            "n_occurrences": n_occ,
            "crossroad_cluster": cr_cluster,
        }

        for H in horizons:
            successors = []
            same_cluster = 0
            for traj, idx in occurrences:
                future_idx = idx + H
                if future_idx < len(traj):
                    succ_hash = traj[future_idx]
                    successors.append(succ_hash)
                    if cr_cluster is not None:
                        succ_cluster = hash_to_cluster.get(succ_hash)
                        if succ_cluster == cr_cluster:
                            same_cluster += 1

            n_succ = len(successors)
            if n_succ > 0:
                n_distinct = len(set(successors))
                div_rate = n_distinct / n_succ
                cluster_retention = same_cluster / n_succ if cr_cluster is not None else None
                row_result[f"h{H}_n_games"] = n_succ
                row_result[f"h{H}_distinct_successors"] = n_distinct
                row_result[f"h{H}_divergence_rate"] = round(div_rate, 4)
                if cluster_retention is not None:
                    row_result[f"h{H}_cluster_retention"] = round(cluster_retention, 4)
            else:
                row_result[f"h{H}_n_games"] = 0
                row_result[f"h{H}_distinct_successors"] = 0
                row_result[f"h{H}_divergence_rate"] = None

        results.append(row_result)

    if not results:
        print("  No divergence data computed")
        return

    div_df = pl.DataFrame(results)
    path = output_dir / "divergence_analysis.csv"
    div_df.write_csv(path)
    print(f"  Divergence analysis ({len(div_df)} crossroads, "
          f"horizons={horizons}) → {path}")

    # Show summary
    if f"h{horizons[1]}_divergence_rate" in div_df.columns:
        h = horizons[1]
        valid = div_df.filter(pl.col(f"h{h}_divergence_rate").is_not_null())
        if not valid.is_empty():
            print(f"\n  At horizon H={h}:")
            print(f"    mean divergence rate: "
                  f"{valid[f'h{h}_divergence_rate'].mean():.3f}")
            if f"h{h}_cluster_retention" in valid.columns:
                cr = valid[f"h{h}_cluster_retention"].drop_nulls()
                if not cr.is_empty():
                    print(f"    mean cluster retention: {cr.mean():.3f}")


# ---------------------------------------------------------------------------
# Analysis 8 — Convergence Attractors
# ---------------------------------------------------------------------------

def analyze_attractors(
    nodes: pl.DataFrame,
    edges_agg: pl.DataFrame,
    clusters: pl.DataFrame | None,
    hashes: pl.DataFrame | None,
    output_dir: Path,
) -> None:
    """Identify convergence attractors: positions that many paths lead to."""
    section("Analysis 8 — Convergence Attractors")

    if "in_degree" not in nodes.columns:
        print("  in_degree not in nodes — skipping")
        return

    # Attractor candidates: high in_degree relative to out_degree
    # (many paths enter, few leave → "sink" positions)
    # Also: high occurrence from diverse matches
    attractors = (
        nodes.filter(pl.col("distinct_matches") >= 3)
        .with_columns(
            (pl.col("in_degree") / pl.col("out_degree").clip(lower_bound=1))
            .alias("in_out_ratio")
        )
        .sort("in_out_ratio", descending=True)
        .head(100)
    )

    # Enrich with cluster labels
    if hashes is not None and clusters is not None and "position_id" in hashes.columns:
        hc = (
            hashes.select(["position_hash", "position_id"])
            .join(clusters.select(["position_id", "cluster"]), on="position_id", how="left")
            .drop_nulls("cluster")
        )
        dominant = (
            hc.group_by("position_hash")
            .agg(pl.col("cluster").mode().first().alias("dominant_cluster"))
        )
        attractors = attractors.join(dominant, on="position_hash", how="left")

    path = output_dir / "convergence_attractors.csv"
    attractors.write_csv(path)
    print(f"  Top {len(attractors)} convergence attractors → {path}")

    print(f"\n  {'hash':>22}  {'in°':>4}  {'out°':>4}  {'ratio':>6}  "
          f"{'matches':>7}  {'err':>6}")
    for row in attractors.head(10).iter_rows(named=True):
        print(f"  {row['position_hash']:>22}  {row.get('in_degree') or 0:>4}  "
              f"{row.get('out_degree') or 0:>4}  "
              f"{row.get('in_out_ratio') or 0:>6.2f}  "
              f"{row.get('distinct_matches') or 0:>7,}  "
              f"{row.get('avg_error') or 0:>6.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global HIGHWAY_MIN_FREQ, CENTRALITY_NODES  # overridable via CLI

    ap = argparse.ArgumentParser(description="S1.8 — Convergence & Graph Topology")
    ap.add_argument("--graph-dir", default="data/parquet",
                    help="Directory containing S0.7 graph outputs "
                         "(graph_nodes.parquet, graph_edges_agg.parquet, "
                         "graph_trajectories.parquet)")
    ap.add_argument("--parquet-dir", default="data/parquet",
                    help="Base parquet directory (contains position_hashes.parquet)")
    ap.add_argument("--clusters-dir", default="data/clusters",
                    help="S1.3 cluster output directory "
                         "(clusters_checker.parquet, optional)")
    ap.add_argument("--output", default="data/graph_topology",
                    help="Output directory for CSV files (default: data/graph_topology)")
    ap.add_argument("--max-traj", type=int, default=50_000,
                    help="Max trajectories to sample for path analysis (default: 50000)")
    ap.add_argument("--centrality-nodes", type=int, default=CENTRALITY_NODES,
                    help="Max nodes in betweenness subgraph (default: 5000)")
    ap.add_argument("--highway-freq", type=int, default=HIGHWAY_MIN_FREQ,
                    help="Min frequency to classify edge as highway (default: 10)")
    args = ap.parse_args()

    HIGHWAY_MIN_FREQ = args.highway_freq
    CENTRALITY_NODES = args.centrality_nodes

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  S1.8 — Convergence & Graph Topology")
    print("=" * 60)
    print(f"  graph-dir   : {args.graph_dir}")
    print(f"  parquet-dir : {args.parquet_dir}")
    print(f"  clusters-dir: {args.clusters_dir}")
    print(f"  output      : {output_dir}")

    graph_dir = Path(args.graph_dir)
    parquet_dir = Path(args.parquet_dir)
    clusters_dir = Path(args.clusters_dir)

    # -----------------------------------------------------------------------
    # Load inputs
    # -----------------------------------------------------------------------
    section("Loading inputs")

    nodes = load_parquet_optional(graph_dir / "graph_nodes.parquet")
    if nodes is None or nodes.is_empty():
        sys.exit("ERROR: graph_nodes.parquet not found or empty — run S0.7 first")

    edges_agg = load_parquet_optional(graph_dir / "graph_edges_agg.parquet")
    if edges_agg is None or edges_agg.is_empty():
        sys.exit("ERROR: graph_edges_agg.parquet not found or empty — run S0.7 first")

    trajectories = load_parquet_optional(graph_dir / "graph_trajectories.parquet")
    hashes = load_parquet_optional(
        parquet_dir / "position_hashes.parquet",
        columns=["position_hash", "position_id", "move_number"],
    )
    clusters = load_parquet_optional(
        clusters_dir / "clusters_checker.parquet",
        columns=["position_id", "cluster"],
    )
    if clusters is None:
        print("  [info] S1.3 cluster labels not found — community/cluster comparison disabled")

    print(f"\n  Nodes:        {len(nodes):,}")
    print(f"  Edges (agg):  {len(edges_agg):,}")
    print(f"  Trajectories: {len(trajectories) if trajectories is not None else 0:,}")
    print(f"  Hashes:       {len(hashes) if hashes is not None else 0:,}")
    print(f"  Clusters:     {len(clusters) if clusters is not None else 0:,}")

    # -----------------------------------------------------------------------
    # Run analyses
    # -----------------------------------------------------------------------
    t_start = time.time()

    top_crossroads = analyze_crossroads(nodes, hashes, clusters, output_dir)
    analyze_familiarity_vs_error(nodes, output_dir)
    analyze_degree_distribution(nodes, output_dir)
    analyze_betweenness(edges_agg, nodes, output_dir)
    analyze_communities(edges_agg, nodes, clusters, hashes, output_dir)

    if trajectories is not None and not trajectories.is_empty():
        analyze_frequent_paths(trajectories, output_dir, max_trajectories=args.max_traj)
    else:
        print("  [skip] No trajectories — skipping path analyses")

    analyze_path_categories(edges_agg, output_dir)

    if trajectories is not None and not trajectories.is_empty():
        analyze_divergence(
            trajectories, top_crossroads, clusters, hashes,
            output_dir, max_trajectories=args.max_traj,
        )
    analyze_attractors(nodes, edges_agg, clusters, hashes, output_dir)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  S1.8 — Complete")
    print("=" * 60)
    print(f"  Total time: {time.time()-t_start:.1f}s")
    print(f"  Outputs in: {output_dir}/")
    print()
    for csv_file in sorted(output_dir.glob("*.csv")):
        rows = sum(1 for _ in open(csv_file)) - 1
        print(f"    {csv_file.name:<45} {rows:>6} rows")
    print("=" * 60)


if __name__ == "__main__":
    main()
