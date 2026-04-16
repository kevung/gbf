#!/usr/bin/env python3
"""
RG.2–RG.6 — Barycentric Visualizations

Generate plots from the barycentric coordinates computed by
compute_barycentric.py.  Reads data/barycentric/ and writes PNG plots.

Plots
-----
  1. Displacement vector field  (quiver plot, 15x15 score grid)
  2. Cube gap heatmap           (15x15 grid, color = mean cube gap)
  3. MWC distribution histograms (per score cell, small multiples)
  4. Per-cell barycenter clouds  (scatter for selected score cells)
  5. Global scatter              (stratified sample, all cells)

Usage
-----
  python scripts/visualize_barycentric.py \\
      --input data/barycentric \\
      [--plots displacement,cube_gap,mwc_hist,clouds,global] \\
      [--cloud-cells 3-3,5-3,7-7,1-5]
"""

import argparse
from pathlib import Path

import numpy as np
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


# ---------------------------------------------------------------------------
# Kazaross MET (for MWC histogram reference lines)
# ---------------------------------------------------------------------------

MET_TABLE = [
    [50,   67.7, 75.1, 81.4, 84.2, 88.7, 90.7, 93.3, 94.4, 95.9, 96.6, 97.6, 98,   98.5, 98.8],
    [32.3, 50,   59.9, 66.9, 74.4, 79.9, 84.2, 87.5, 90.2, 92.3, 93.9, 95.2, 96.2, 97.1, 97.7],
    [24.9, 40.1, 50,   57.6, 64.8, 71.1, 76.2, 80.5, 84,   87.1, 89.4, 91.5, 93.1, 94.4, 95.5],
    [18.6, 33.1, 42.9, 50,   57.7, 64.3, 69.9, 74.6, 78.8, 82.4, 85.4, 87.9, 90,   91.8, 93.3],
    [15.8, 25.6, 35.2, 42.3, 50,   56.6, 62.6, 67.8, 72.5, 76.7, 80.3, 83.4, 86,   88.3, 90.2],
    [11.3, 20.1, 28.9, 35.7, 43.4, 50,   56.3, 61.6, 66.8, 71.3, 75.3, 78.9, 82,   84.7, 87.0],
    [9.3,  15.8, 23.8, 30.1, 37.4, 43.7, 50,   55.5, 60.8, 65.6, 70.0, 73.9, 77.4, 80.5, 83.3],
    [6.8,  12.5, 19.5, 25.4, 32.2, 38.4, 44.5, 50,   55.4, 60.4, 65.0, 69.1, 72.9, 76.4, 79.4],
    [5.6,  9.8,  16.0, 21.2, 27.5, 33.2, 39.1, 44.6, 50,   55.0, 59.8, 64.1, 68.2, 71.9, 75.3],
    [4.1,  7.7,  12.9, 17.6, 23.3, 28.7, 34.4, 39.6, 45.0, 50,   54.9, 59.3, 63.6, 67.5, 71.1],
    [3.4,  6.1,  10.6, 14.6, 19.7, 24.7, 30.0, 35.0, 40.2, 45.1, 50,   54.6, 58.9, 63.0, 66.8],
    [2.4,  4.8,  8.5,  12.1, 16.6, 21.1, 26.1, 30.9, 35.9, 40.7, 45.4, 50,   54.4, 58.6, 62.5],
    [2.0,  3.8,  6.9,  10.0, 14.0, 18.0, 22.6, 27.1, 31.8, 36.4, 41.1, 45.6, 50,   54.2, 58.3],
    [1.5,  2.9,  5.6,  8.2,  11.7, 15.3, 19.5, 23.6, 28.1, 32.5, 37.0, 41.4, 45.8, 50,   54.1],
    [1.2,  2.3,  4.5,  6.7,  9.8,  13.0, 16.7, 20.6, 24.7, 28.9, 33.2, 37.5, 41.7, 45.9, 50],
]


def kazaross_mwc(a: int, b: int) -> float | None:
    if 1 <= a <= 15 and 1 <= b <= 15:
        return MET_TABLE[a - 1][b - 1] / 100.0
    return None


# ---------------------------------------------------------------------------
# 1. Displacement vector field
# ---------------------------------------------------------------------------

