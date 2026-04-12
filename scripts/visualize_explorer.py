#!/usr/bin/env python3
"""Interactive Feature Explorer — scatter, histogram, and violin plots
with filtering by theme, cluster, match phase, and custom predicates.

Generates either static PNGs (default) or an interactive Plotly HTML
dashboard (``--interactive``).

Usage::

    # Static PNG overview (all themes):
    python scripts/visualize_explorer.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --clusters data/clusters \\
        --output viz/explorer

    # Filter to specific theme(s):
    python scripts/visualize_explorer.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --filter-themes blitz priming holding \\
        --output viz/explorer/blitz_priming_holding

    # Filter by match phase:
    python scripts/visualize_explorer.py \\
        --enriched data/parquet/positions_enriched \\
        --filter-phase contact \\
        --output viz/explorer/contact

    # Interactive HTML:
    python scripts/visualize_explorer.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --clusters data/clusters \\
        --output viz/explorer \\
        --interactive

    # Custom scatter axes:
    python scripts/visualize_explorer.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --scatter-x pip_count_diff --scatter-y move_played_error \\
        --output viz/explorer/pip_vs_error
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


# ── Constants ────────────────────────────────────────────────────────

PHASE_MAP = {"contact": 0, "race": 1, "bearoff": 2}
PHASE_COLORS = {0: "#e74c3c", 1: "#2ecc71", 2: "#3498db"}
PHASE_LABELS = {0: "Contact", 1: "Race", 2: "Bearoff"}

THEME_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    "#e6beff", "#1a55FF", "#aa6e28", "#800080", "#00FF7F",
    "#FF6347", "#708090",
]

# Default scatter pairs for overview.
DEFAULT_SCATTER_PAIRS = [
    ("pip_count_diff", "move_played_error"),
    ("eval_win", "move_played_error"),
    ("home_board_points_p1", "num_blots_p2"),
    ("longest_prime_p1", "num_checkers_back_p1"),
    ("gammon_threat", "gammon_risk"),
    ("cube_leverage", "move_played_error"),
]

# Features for histograms.
HIST_FEATURES = [
    "pip_count_diff", "move_played_error", "eval_win",
    "gammon_threat", "num_blots_p1", "home_board_points_p1",
    "longest_prime_p1", "num_checkers_back_p1", "cube_leverage",
]

ALL_FEATURES = sorted(set(
    [a for a, b in DEFAULT_SCATTER_PAIRS] +
    [b for a, b in DEFAULT_SCATTER_PAIRS] +
    HIST_FEATURES
))


# ── Helpers ──────────────────────────────────────────────────────────

def sample_parquet_dir(path: Path, n: int, columns: list[str] | None = None) -> pl.DataFrame:
    files = sorted(path.glob("part-*.parquet"))
    if not files:
        sys.exit(f"No parquet files in {path}")
    schema_cols = pl.read_parquet(files[0], n_rows=1).columns
    cols = [c for c in columns if c in schema_cols] if columns else None
    frames = []
    rows = 0
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


def apply_filters(
    df: pl.DataFrame,
    theme_filter: list[str] | None,
    phase_filter: int | None,
    cluster_filter: list[int] | None,
    df_themes: pl.DataFrame | None,
    df_clusters: pl.DataFrame | None,
) -> pl.DataFrame:
    """Apply subset filters and return filtered dataframe with metadata columns."""

    if theme_filter and df_themes is not None:
        # Match positions that have ANY of the requested themes.
        theme_cols = [f"theme_{t}" for t in theme_filter]
        valid_cols = [c for c in theme_cols if c in df_themes.columns]
        if valid_cols:
            mask = df_themes.select(
                pl.col("position_id"),
                pl.any_horizontal(*[pl.col(c) for c in valid_cols]).alias("_match"),
            ).filter(pl.col("_match"))
            df = df.join(mask.select("position_id"), on="position_id", how="semi")

    if phase_filter is not None:
        df = df.filter(pl.col("match_phase") == phase_filter)

    if cluster_filter and df_clusters is not None:
        df = df.join(
            df_clusters.filter(pl.col("cluster").is_in(cluster_filter)).select("position_id"),
            on="position_id",
            how="semi",
        )

    return df


def add_color_column(
    df: pl.DataFrame,
    color_by: str,
    df_themes: pl.DataFrame | None,
    df_clusters: pl.DataFrame | None,
) -> tuple[pl.DataFrame, dict]:
    """Add a 'color_label' column and return label→color mapping."""
    if color_by == "phase":
        df = df.with_columns(
            pl.col("match_phase").replace_strict(
                {0: "Contact", 1: "Race", 2: "Bearoff"}, default="Unknown"
            ).alias("color_label")
        )
        cmap = {"Contact": "#e74c3c", "Race": "#2ecc71", "Bearoff": "#3498db", "Unknown": "#999"}
    elif color_by == "theme" and df_themes is not None:
        merged = df.join(
            df_themes.select(["position_id", "primary_theme"]),
            on="position_id", how="left",
        )
        merged = merged.with_columns(
            pl.col("primary_theme").fill_null("unclassified").alias("color_label")
        )
        labels = merged["color_label"].unique().sort().to_list()
        cmap = {l: THEME_PALETTE[i % len(THEME_PALETTE)] for i, l in enumerate(labels)}
        return merged, cmap
    elif color_by == "cluster" and df_clusters is not None:
        merged = df.join(
            df_clusters.select(["position_id", "cluster"]),
            on="position_id", how="left",
        )
        merged = merged.with_columns(
            pl.col("cluster").fill_null(-1).cast(pl.Utf8).alias("color_label")
        )
        labels = merged["color_label"].unique().sort().to_list()
        cmap = {l: THEME_PALETTE[i % len(THEME_PALETTE)] for i, l in enumerate(labels)}
        return merged, cmap
    else:
        df = df.with_columns(pl.lit("all").alias("color_label"))
        cmap = {"all": "#4363d8"}

    return df, cmap


# ── Static Plots ─────────────────────────────────────────────────────

def plot_scatter(df: pl.DataFrame, x_col: str, y_col: str,
                 cmap: dict, out_dir: Path, tag: str = "") -> None:
    """Scatter plot of two features, colored by color_label."""
    fig, ax = plt.subplots(figsize=(10, 8))
    labels = sorted(df["color_label"].unique().to_list())

    for label in labels:
        subset = df.filter(pl.col("color_label") == label)
        x = subset[x_col].to_numpy()
        y = subset[y_col].to_numpy()
        color = cmap.get(label, "#999")
        display = label.replace("_", " ").title()[:20]
        ax.scatter(x, y, c=color, s=3, alpha=0.3, label=display, rasterized=True)

    ax.set_xlabel(x_col.replace("_", " ").title())
    ax.set_ylabel(y_col.replace("_", " ").title())
    title = f"{x_col} vs {y_col}"
    if tag:
        title += f" ({tag})"
    ax.set_title(title)
    if len(labels) <= 20:
        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=7,
                  markerscale=3, ncol=max(1, len(labels) // 15))
    fig.tight_layout()
    name = f"scatter_{x_col}_vs_{y_col}"
    if tag:
        name += f"_{tag}"
    save(fig, out_dir, name)


def plot_histograms(df: pl.DataFrame, features: list[str],
                    cmap: dict, out_dir: Path, tag: str = "") -> None:
    """Overlaid histograms for each feature, split by color_label."""
    feats = [f for f in features if f in df.columns]
    ncols = 3
    nrows = (len(feats) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes = axes.flatten()

    labels = sorted(df["color_label"].unique().to_list())

    for idx, feat in enumerate(feats):
        ax = axes[idx]
        for label in labels:
            subset = df.filter(pl.col("color_label") == label)
            vals = subset[feat].drop_nulls().to_numpy()
            if len(vals) > 0:
                color = cmap.get(label, "#999")
                display = label.replace("_", " ").title()[:15]
                ax.hist(vals, bins=50, color=color, alpha=0.5,
                        density=True, label=display)
        ax.set_title(feat.replace("_", " ").title(), fontsize=9)
        ax.set_ylabel("Density")
        if idx == 0 and len(labels) <= 10:
            ax.legend(fontsize=6)

    for idx in range(len(feats), len(axes)):
        axes[idx].set_visible(False)

    title = "Feature Histograms"
    if tag:
        title += f" — {tag}"
    fig.suptitle(title, fontsize=12, y=1.01)
    fig.tight_layout()
    name = "histograms"
    if tag:
        name += f"_{tag}"
    save(fig, out_dir, name)


def plot_violin_error(df: pl.DataFrame, group_col: str,
                      out_dir: Path, tag: str = "") -> None:
    """Violin (box) plot of move_played_error by group."""
    if "move_played_error" not in df.columns or group_col not in df.columns:
        return

    groups = df.group_by(group_col).len().sort("len", descending=True)
    top = groups.head(15)[group_col].to_list()
    filtered = df.filter(pl.col(group_col).is_in(top))

    data, labels = [], []
    for g in top:
        vals = filtered.filter(pl.col(group_col) == g)["move_played_error"].drop_nulls().to_numpy()
        if len(vals) > 0:
            data.append(vals)
            labels.append(str(g).replace("_", " ").title()[:18])

    if not data:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    bp = ax.boxplot(data, patch_artist=True, showfliers=False)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(THEME_PALETTE[i % len(THEME_PALETTE)])
        patch.set_alpha(0.7)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Move Played Error")
    title = f"Error Distribution by {group_col.replace('_', ' ').title()}"
    if tag:
        title += f" — {tag}"
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    name = f"violin_error_by_{group_col}"
    if tag:
        name += f"_{tag}"
    save(fig, out_dir, name)


# ── Interactive Plotly Dashboard ─────────────────────────────────────

def create_interactive_dashboard(
    df: pl.DataFrame,
    cmap: dict,
    out_dir: Path,
    tag: str = "",
) -> None:
    """Build a self-contained Plotly HTML with dropdowns for X/Y axes
    and color-by selector."""
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  (plotly not installed, skipping interactive dashboard)")
        return

    # Convert to pandas for plotly.
    pdf = df.to_pandas()
    features = [c for c in ALL_FEATURES if c in pdf.columns]
    if not features:
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Main scatter with dropdown ──
    fig = px.scatter(
        pdf, x=features[0], y=features[1] if len(features) > 1 else features[0],
        color="color_label",
        color_discrete_map=cmap,
        opacity=0.4,
        title="Feature Explorer — use dropdowns to change axes",
        hover_data=["position_id"] if "position_id" in pdf.columns else None,
    )
    fig.update_traces(marker=dict(size=3))

    # Add dropdowns for axes.
    x_buttons = [
        dict(label=f, method="update",
             args=[{"x": [pdf[f].values]},
                   {"xaxis.title.text": f.replace("_", " ").title()}])
        for f in features
    ]
    y_buttons = [
        dict(label=f, method="update",
             args=[{"y": [pdf[f].values]},
                   {"yaxis.title.text": f.replace("_", " ").title()}])
        for f in features
    ]

    fig.update_layout(
        updatemenus=[
            dict(buttons=x_buttons, direction="down",
                 showactive=True, x=0.0, y=1.15,
                 xanchor="left", yanchor="top",
                 pad=dict(t=5), bgcolor="white"),
            dict(buttons=y_buttons, direction="down",
                 showactive=True, x=0.25, y=1.15,
                 xanchor="left", yanchor="top",
                 pad=dict(t=5), bgcolor="white"),
        ],
        annotations=[
            dict(text="X-axis:", x=0.0, y=1.19, xref="paper", yref="paper",
                 showarrow=False, font=dict(size=11)),
            dict(text="Y-axis:", x=0.25, y=1.19, xref="paper", yref="paper",
                 showarrow=False, font=dict(size=11)),
        ],
        height=700,
        template="plotly_white",
    )

    name = "interactive_explorer"
    if tag:
        name += f"_{tag}"
    path = out_dir / f"{name}.html"
    fig.write_html(str(path), include_plotlyjs="cdn")
    print(f"  saved {path}")

    # ── Histogram dashboard ──
    fig2 = make_subplots(
        rows=3, cols=3,
        subplot_titles=[f.replace("_", " ").title() for f in features[:9]],
    )
    labels = sorted(pdf["color_label"].unique())
    for idx, feat in enumerate(features[:9]):
        row = idx // 3 + 1
        col = idx % 3 + 1
        for label in labels:
            sub = pdf[pdf["color_label"] == label]
            color = cmap.get(label, "#999")
            fig2.add_trace(
                go.Histogram(
                    x=sub[feat], name=label.replace("_", " ").title()[:15],
                    marker_color=color, opacity=0.6,
                    showlegend=(idx == 0),
                    histnorm="probability density",
                ),
                row=row, col=col,
            )

    fig2.update_layout(
        height=800, width=1200,
        title="Feature Histograms by Group",
        template="plotly_white",
        barmode="overlay",
    )
    hname = "interactive_histograms"
    if tag:
        hname += f"_{tag}"
    hpath = out_dir / f"{hname}.html"
    fig2.write_html(str(hpath), include_plotlyjs="cdn")
    print(f"  saved {hpath}")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Feature Explorer with subsetting.")
    parser.add_argument("--enriched", required=True)
    parser.add_argument("--themes", default=None, help="position_themes parquet dir")
    parser.add_argument("--clusters", default=None, help="clusters dir")
    parser.add_argument("--output", default="viz/explorer")
    parser.add_argument("--sample", type=int, default=200000)
    parser.add_argument("--interactive", action="store_true")

    # Filters.
    parser.add_argument("--filter-themes", nargs="+", default=None,
                        help="Theme names (without theme_ prefix)")
    parser.add_argument("--filter-phase", choices=["contact", "race", "bearoff"],
                        default=None)
    parser.add_argument("--filter-clusters", nargs="+", type=int, default=None)

    # Color-by.
    parser.add_argument("--color-by", choices=["phase", "theme", "cluster"],
                        default="phase")

    # Custom scatter.
    parser.add_argument("--scatter-x", default=None)
    parser.add_argument("--scatter-y", default=None)

    args = parser.parse_args()
    out_dir = Path(args.output)

    # Load data.
    all_cols = list(set(["position_id", "match_phase", "move_played_error",
                         "decision_type"] + ALL_FEATURES))
    if args.scatter_x:
        all_cols.append(args.scatter_x)
    if args.scatter_y:
        all_cols.append(args.scatter_y)
    all_cols = list(set(all_cols))

    print(f"Loading enriched (sample={args.sample:,}) ...")
    df = sample_parquet_dir(Path(args.enriched), args.sample, columns=all_cols)
    print(f"  {len(df):,} positions loaded")

    df_themes = None
    if args.themes:
        themes_path = Path(args.themes)
        if themes_path.exists():
            print("Loading themes ...")
            tcols = ["position_id", "primary_theme", "theme_count"] + ALL_THEME_COLUMNS
            df_themes = sample_parquet_dir(themes_path, args.sample * 2, columns=tcols)
            print(f"  {len(df_themes):,} theme rows")

    df_clusters = None
    if args.clusters:
        cp = Path(args.clusters) / "clusters_checker.parquet"
        if cp.exists():
            print("Loading clusters ...")
            df_clusters = pl.read_parquet(cp)
            print(f"  {len(df_clusters):,} cluster rows")

    # Apply filters.
    tag_parts = []
    phase_val = PHASE_MAP.get(args.filter_phase) if args.filter_phase else None
    df = apply_filters(df, args.filter_themes, phase_val,
                       args.filter_clusters, df_themes, df_clusters)
    if args.filter_themes:
        tag_parts.append("themes=" + "+".join(args.filter_themes))
    if args.filter_phase:
        tag_parts.append(args.filter_phase)
    if args.filter_clusters:
        tag_parts.append("clusters=" + "+".join(map(str, args.filter_clusters)))
    tag = "_".join(tag_parts) if tag_parts else ""

    print(f"  {len(df):,} positions after filters")
    if len(df) == 0:
        print("No positions match the filter criteria.")
        return

    # Add color.
    df, cmap = add_color_column(df, args.color_by, df_themes, df_clusters)

    # Static plots.
    print("\nGenerating scatter plots ...")
    if args.scatter_x and args.scatter_y:
        plot_scatter(df, args.scatter_x, args.scatter_y, cmap, out_dir, tag)
    else:
        for x_col, y_col in DEFAULT_SCATTER_PAIRS:
            if x_col in df.columns and y_col in df.columns:
                plot_scatter(df, x_col, y_col, cmap, out_dir, tag)

    print("Generating histograms ...")
    plot_histograms(df, HIST_FEATURES, cmap, out_dir, tag)

    # Error distribution.
    if args.color_by == "theme" and "color_label" in df.columns:
        print("Error violin by theme ...")
        plot_violin_error(df, "color_label", out_dir, tag)
    elif args.color_by == "phase":
        print("Error violin by phase ...")
        plot_violin_error(df, "color_label", out_dir, tag)

    # Interactive.
    if args.interactive:
        print("\nGenerating interactive Plotly dashboard ...")
        create_interactive_dashboard(df, cmap, out_dir, tag)

    print(f"\nDone — saved to {out_dir}/")


if __name__ == "__main__":
    main()
