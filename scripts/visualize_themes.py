#!/usr/bin/env python3
"""Theme Visualization — Overview plots for the 26-theme classification.

Generates:
  1. Theme frequency bar chart
  2. Theme co-occurrence heatmap
  3. Feature distributions by primary theme (box plots)
  4. Theme overlap Upset-style horizontal bar chart
  5. Error distribution per theme (violin-like)
  6. UMAP scatter colored by primary theme (if clusters available)

Usage::

    python scripts/visualize_themes.py \\
        --themes data/parquet/position_themes \\
        --enriched data/parquet/positions_enriched \\
        --clusters data/clusters \\
        --output viz/themes \\
        --sample 200000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.theme_rules import ALL_THEME_COLUMNS


# ── Helpers ──────────────────────────────────────────────────────────

THEME_DISPLAY = {c: c.removeprefix("theme_").replace("_", " ").title()
                 for c in ALL_THEME_COLUMNS}

PHASE_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}
PHASE_LABELS = {0: "Contact", 1: "Race", 2: "Bearoff"}

# A qualitative palette for 26+ themes.
THEME_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    "#e6beff", "#1a55FF", "#aa6e28", "#800080", "#00FF7F", "#FF6347",
    "#708090",
]


def sample_parquet_dir(path: Path, n: int, columns: list[str] | None = None) -> pl.DataFrame:
    """Read and sample a partitioned parquet directory."""
    files = sorted(path.glob("part-*.parquet"))
    if not files:
        sys.exit(f"No parquet files in {path}")
    # Read a subset of files if the sample is smaller than total rows.
    schema_cols = pl.read_parquet(files[0], n_rows=1).columns
    cols = [c for c in columns if c in schema_cols] if columns else None
    frames = []
    rows_so_far = 0
    for f in files:
        df = pl.read_parquet(f, columns=cols)
        frames.append(df)
        rows_so_far += len(df)
        if rows_so_far >= n * 2:
            break
    combined = pl.concat(frames)
    if len(combined) > n:
        combined = combined.sample(n, seed=42)
    return combined


def save(fig: plt.Figure, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved {path}")


# ── Plot 1: Theme frequency bar chart ───────────────────────────────

def plot_theme_frequencies(df: pl.DataFrame, out_dir: Path) -> None:
    """Horizontal bar chart of theme occurrence rate."""
    counts = {}
    for col in ALL_THEME_COLUMNS:
        if col in df.columns:
            counts[THEME_DISPLAY[col]] = df[col].sum()

    names = list(counts.keys())
    vals = list(counts.values())
    total = len(df)
    pcts = [v / total * 100 for v in vals]

    # Sort by frequency.
    order = np.argsort(pcts)
    names = [names[i] for i in order]
    pcts = [pcts[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.barh(range(len(names)), pcts, color="#4363d8", edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("% of positions")
    ax.set_title(f"Theme Frequencies ({total:,} positions)")
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=1))

    # Annotate counts.
    for bar, pct in zip(bars, pcts):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", fontsize=8)

    save(fig, out_dir, "theme_frequencies")


# ── Plot 2: Theme co-occurrence heatmap ─────────────────────────────

def plot_cooccurrence(df: pl.DataFrame, out_dir: Path) -> None:
    """Heatmap of pairwise theme co-occurrence (Jaccard similarity)."""
    cols = [c for c in ALL_THEME_COLUMNS if c in df.columns]
    n = len(cols)
    mat = np.zeros((n, n))

    # Convert to numpy for speed.
    arrays = {c: df[c].to_numpy().astype(bool) for c in cols}

    for i in range(n):
        a = arrays[cols[i]]
        for j in range(i, n):
            b = arrays[cols[j]]
            intersection = np.sum(a & b)
            union = np.sum(a | b)
            jaccard = intersection / union if union > 0 else 0
            mat[i, j] = jaccard
            mat[j, i] = jaccard

    labels = [THEME_DISPLAY[c] for c in cols]
    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(mat, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_title("Theme Co-occurrence (Jaccard Similarity)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Jaccard")

    save(fig, out_dir, "theme_cooccurrence")


# ── Plot 3: Feature box plots by primary theme ──────────────────────

FEATURE_COLS = [
    "pip_count_diff", "num_blots_p1", "num_points_made_p1",
    "home_board_points_p1", "longest_prime_p1", "num_checkers_back_p1",
    "eval_win", "move_played_error", "gammon_threat", "gammon_risk",
]


def plot_feature_distributions(df_themes: pl.DataFrame, df_enr: pl.DataFrame,
                                out_dir: Path) -> None:
    """Box plots of key features grouped by primary theme."""
    # Merge on position_id
    merged = df_themes.select(["position_id", "primary_theme"]).join(
        df_enr.select(["position_id"] + [c for c in FEATURE_COLS if c in df_enr.columns]),
        on="position_id",
        how="inner",
    )

    # Limit to top 12 most frequent themes.
    theme_counts = merged.group_by("primary_theme").len().sort("len", descending=True)
    top_themes = theme_counts.head(12)["primary_theme"].to_list()
    merged = merged.filter(pl.col("primary_theme").is_in(top_themes))

    feats = [c for c in FEATURE_COLS if c in merged.columns]
    n_feats = len(feats)
    ncols = 2
    nrows = (n_feats + 1) // 2

    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 4 * nrows))
    axes = axes.flatten()

    for idx, feat in enumerate(feats):
        ax = axes[idx]
        data_by_theme = []
        labels = []
        for theme in top_themes:
            subset = merged.filter(pl.col("primary_theme") == theme)
            vals = subset[feat].drop_nulls().to_numpy()
            if len(vals) > 0:
                data_by_theme.append(vals)
                labels.append(theme.replace("_", " ").title()[:15])

        if data_by_theme:
            bp = ax.boxplot(data_by_theme, vert=True, patch_artist=True, showfliers=False)
            for patch, color in zip(bp["boxes"], THEME_PALETTE[:len(labels)]):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
            ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_title(feat.replace("_", " ").title(), fontsize=10)
        ax.grid(axis="y", alpha=0.3)

    for idx in range(n_feats, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("Feature Distributions by Primary Theme (top 12)", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, out_dir, "feature_distributions_by_theme")


# ── Plot 4: Error distribution per theme ─────────────────────────────

def plot_error_by_theme(df_themes: pl.DataFrame, df_enr: pl.DataFrame,
                        out_dir: Path) -> None:
    """Mean error per theme, sorted."""
    merged = df_themes.select(["position_id"] + [c for c in ALL_THEME_COLUMNS if c in df_themes.columns]).join(
        df_enr.select(["position_id", "move_played_error"]),
        on="position_id",
        how="inner",
    )

    theme_errors = {}
    for col in ALL_THEME_COLUMNS:
        if col not in merged.columns:
            continue
        subset = merged.filter(pl.col(col))
        if len(subset) > 0:
            mean_err = subset["move_played_error"].mean()
            median_err = subset["move_played_error"].median()
            theme_errors[THEME_DISPLAY[col]] = (mean_err, median_err)

    if not theme_errors:
        return

    names = list(theme_errors.keys())
    means = [theme_errors[n][0] for n in names]
    medians = [theme_errors[n][1] for n in names]

    order = np.argsort(means)[::-1]
    names = [names[i] for i in order]
    means = [means[i] for i in order]
    medians = [medians[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, 8))
    y = range(len(names))
    ax.barh(y, means, color="#e74c3c", alpha=0.7, label="Mean error")
    ax.barh(y, medians, color="#3498db", alpha=0.7, label="Median error")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Equity loss")
    ax.set_title("Move Error by Theme")
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.3)

    save(fig, out_dir, "error_by_theme")


# ── Plot 5: Theme count histogram ────────────────────────────────────

def plot_theme_count_histogram(df: pl.DataFrame, out_dir: Path) -> None:
    """How many themes does a typical position match?"""
    if "theme_count" not in df.columns:
        return
    counts = df["theme_count"].to_numpy()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(counts, bins=range(0, int(counts.max()) + 2), color="#4363d8",
            edgecolor="white", alpha=0.8, density=True)
    ax.set_xlabel("Number of themes matched")
    ax.set_ylabel("Fraction of positions")
    ax.set_title("Theme Overlap Distribution")
    ax.axvline(np.median(counts), color="red", linestyle="--", label=f"Median: {np.median(counts):.1f}")
    ax.legend()
    save(fig, out_dir, "theme_count_histogram")


# ── Plot 6: UMAP scatter by primary theme ────────────────────────────

def plot_umap_by_theme(df_themes: pl.DataFrame, df_clusters: pl.DataFrame,
                       out_dir: Path) -> None:
    """2D scatter of UMAP projection colored by primary theme."""
    merged = df_themes.select(["position_id", "primary_theme"]).join(
        df_clusters.select(["position_id", "umap_x", "umap_y"]),
        on="position_id",
        how="inner",
    )

    if len(merged) == 0:
        print("  (no UMAP/theme overlap, skipping)")
        return

    # Limit to 50K for readability.
    if len(merged) > 50000:
        merged = merged.sample(50000, seed=42)

    themes = merged["primary_theme"].unique().sort().to_list()
    color_map = {t: THEME_PALETTE[i % len(THEME_PALETTE)] for i, t in enumerate(themes)}

    fig, ax = plt.subplots(figsize=(14, 10))
    for theme in themes:
        subset = merged.filter(pl.col("primary_theme") == theme)
        x = subset["umap_x"].to_numpy()
        y = subset["umap_y"].to_numpy()
        label = theme.replace("_", " ").title()
        ax.scatter(x, y, c=color_map[theme], s=2, alpha=0.4, label=label, rasterized=True)

    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("Position UMAP — Colored by Primary Theme")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=7,
              markerscale=4, ncol=2)
    fig.tight_layout()
    save(fig, out_dir, "umap_by_theme")


# ── Plot 7: Phase × Theme stacked bar ───────────────────────────────

def plot_phase_theme_stacked(df_themes: pl.DataFrame, df_enr: pl.DataFrame,
                              out_dir: Path) -> None:
    """Stacked bar showing match-phase breakdown within each theme."""
    merged = df_themes.select(["position_id", "primary_theme"]).join(
        df_enr.select(["position_id", "match_phase"]),
        on="position_id",
        how="inner",
    )

    theme_counts = merged.group_by("primary_theme").len().sort("len", descending=True)
    top12 = theme_counts.head(12)["primary_theme"].to_list()
    merged = merged.filter(pl.col("primary_theme").is_in(top12))

    cross = merged.group_by(["primary_theme", "match_phase"]).len()
    themes = []
    phase_data = {0: [], 1: [], 2: []}

    for theme in top12:
        themes.append(theme.replace("_", " ").title()[:18])
        total = cross.filter(pl.col("primary_theme") == theme)["len"].sum()
        for phase in [0, 1, 2]:
            cnt = cross.filter(
                (pl.col("primary_theme") == theme) & (pl.col("match_phase") == phase)
            )["len"].sum()
            phase_data[phase].append(cnt / total * 100 if total > 0 else 0)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(themes))
    bottom = np.zeros(len(themes))
    for phase in [0, 1, 2]:
        vals = np.array(phase_data[phase])
        ax.bar(x, vals, bottom=bottom, color=PHASE_COLORS[phase],
               label=PHASE_LABELS[phase], edgecolor="white", linewidth=0.5)
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(themes, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("% of positions")
    ax.set_title("Match Phase Breakdown by Theme")
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    fig.tight_layout()
    save(fig, out_dir, "phase_by_theme")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Theme visualization suite.")
    parser.add_argument("--themes", required=True, help="position_themes parquet dir")
    parser.add_argument("--enriched", required=True, help="positions_enriched parquet dir")
    parser.add_argument("--clusters", default=None, help="clusters dir (optional)")
    parser.add_argument("--output", default="viz/themes", help="output directory")
    parser.add_argument("--sample", type=int, default=200000, help="max positions to sample")
    args = parser.parse_args()

    themes_dir = Path(args.themes)
    enriched_dir = Path(args.enriched)
    out_dir = Path(args.output)
    n = args.sample

    print(f"Loading themes (sample={n:,}) ...")
    theme_cols = ["position_id", "primary_theme", "theme_count"] + ALL_THEME_COLUMNS
    df_themes = sample_parquet_dir(themes_dir, n, columns=theme_cols)
    print(f"  {len(df_themes):,} theme rows loaded")

    print("Loading enriched positions ...")
    enr_cols = list(set(["position_id", "match_phase", "move_played_error"] + FEATURE_COLS))
    df_enr = sample_parquet_dir(enriched_dir, n * 2, columns=enr_cols)
    # Ensure we only have positions that exist in both sets.
    common_ids = set(df_themes["position_id"].to_list())
    df_enr = df_enr.filter(pl.col("position_id").is_in(list(common_ids)))
    print(f"  {len(df_enr):,} enriched rows matched")

    print("\n1. Theme frequencies ...")
    plot_theme_frequencies(df_themes, out_dir)

    print("2. Theme co-occurrence ...")
    plot_cooccurrence(df_themes, out_dir)

    print("3. Feature distributions by theme ...")
    plot_feature_distributions(df_themes, df_enr, out_dir)

    print("4. Error by theme ...")
    plot_error_by_theme(df_themes, df_enr, out_dir)

    print("5. Theme count histogram ...")
    plot_theme_count_histogram(df_themes, out_dir)

    print("6. Phase × theme stacked bar ...")
    plot_phase_theme_stacked(df_themes, df_enr, out_dir)

    # 7. UMAP scatter (if clusters available).
    if args.clusters:
        clusters_dir = Path(args.clusters)
        checker_file = clusters_dir / "clusters_checker.parquet"
        if checker_file.exists():
            print("7. UMAP scatter by theme ...")
            df_clusters = pl.read_parquet(checker_file)
            plot_umap_by_theme(df_themes, df_clusters, out_dir)
        else:
            print("7. (no clusters_checker.parquet, skipping UMAP)")

    print(f"\nDone — plots saved to {out_dir}/")


if __name__ == "__main__":
    main()
