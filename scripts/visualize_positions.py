#!/usr/bin/env python3
"""Theme Position Browser — sample positions per theme for classification review.

For each theme, extracts a sample of matching positions and generates:
  1. A summary CSV with position details + all theme flags
  2. Board diagrams (ASCII art in text file + optional PNG grid)
  3. Per-theme scatter of key discriminating features (shows WHY
     positions were classified under that theme)
  4. A comparison view showing the same features for theme vs non-theme

This is the tool to validate that theme criteria are working:
review the sampled positions and check they genuinely represent
the intended backgammon concept.

Usage::

    # Review all themes (20 samples each):
    python scripts/visualize_positions.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --output viz/positions \\
        --per-theme 20

    # Review a specific theme:
    python scripts/visualize_positions.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --output viz/positions/blitz \\
        --only-themes blitz \\
        --per-theme 50

    # Review multiple themes side by side:
    python scripts/visualize_positions.py \\
        --enriched data/parquet/positions_enriched \\
        --themes data/parquet/position_themes \\
        --output viz/positions/compare \\
        --only-themes blitz priming holding ace_point
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.theme_rules import ALL_THEME_COLUMNS


# ── Constants ────────────────────────────────────────────────────────

# Features most relevant for distinguishing each theme.
# Maps theme_name → list of (feature_col, expected_direction_description).
THEME_DISCRIMINATORS = {
    "opening": ["move_number", "pip_count_p1", "pip_count_p2", "num_borne_off_p1"],
    "flexibility": ["num_builders_p1", "longest_prime_p1", "num_blots_p1", "num_points_made_p1"],
    "middle_game": ["move_number", "pip_count_p1", "num_borne_off_p1", "num_borne_off_p2"],
    "5_point": ["move_number", "num_checkers_back_p1", "num_checkers_back_p2"],
    "blitz": ["home_board_points_p1", "num_on_bar_p2", "num_blots_p2", "pip_count_p1"],
    "one_man_back": ["num_checkers_back_p1", "longest_prime_p2", "eval_win"],
    "holding": ["num_checkers_back_p1", "back_anchor_p1", "eval_win"],
    "priming": ["longest_prime_p1", "prime_location_p1", "num_checkers_back_p2"],
    "connectivity": ["num_blots_p1", "outfield_blots_p1", "num_points_made_p1"],
    "hit_or_not": ["num_blots_p1", "num_blots_p2", "move_played_error"],
    "crunch": ["home_board_points_p1", "num_points_made_p1", "pip_count_diff"],
    "action_doubles": ["eval_win", "gammon_threat", "gammon_risk"],
    "late_blitz": ["home_board_points_p1", "num_on_bar_p2", "move_number"],
    "too_good": ["eval_win", "gammon_threat", "eval_equity"],
    "ace_point": ["num_checkers_back_p1", "back_anchor_p1", "eval_win"],
    "back_game": ["num_checkers_back_p1", "back_anchor_p1", "pip_count_diff"],
    "containment": ["num_checkers_back_p2", "longest_prime_p1", "pip_count_diff"],
    "playing_gammon": ["gammon_threat", "eval_win", "home_board_points_p1"],
    "saving_gammon": ["gammon_risk", "eval_win", "num_borne_off_p1"],
    "bearoff_vs_contact": ["num_borne_off_p1", "num_borne_off_p2", "match_phase"],
    "various_endgames": ["match_phase", "pip_count_p1", "eval_win"],
    "race": ["match_phase", "pip_count_diff", "num_borne_off_p1"],
    "bearoff": ["match_phase", "num_borne_off_p1", "num_borne_off_p2"],
    "breaking_anchor": ["num_checkers_back_p1", "move_number", "eval_win"],
    "post_blitz_turnaround": ["home_board_points_p1", "num_on_bar_p2", "eval_win"],
    "post_ace_point": ["num_checkers_back_p1", "back_anchor_p1", "num_borne_off_p1"],
}

PHASE_LABELS = {0: "Contact", 1: "Race", 2: "Bearoff"}


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
    print(f"    saved {path}")


# ── Board rendering ──────────────────────────────────────────────────

def board_ascii(board_p1: list[int], board_p2: list[int]) -> str:
    """Render a backgammon board as ASCII art.

    board_p1/p2: 26-element arrays [bar, pts 1-24, off].
    p1 moves from high→low (bearoff = index 25), p2 from low→high.
    """
    lines = []
    lines.append("┌─13─14─15─16─17─18──┬──19─20─21─22─23─24─┐")
    # Top half: points 13-24.
    for row in range(5):
        top_left = ""
        for pt in range(13, 19):
            p1c = board_p1[pt]
            p2c = board_p2[25 - pt]  # p2's perspective is mirrored.
            ch = _point_char(p1c, p2c, row)
            top_left += f" {ch} "
        top_right = ""
        for pt in range(19, 25):
            p1c = board_p1[pt]
            p2c = board_p2[25 - pt]
            ch = _point_char(p1c, p2c, row)
            top_right += f" {ch} "
        lines.append(f"│{top_left}│{top_right}│")

    # Bar.
    bar1, bar2 = board_p1[0], board_p2[0]
    lines.append(f"│{'         BAR        '}│{' ' * 20}│  P1bar:{bar1} P2bar:{bar2}")

    # Bottom half: points 12-1 (displayed left to right as 12,11,..,7 | 6,5,..,1).
    for row in range(4, -1, -1):
        bot_left = ""
        for pt in range(12, 6, -1):
            p1c = board_p1[pt]
            p2c = board_p2[25 - pt]
            ch = _point_char(p1c, p2c, row)
            bot_left += f" {ch} "
        bot_right = ""
        for pt in range(6, 0, -1):
            p1c = board_p1[pt]
            p2c = board_p2[25 - pt]
            ch = _point_char(p1c, p2c, row)
            bot_right += f" {ch} "
        lines.append(f"│{bot_left}│{bot_right}│")

    lines.append("└─12─11─10──9──8──7──┴───6──5──4──3──2──1─┘")
    lines.append(f"  P1 off: {board_p1[25]}   P2 off: {board_p2[25]}")
    return "\n".join(lines)


def _point_char(p1_count: int, p2_count: int, row: int) -> str:
    """Character for a point at display row (0=closest to edge)."""
    if p1_count > row:
        return "X" if p1_count <= 5 else str(p1_count) if row == 0 else "X"
    if p2_count > row:
        return "O" if p2_count <= 5 else str(p2_count) if row == 0 else "O"
    return "."


# ── Per-theme analysis ───────────────────────────────────────────────

def analyze_theme(
    theme_name: str,
    df_themes: pl.DataFrame,
    df_enr: pl.DataFrame,
    out_dir: Path,
    per_theme: int,
) -> dict:
    """Generate all outputs for one theme. Returns stats dict."""
    theme_col = f"theme_{theme_name}"
    if theme_col not in df_themes.columns:
        return {}

    theme_dir = out_dir / theme_name
    theme_dir.mkdir(parents=True, exist_ok=True)

    # Get positions for this theme.
    theme_ids = df_themes.filter(pl.col(theme_col))["position_id"].to_list()
    nontheme_ids = df_themes.filter(~pl.col(theme_col))["position_id"].to_list()

    n_theme = len(theme_ids)
    n_total = len(df_themes)
    pct = n_theme / n_total * 100 if n_total > 0 else 0

    print(f"\n  {theme_name}: {n_theme:,} positions ({pct:.1f}%)")

    if n_theme == 0:
        return {"theme": theme_name, "count": 0, "pct": 0}

    # Sample positions for detailed review.
    sample_ids = theme_ids[:per_theme] if n_theme <= per_theme else \
        pl.Series(theme_ids).sample(per_theme, seed=42).to_list()

    sample_enr = df_enr.filter(pl.col("position_id").is_in(sample_ids))
    sample_themes = df_themes.filter(pl.col("position_id").is_in(sample_ids))

    # 1. Summary CSV (drop nested list columns that CSV can't handle).
    merged = sample_themes.join(
        sample_enr.drop([c for c in sample_enr.columns if c in sample_themes.columns and c != "position_id"]),
        on="position_id", how="left",
    )
    csv_cols = [c for c in merged.columns if merged[c].dtype not in (pl.List(pl.Int8), pl.List(pl.Int64))]
    csv_path = theme_dir / "sample_positions.csv"
    merged.select(csv_cols).write_csv(csv_path)
    print(f"    sample CSV: {csv_path}")

    # 2. Board diagrams (text).
    if "board_p1" in sample_enr.columns and "board_p2" in sample_enr.columns:
        txt_path = theme_dir / "board_diagrams.txt"
        with open(txt_path, "w") as f:
            for row in sample_enr.head(min(per_theme, 10)).iter_rows(named=True):
                f.write(f"=== {row['position_id']} ===\n")
                b1 = row["board_p1"]
                b2 = row["board_p2"]
                f.write(board_ascii(b1, b2) + "\n")
                # Key metadata.
                phase = PHASE_LABELS.get(row.get("match_phase", -1), "?")
                f.write(f"  Phase: {phase}  "
                        f"Equity: {row.get('eval_equity', '?'):.3f}  "
                        f"Error: {row.get('move_played_error', '?'):.4f}\n")
                f.write(f"  Pip: {row.get('pip_count_p1', '?')}/{row.get('pip_count_p2', '?')}  "
                        f"Prime: {row.get('longest_prime_p1', '?')}  "
                        f"Back: {row.get('num_checkers_back_p1', '?')}\n\n")
        print(f"    boards: {txt_path}")

    # 3. Discriminator scatter: theme vs. non-theme comparison.
    disc_features = THEME_DISCRIMINATORS.get(theme_name,
        ["eval_win", "move_played_error", "pip_count_diff"])
    disc_features = [f for f in disc_features if f in df_enr.columns]

    if len(disc_features) >= 2:
        # Sample non-theme for comparison.
        n_sample = min(5000, n_theme)
        theme_sample = df_enr.filter(pl.col("position_id").is_in(theme_ids))
        if len(theme_sample) > n_sample:
            theme_sample = theme_sample.sample(n_sample, seed=42)

        nontheme_sample = df_enr.filter(pl.col("position_id").is_in(nontheme_ids))
        if len(nontheme_sample) > n_sample:
            nontheme_sample = nontheme_sample.sample(n_sample, seed=42)

        # Scatter: first two discriminators.
        fx, fy = disc_features[0], disc_features[1]
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.scatter(
            nontheme_sample[fx].to_numpy(),
            nontheme_sample[fy].to_numpy(),
            c="#cccccc", s=2, alpha=0.2, label="Other", rasterized=True,
        )
        ax.scatter(
            theme_sample[fx].to_numpy(),
            theme_sample[fy].to_numpy(),
            c="#e6194b", s=4, alpha=0.5,
            label=theme_name.replace("_", " ").title(),
            rasterized=True,
        )
        ax.set_xlabel(fx.replace("_", " ").title())
        ax.set_ylabel(fy.replace("_", " ").title())
        ax.set_title(f"{theme_name.replace('_', ' ').title()}: "
                      f"{fx} vs {fy} (red = theme, gray = rest)")
        ax.legend(markerscale=4)
        save(fig, theme_dir, f"scatter_{fx}_vs_{fy}")

        # Histogram comparison for each discriminator.
        n_disc = len(disc_features)
        fig, axes = plt.subplots(1, n_disc, figsize=(5 * n_disc, 4))
        if n_disc == 1:
            axes = [axes]
        for idx, feat in enumerate(disc_features):
            ax = axes[idx]
            t_vals = theme_sample[feat].drop_nulls().to_numpy()
            nt_vals = nontheme_sample[feat].drop_nulls().to_numpy()
            if len(t_vals) > 0:
                ax.hist(nt_vals, bins=50, color="#cccccc", alpha=0.6,
                        density=True, label="Other")
                ax.hist(t_vals, bins=50, color="#e6194b", alpha=0.6,
                        density=True, label=theme_name.title()[:15])
            ax.set_title(feat.replace("_", " ").title(), fontsize=9)
            ax.set_ylabel("Density")
            if idx == 0:
                ax.legend(fontsize=8)

        fig.suptitle(f"Feature Comparison: {theme_name.replace('_', ' ').title()} vs Rest",
                     fontsize=11)
        fig.tight_layout()
        save(fig, theme_dir, "discriminator_histograms")

    # 4. Theme co-occurrence for this theme.
    theme_subset = df_themes.filter(pl.col(theme_col))
    cooccur = {}
    for other_col in ALL_THEME_COLUMNS:
        if other_col != theme_col and other_col in theme_subset.columns:
            cnt = theme_subset[other_col].sum()
            if cnt > 0:
                cooccur[other_col.removeprefix("theme_")] = cnt

    if cooccur:
        fig, ax = plt.subplots(figsize=(8, max(4, len(cooccur) * 0.3)))
        sorted_co = sorted(cooccur.items(), key=lambda x: x[1], reverse=True)[:15]
        names = [n.replace("_", " ").title() for n, _ in sorted_co]
        vals = [v / n_theme * 100 for _, v in sorted_co]
        ax.barh(range(len(names)), vals, color="#4363d8")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=9)
        ax.set_xlabel("% of theme positions also in this theme")
        ax.set_title(f"Co-occurring themes for {theme_name.replace('_', ' ').title()}")
        fig.tight_layout()
        save(fig, theme_dir, "cooccurrence")

    return {"theme": theme_name, "count": n_theme, "pct": pct}


# ── Comparison grid ──────────────────────────────────────────────────

def plot_theme_comparison(
    themes: list[str],
    df_themes: pl.DataFrame,
    df_enr: pl.DataFrame,
    out_dir: Path,
) -> None:
    """Side-by-side comparison of multiple themes on key features."""
    features = ["eval_win", "move_played_error", "pip_count_diff",
                "gammon_threat", "longest_prime_p1", "num_checkers_back_p1"]
    features = [f for f in features if f in df_enr.columns]

    fig, axes = plt.subplots(len(features), 1, figsize=(12, 3.5 * len(features)))
    if len(features) == 1:
        axes = [axes]

    palette = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
               "#42d4f4", "#f032e6", "#bfef45"]

    for f_idx, feat in enumerate(features):
        ax = axes[f_idx]
        data_list, labels = [], []
        for t_idx, theme in enumerate(themes):
            tcol = f"theme_{theme}"
            if tcol not in df_themes.columns:
                continue
            ids = df_themes.filter(pl.col(tcol))["position_id"].to_list()
            vals = df_enr.filter(pl.col("position_id").is_in(ids))[feat].drop_nulls().to_numpy()
            if len(vals) > 5000:
                vals = np.random.default_rng(42).choice(vals, 5000, replace=False)
            if len(vals) > 0:
                data_list.append(vals)
                labels.append(theme.replace("_", " ").title()[:15])

        if data_list:
            bp = ax.boxplot(data_list, patch_artist=True, showfliers=False, vert=True)
            for i, patch in enumerate(bp["boxes"]):
                patch.set_facecolor(palette[i % len(palette)])
                patch.set_alpha(0.7)
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel(feat.replace("_", " ").title(), fontsize=9)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Theme Comparison — Feature Distributions", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, out_dir, "theme_comparison")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Theme position browser.")
    parser.add_argument("--enriched", required=True)
    parser.add_argument("--themes", required=True)
    parser.add_argument("--output", default="viz/positions")
    parser.add_argument("--sample", type=int, default=300000)
    parser.add_argument("--per-theme", type=int, default=20,
                        help="Positions to sample per theme for review")
    parser.add_argument("--only-themes", nargs="+", default=None,
                        help="Limit to these themes (without theme_ prefix)")
    args = parser.parse_args()

    out_dir = Path(args.output)

    # Load data.
    print(f"Loading themes (sample={args.sample:,}) ...")
    tcols = ["position_id", "primary_theme", "theme_count"] + ALL_THEME_COLUMNS
    df_themes = sample_parquet_dir(Path(args.themes), args.sample, columns=tcols)
    print(f"  {len(df_themes):,} rows")

    print("Loading enriched ...")
    ecols = ["position_id", "game_id", "move_number", "match_phase",
             "decision_type", "board_p1", "board_p2",
             "eval_equity", "eval_win", "move_played_error", "best_move",
             "pip_count_p1", "pip_count_p2", "pip_count_diff",
             "num_on_bar_p1", "num_on_bar_p2",
             "num_borne_off_p1", "num_borne_off_p2",
             "num_blots_p1", "num_blots_p2",
             "num_points_made_p1", "num_points_made_p2",
             "home_board_points_p1", "home_board_points_p2",
             "num_checkers_back_p1", "num_checkers_back_p2",
             "longest_prime_p1", "longest_prime_p2",
             "prime_location_p1", "back_anchor_p1",
             "num_builders_p1", "outfield_blots_p1",
             "gammon_threat", "gammon_risk", "net_gammon",
             "cube_leverage"]
    df_enr = sample_parquet_dir(Path(args.enriched), args.sample * 2, columns=ecols)
    # Match to theme set.
    common = set(df_themes["position_id"].to_list())
    df_enr = df_enr.filter(pl.col("position_id").is_in(list(common)))
    print(f"  {len(df_enr):,} enriched rows matched")

    # Determine themes to process.
    if args.only_themes:
        themes = args.only_themes
    else:
        themes = [c.removeprefix("theme_") for c in ALL_THEME_COLUMNS]

    stats = []
    for theme in themes:
        result = analyze_theme(theme, df_themes, df_enr, out_dir, args.per_theme)
        if result:
            stats.append(result)

    # Comparison grid (if multiple themes).
    if len(themes) > 1:
        active_themes = [s["theme"] for s in stats if s.get("count", 0) > 0][:8]
        if len(active_themes) >= 2:
            print("\nGenerating theme comparison ...")
            plot_theme_comparison(active_themes, df_themes, df_enr, out_dir)

    # Summary.
    if stats:
        summary = pl.DataFrame(stats)
        summary_path = out_dir / "theme_summary.csv"
        summary.write_csv(summary_path)
        print(f"\nSummary: {summary_path}")

    print(f"Done — outputs in {out_dir}/")


if __name__ == "__main__":
    main()