def plot_displacement_field(agg: pl.DataFrame, output: Path) -> None:
    """15x15 quiver plot: arrows show mean displacement per score cell."""
    fig, ax = plt.subplots(figsize=(10, 10))

    rows = agg.filter(
        (pl.col("score_away_p1") >= 1) & (pl.col("score_away_p1") <= 15)
        & (pl.col("score_away_p2") >= 1) & (pl.col("score_away_p2") <= 15)
    ).to_dicts()

    if not rows:
        print("  [WARN] No data for displacement field")
        plt.close()
        return

    x = np.array([r["score_away_p2"] for r in rows])   # opponent away = x axis
    y = np.array([r["score_away_p1"] for r in rows])   # our away = y axis
    u = np.array([r["mean_disp_b"] for r in rows])     # displacement in opponent direction
    v = np.array([r["mean_disp_a"] for r in rows])     # displacement in our direction
    mwc = np.array([r["mean_cubeless_mwc"] for r in rows])

    # Color by MWC: diverging blue (winning) to red (losing)
    norm = mcolors.TwoSlopeNorm(vmin=0.0, vcenter=0.5, vmax=1.0)
    cmap = plt.cm.RdBu

    q = ax.quiver(x, y, u, v, mwc, cmap=cmap, norm=norm,
                  angles="xy", scale_units="xy", scale=1.0,
                  width=0.004, headwidth=4, headlength=5)

    cbar = plt.colorbar(q, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Cubeless MWC", fontsize=11)

    # Grid
    ax.set_xlim(0.5, 15.5)
    ax.set_ylim(0.5, 15.5)
    ax.set_xticks(range(1, 16))
    ax.set_yticks(range(1, 16))
    ax.set_xlabel("Opponent away score", fontsize=12)
    ax.set_ylabel("Player away score", fontsize=12)
    ax.set_title("Displacement Vector Field — Expected Score Movement", fontsize=14)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.invert_yaxis()

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close()
    print(f"    -> {output}")


# ---------------------------------------------------------------------------
# 2. Cube gap heatmap
# ---------------------------------------------------------------------------

def plot_cube_gap_heatmap(agg: pl.DataFrame, output: Path) -> None:
    """15x15 heatmap of mean cube gap per score cell."""
    fig, ax = plt.subplots(figsize=(10, 9))

    grid = np.full((15, 15), np.nan)
    n_grid = np.full((15, 15), 0)

    for row in agg.iter_rows(named=True):
        a, b = int(row["score_away_p1"]), int(row["score_away_p2"])
        if 1 <= a <= 15 and 1 <= b <= 15:
            grid[a - 1, b - 1] = row["mean_cube_gap"]
            n_grid[a - 1, b - 1] = row["n"]

    vmax = np.nanmax(np.abs(grid))
    im = ax.imshow(grid, cmap="RdBu_r", vmin=-vmax, vmax=vmax,
                   origin="upper", extent=(0.5, 15.5, 15.5, 0.5))

    # Annotate cells with values
    for a in range(1, 16):
        for b in range(1, 16):
            val = grid[a - 1, b - 1]
            n = n_grid[a - 1, b - 1]
            if not np.isnan(val) and n >= 20:
                color = "white" if abs(val) > vmax * 0.6 else "black"
                ax.text(b, a, f"{val:+.2f}", ha="center", va="center",
                        fontsize=6, color=color)

    cbar = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Mean cube gap (cubeful - cubeless equity)", fontsize=11)

    ax.set_xticks(range(1, 16))
    ax.set_yticks(range(1, 16))
    ax.set_xlabel("Opponent away score", fontsize=12)
    ax.set_ylabel("Player away score", fontsize=12)
    ax.set_title("Cube Gap Heatmap — Where Cube Ownership Matters", fontsize=14)

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close()
    print(f"    -> {output}")


# ---------------------------------------------------------------------------
# 3. MWC distribution histograms (small multiples)
# ---------------------------------------------------------------------------

def plot_mwc_histograms(positions: pl.DataFrame, output_dir: Path,
                        max_away: int = 13) -> None:
    """Small multiples: MWC distribution per score cell."""
    output_dir.mkdir(parents=True, exist_ok=True)

    ncols = max_away
    nrows = max_away
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 1.5, nrows * 1.2),
                             sharex=True, sharey=True)

    for a in range(1, max_away + 1):
        for b in range(1, max_away + 1):
            ax = axes[a - 1, b - 1]
            cell = positions.filter(
                (pl.col("score_away_p1") == a)
                & (pl.col("score_away_p2") == b)
            )
            if len(cell) < 10:
                ax.set_visible(False)
                continue

            vals = cell["cubeless_mwc"].to_numpy()
            ax.hist(vals, bins=30, density=True, alpha=0.7,
                    color="steelblue", edgecolor="none")

            # Kazaross reference line
            kaz = kazaross_mwc(a, b)
            if kaz is not None:
                ax.axvline(kaz, color="red", linewidth=1, linestyle="--")

            ax.set_xlim(0, 1)
            ax.tick_params(labelsize=5)
            if a == 1:
                ax.set_title(f"{b}a", fontsize=7)
            if b == 1:
                ax.set_ylabel(f"{a}a", fontsize=7, rotation=0, labelpad=12)

    fig.suptitle("Cubeless MWC Distributions per Score Cell\n"
                 "(red = Kazaross MET reference)",
                 fontsize=13, y=1.01)
    fig.tight_layout()
    p = output_dir / "mwc_distributions.png"
    fig.savefig(p, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    -> {p}")


# ---------------------------------------------------------------------------
# 4. Per-cell barycenter scatter clouds
# ---------------------------------------------------------------------------

def plot_score_clouds(positions: pl.DataFrame, cells: list[tuple[int, int]],
                      output_dir: Path, max_per_cell: int = 5000) -> None:
    """Scatter of barycentric coordinates for selected score cells."""
    output_dir.mkdir(parents=True, exist_ok=True)

    ncols = min(len(cells), 3)
    nrows = (len(cells) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(6 * ncols, 5.5 * nrows),
                             squeeze=False)

    for idx, (a, b) in enumerate(cells):
        ax = axes[idx // ncols, idx % ncols]
        cell = positions.filter(
            (pl.col("score_away_p1") == a) & (pl.col("score_away_p2") == b)
        )
        if len(cell) == 0:
            ax.set_visible(False)
            continue
        if len(cell) > max_per_cell:
            cell = cell.sample(n=max_per_cell, seed=42)

        bx = cell["bary_b"].to_numpy()
        by = cell["bary_a"].to_numpy()
        mwc = cell["cubeless_mwc"].to_numpy()
        gap = np.abs(cell["cube_gap"].to_numpy())

        # Size: cube gap magnitude (scaled)
        sizes = 5 + 40 * (gap / (gap.max() + 1e-9))

        sc = ax.scatter(bx, by, c=mwc, cmap="RdBu", vmin=0, vmax=1,
                        s=sizes, alpha=0.3, edgecolors="none")

        # Crosshair at current score
        ax.axvline(b, color="gray", linewidth=0.8, linestyle=":")
        ax.axhline(a, color="gray", linewidth=0.8, linestyle=":")
        ax.plot(b, a, marker="+", color="black", markersize=15, markeredgewidth=2)

        ax.set_xlabel("Opponent away (barycenter)", fontsize=10)
        ax.set_ylabel("Player away (barycenter)", fontsize=10)
        ax.set_title(f"Score {a}a-{b}a  (n={len(cell):,})", fontsize=11)
        ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.2)

    # Hide unused axes
    for idx in range(len(cells), nrows * ncols):
        axes[idx // ncols, idx % ncols].set_visible(False)

    fig.suptitle("Barycenter Clouds per Score Cell\n"
                 "(color = cubeless MWC, size = |cube gap|)",
                 fontsize=13)
    fig.tight_layout()
    p = output_dir / "score_clouds.png"
    fig.savefig(p, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    -> {p}")


# ---------------------------------------------------------------------------
# 5. Global scatter
# ---------------------------------------------------------------------------

def plot_global_scatter(positions: pl.DataFrame, output: Path,
                        per_cell: int = 500) -> None:
    """Stratified sample of all barycenters in score space."""
    sampled = (
        positions.with_columns(
            pl.lit(1).alias("_dummy")
        )
        .group_by(["score_away_p1", "score_away_p2"])
        .map_groups(
            lambda g: g.sample(n=min(per_cell, len(g)), seed=42)
        )
    )

    fig, ax = plt.subplots(figsize=(10, 10))

    bx = sampled["bary_b"].to_numpy()
    by = sampled["bary_a"].to_numpy()
    mwc = sampled["cubeless_mwc"].to_numpy()

    sc = ax.scatter(bx, by, c=mwc, cmap="RdBu", vmin=0, vmax=1,
                    s=3, alpha=0.15, edgecolors="none")

    cbar = plt.colorbar(sc, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Cubeless MWC", fontsize=11)

    # Score grid
    for i in range(1, 16):
        ax.axvline(i, color="gray", linewidth=0.3, alpha=0.4)
        ax.axhline(i, color="gray", linewidth=0.3, alpha=0.4)

    ax.set_xlim(-0.5, 16)
    ax.set_ylim(-0.5, 16)
    ax.set_xlabel("Opponent away (barycenter)", fontsize=12)
    ax.set_ylabel("Player away (barycenter)", fontsize=12)
    ax.set_title(f"Global Barycenter Scatter  (n={len(sampled):,})", fontsize=14)
    ax.set_aspect("equal")
    ax.invert_yaxis()

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close()
    print(f"    -> {output}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_cells(s: str) -> list[tuple[int, int]]:
    """Parse '3-3,5-3,7-7' into [(3,3),(5,3),(7,7)]."""
    cells = []
    for pair in s.split(","):
        parts = pair.strip().split("-")
        if len(parts) == 2:
            cells.append((int(parts[0]), int(parts[1])))
    return cells


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RG.2-RG.6 — Barycentric Visualizations")
    ap.add_argument("--input", default="data/barycentric",
                    help="Input directory (output of compute_barycentric.py)")
    ap.add_argument("--plots", default="displacement,cube_gap,mwc_hist,clouds,global",
                    help="Comma-separated list of plots to generate")
    ap.add_argument("--cloud-cells", default="3-3,5-3,7-7,1-5,5-1,9-9",
                    help="Score cells for cloud scatter (a-b format)")
    ap.add_argument("--max-away-hist", type=int, default=13,
                    help="Max away for MWC histogram grid (default: 13)")
    args = ap.parse_args()

    input_dir = Path(args.input)
    plots_dir = input_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    plots = set(args.plots.split(","))

    print("=" * 60)
    print("  RG — Barycentric Visualizations")
    print("=" * 60)
    print(f"  input : {input_dir}")
    print(f"  plots : {', '.join(sorted(plots))}")

    # Load aggregates
    agg_path = input_dir / "barycentric_aggregates.csv"
    if not agg_path.exists():
        print(f"  [ERROR] Aggregates not found: {agg_path}")
        print("  Run compute_barycentric.py first.")
        return
    agg = pl.read_csv(agg_path)
    print(f"\n  Loaded {len(agg)} aggregate cells")

    # Load positions (for per-position plots)
    pos = None
    pos_path = input_dir / "barycentric.parquet"
    needs_positions = plots & {"mwc_hist", "clouds", "global"}
    if needs_positions:
        if not pos_path.exists():
            print(f"  [WARN] Parquet not found: {pos_path} — skipping position-level plots")
            plots -= {"mwc_hist", "clouds", "global"}
        else:
            pos = pl.read_parquet(pos_path)
            print(f"  Loaded {len(pos):,} positions")

    # --- Generate plots ---
    print()

    if "displacement" in plots:
        print("  Generating displacement vector field...")
        plot_displacement_field(agg, plots_dir / "displacement_field.png")

    if "cube_gap" in plots:
        print("  Generating cube gap heatmap...")
        plot_cube_gap_heatmap(agg, plots_dir / "cube_gap_heatmap.png")

    if "mwc_hist" in plots and pos is not None:
        print("  Generating MWC distribution histograms...")
        plot_mwc_histograms(pos, plots_dir, max_away=args.max_away_hist)

    if "clouds" in plots and pos is not None:
        cells = parse_cells(args.cloud_cells)
        print(f"  Generating barycenter clouds for {len(cells)} cells...")
        plot_score_clouds(pos, cells, plots_dir)

    if "global" in plots and pos is not None:
        print("  Generating global scatter...")
        plot_global_scatter(pos, plots_dir / "global_scatter.png")

    print(f"\n{'='*60}")
    print(f"  Done — plots in {plots_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
