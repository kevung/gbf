#!/usr/bin/env python3
"""Cluster & Statistics Visualization — complements theme-based views.

Generates:
  1. Cluster map (UMAP scatter colored by cluster)
  2. Cluster profile radar charts
  3. Error distribution histograms (checker + cube)
  4. Score distribution heatmap
  5. Match phase pie chart
  6. Correlation matrix of key features
  7. Player ranking bar chart (top 30)

Usage::

    python scripts/visualize_stats.py \\
        --enriched data/parquet/positions_enriched \\
        --clusters data/clusters \\
        --profiles data/player_profiles \\
        --stats data/stats \\
        --output viz/stats \\
        --sample 200000
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

import polars as pl

PHASE_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}
PHASE_LABELS = {0: "Contact", 1: "Race", 2: "Bearoff"}

CLUSTER_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]


def sample_parquet_dir(path: Path, n: int, columns: list[str] | None = None) -> pl.DataFrame:
    files = sorted(path.glob("part-*.parquet"))
    if not files:
        sys.exit(f"No parquet files in {path}")
    schema_cols = pl.read_parquet(files[0], n_rows=1).columns
    cols = [c for c in columns if c in schema_cols] if columns else None
    frames, rows = [], 0
    for f in files:
        df = pl.read_parquet(f, columns=cols)
        frames.append(df)
        rows += len(df)
        if rows >= n * 2:
            break
    combined = pl.concat(frames)
    if len(combined) > n:
        combined = combined.sample(n, seed=42)
    return combined


def save(fig, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved {path}")


# ── Plot 1: Cluster UMAP map ────────────────────────────────────────

def plot_cluster_map(clusters_path: Path, out_dir: Path, label: str) -> None:
    df = pl.read_parquet(clusters_path)
    if len(df) > 50000:
        df = df.sample(50000, seed=42)

    fig, ax = plt.subplots(figsize=(12, 10))
    cluster_ids = sorted(df["cluster"].unique().to_list())

    for cid in cluster_ids:
        sub = df.filter(pl.col("cluster") == cid)
        color = "#cccccc" if cid == -1 else CLUSTER_PALETTE[cid % len(CLUSTER_PALETTE)]
        lbl = "Noise" if cid == -1 else f"C{cid}"
        ax.scatter(sub["umap_x"].to_numpy(), sub["umap_y"].to_numpy(),
                   c=color, s=2, alpha=0.3, label=lbl if cid <= 15 or cid == -1 else None,
                   rasterized=True)

    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title(f"Position Clusters ({label}) — {len(cluster_ids)} clusters")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=7,
              markerscale=4, ncol=2)
    fig.tight_layout()
    save(fig, out_dir, f"cluster_map_{label}")


# ── Plot 2: Cluster profiles ────────────────────────────────────────

def plot_cluster_profiles(clusters_dir: Path, out_dir: Path) -> None:
    profile_file = clusters_dir / "cluster_profiles_checker.csv"
    if not profile_file.exists():
        print("  (no cluster_profiles_checker.csv, skipping)")
        return

    df = pl.read_csv(profile_file)
    if "cluster" not in df.columns:
        return

    # Get feature columns (exclude cluster and count).
    feat_cols = [c for c in df.columns if c not in ("cluster", "count", "label", "name")]
    if len(feat_cols) == 0:
        return

    # Normalize features to [0, 1] for radar.
    norms = {}
    for c in feat_cols:
        vals = df[c].to_numpy().astype(float)
        mn, mx = vals.min(), vals.max()
        norms[c] = (vals - mn) / (mx - mn + 1e-10)

    clusters = df["cluster"].to_list()
    n_clusters = min(12, len(clusters))  # Top 12.

    angles = np.linspace(0, 2 * np.pi, len(feat_cols), endpoint=False).tolist()
    angles += angles[:1]  # Close the loop.

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    for i in range(n_clusters):
        vals = [norms[c][i] for c in feat_cols] + [norms[feat_cols[0]][i]]
        color = CLUSTER_PALETTE[i % len(CLUSTER_PALETTE)]
        ax.plot(angles, vals, color=color, linewidth=1.5, alpha=0.7,
                label=f"C{clusters[i]}")
        ax.fill(angles, vals, color=color, alpha=0.1)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([c.replace("_", "\n") for c in feat_cols], fontsize=6)
    ax.set_title("Cluster Feature Profiles (top 12)", pad=20)
    ax.legend(bbox_to_anchor=(1.15, 1), fontsize=7)
    fig.tight_layout()
    save(fig, out_dir, "cluster_profiles_radar")


# ── Plot 3: Error distributions ──────────────────────────────────────

def plot_error_distributions(df: pl.DataFrame, out_dir: Path) -> None:
    if "move_played_error" not in df.columns:
        return

    errors = df["move_played_error"].drop_nulls().to_numpy()
    # Clip extreme values for display.
    errors_clipped = np.clip(errors, 0, 0.5)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Overall histogram.
    axes[0].hist(errors_clipped, bins=100, color="#4363d8", alpha=0.7,
                 edgecolor="white", linewidth=0.3)
    axes[0].set_xlabel("Equity loss")
    axes[0].set_ylabel("Count")
    axes[0].set_title(f"Error Distribution (n={len(errors):,})")
    axes[0].axvline(np.median(errors), color="red", linestyle="--",
                    label=f"Median: {np.median(errors):.4f}")
    axes[0].axvline(np.mean(errors), color="orange", linestyle="--",
                    label=f"Mean: {np.mean(errors):.4f}")
    axes[0].legend(fontsize=8)

    # By match phase.
    if "match_phase" in df.columns:
        for phase, color in PHASE_COLORS.items():
            sub = df.filter(pl.col("match_phase") == phase)["move_played_error"].drop_nulls().to_numpy()
            if len(sub) > 0:
                axes[1].hist(np.clip(sub, 0, 0.3), bins=80, color=color, alpha=0.5,
                             density=True, label=PHASE_LABELS[phase])
        axes[1].set_xlabel("Equity loss")
        axes[1].set_ylabel("Density")
        axes[1].set_title("Error by Match Phase")
        axes[1].legend()

    # By decision type.
    if "decision_type" in df.columns:
        for dt, color in [("checker", "#4363d8"), ("cube", "#e74c3c")]:
            sub = df.filter(pl.col("decision_type") == dt)["move_played_error"].drop_nulls().to_numpy()
            if len(sub) > 0:
                axes[2].hist(np.clip(sub, 0, 0.3), bins=80, color=color, alpha=0.5,
                             density=True, label=dt.title())
        axes[2].set_xlabel("Equity loss")
        axes[2].set_ylabel("Density")
        axes[2].set_title("Error by Decision Type")
        axes[2].legend()

    fig.tight_layout()
    save(fig, out_dir, "error_distributions")


# ── Plot 4: Score distribution heatmap ───────────────────────────────

def plot_score_heatmap(df: pl.DataFrame, out_dir: Path) -> None:
    if "score_away_p1" not in df.columns or "score_away_p2" not in df.columns:
        return

    sa1 = df["score_away_p1"].to_numpy()
    sa2 = df["score_away_p2"].to_numpy()
    max_score = min(25, max(sa1.max(), sa2.max()))

    grid = np.zeros((max_score + 1, max_score + 1))
    for s1, s2 in zip(sa1, sa2):
        if 0 <= s1 <= max_score and 0 <= s2 <= max_score:
            grid[int(s1), int(s2)] += 1

    grid = grid / grid.sum() * 100  # Percentage.

    fig, ax = plt.subplots(figsize=(10, 9))
    im = ax.imshow(grid, cmap="hot_r", aspect="auto", origin="lower")
    ax.set_xlabel("Score Away P2")
    ax.set_ylabel("Score Away P1")
    ax.set_title("Score Distribution (% of positions)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="%")
    fig.tight_layout()
    save(fig, out_dir, "score_heatmap")


# ── Plot 5: Phase pie chart ─────────────────────────────────────────

def plot_phase_pie(df: pl.DataFrame, out_dir: Path) -> None:
    if "match_phase" not in df.columns:
        return

    counts = df.group_by("match_phase").len().sort("match_phase")
    labels = [PHASE_LABELS.get(r["match_phase"], f"?{r['match_phase']}") for r in counts.iter_rows(named=True)]
    vals = counts["len"].to_list()
    colors = [PHASE_COLORS.get(r["match_phase"], "#999") for r in counts.iter_rows(named=True)]

    fig, ax = plt.subplots(figsize=(7, 7))
    wedges, texts, autotexts = ax.pie(vals, labels=labels, colors=colors,
                                       autopct="%1.1f%%", startangle=140)
    ax.set_title(f"Match Phase Distribution (n={sum(vals):,})")
    save(fig, out_dir, "phase_distribution")


# ── Plot 6: Feature correlation matrix ───────────────────────────────

def plot_correlation(df: pl.DataFrame, out_dir: Path) -> None:
    corr_features = [
        "pip_count_diff", "num_blots_p1", "num_points_made_p1",
        "home_board_points_p1", "longest_prime_p1", "num_checkers_back_p1",
        "eval_win", "move_played_error", "gammon_threat", "gammon_risk",
        "cube_leverage", "outfield_blots_p1", "num_builders_p1",
    ]
    feats = [f for f in corr_features if f in df.columns]
    if len(feats) < 3:
        return

    mat = df.select(feats).to_pandas().corr().values
    labels = [f.replace("_", "\n") for f in feats]

    fig, ax = plt.subplots(figsize=(11, 10))
    im = ax.imshow(mat, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_title("Feature Correlation Matrix")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Pearson r")

    # Annotate values.
    for i in range(len(feats)):
        for j in range(len(feats)):
            color = "white" if abs(mat[i, j]) > 0.5 else "black"
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center",
                    fontsize=6, color=color)

    fig.tight_layout()
    save(fig, out_dir, "correlation_matrix")


# ── Plot 7: Player rankings ─────────────────────────────────────────

def plot_player_rankings(profiles_dir: Path, out_dir: Path) -> None:
    ranking_file = profiles_dir / "player_ranking.csv"
    if not ranking_file.exists():
        print("  (no player_ranking.csv, skipping)")
        return

    df = pl.read_csv(ranking_file)
    # Look for a ranking column.
    rank_col = None
    for c in ["pr", "pr_rating", "performance_rating", "avg_error", "ranking_score"]:
        if c in df.columns:
            rank_col = c
            break
    if rank_col is None:
        print(f"  (no recognized ranking column in {df.columns}, skipping)")
        return

    name_col = None
    for c in ["player", "player_name", "name"]:
        if c in df.columns:
            name_col = c
            break
    if name_col is None:
        return

    # Sort and take top 30.
    df = df.sort(rank_col).head(30)

    fig, ax = plt.subplots(figsize=(10, 8))
    names = df[name_col].to_list()
    vals = df[rank_col].to_numpy()
    colors = plt.cm.RdYlGn_r(np.linspace(0.2, 0.8, len(names)))
    ax.barh(range(len(names)), vals, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel(rank_col.replace("_", " ").title())
    ax.set_title(f"Top 30 Players by {rank_col.replace('_', ' ').title()}")
    ax.invert_yaxis()
    fig.tight_layout()
    save(fig, out_dir, "player_rankings")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster & stats visualization.")
    parser.add_argument("--enriched", required=True)
    parser.add_argument("--clusters", default="data/clusters")
    parser.add_argument("--profiles", default="data/player_profiles")
    parser.add_argument("--stats", default="data/stats")
    parser.add_argument("--output", default="viz/stats")
    parser.add_argument("--sample", type=int, default=200000)
    args = parser.parse_args()

    out_dir = Path(args.output)
    clusters_dir = Path(args.clusters)
    profiles_dir = Path(args.profiles)

    print(f"Loading enriched (sample={args.sample:,}) ...")
    cols = ["position_id", "match_phase", "decision_type",
            "move_played_error", "score_away_p1", "score_away_p2",
            "pip_count_diff", "num_blots_p1", "num_points_made_p1",
            "home_board_points_p1", "longest_prime_p1", "num_checkers_back_p1",
            "eval_win", "gammon_threat", "gammon_risk",
            "cube_leverage", "outfield_blots_p1", "num_builders_p1",
            "eval_equity"]
    df = sample_parquet_dir(Path(args.enriched), args.sample, columns=cols)
    print(f"  {len(df):,} positions")

    print("\n1. Cluster maps ...")
    for label, fname in [("checker", "clusters_checker.parquet"),
                         ("cube", "clusters_cube.parquet")]:
        cp = clusters_dir / fname
        if cp.exists():
            plot_cluster_map(cp, out_dir, label)

    print("2. Cluster profiles ...")
    plot_cluster_profiles(clusters_dir, out_dir)

    print("3. Error distributions ...")
    plot_error_distributions(df, out_dir)

    print("4. Score heatmap ...")
    plot_score_heatmap(df, out_dir)

    print("5. Phase distribution ...")
    plot_phase_pie(df, out_dir)

    print("6. Correlation matrix ...")
    plot_correlation(df, out_dir)

    print("7. Player rankings ...")
    plot_player_rankings(profiles_dir, out_dir)

    print(f"\nDone — saved to {out_dir}/")


if __name__ == "__main__":
    main()
