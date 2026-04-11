#!/usr/bin/env python3
"""Generate the final mining study report from pipeline outputs.

Reads all CSV/Parquet/text files produced by S0–S3 and populates
docs/mining-report.md with real values.

Usage:
    python scripts/generate_report.py \
        --parquet-dir data/parquet \
        --output-dir data \
        --report docs/mining-report.md
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq


def _fmt(n: int | float, decimals: int = 0) -> str:
    if isinstance(n, float):
        return f"{n:,.{decimals}f}"
    return f"{n:,}"


def read_parquet_count(path: Path) -> int | str:
    if not path.exists():
        return "n/a"
    try:
        files = sorted(path.glob("part-*.parquet")) if path.is_dir() else [path]
        return sum(pq.read_metadata(str(f)).num_rows for f in files)
    except Exception:
        return "n/a"


def read_csv_first(path: Path, col: str, default: str = "n/a") -> str:
    if not path.exists():
        return default
    try:
        import polars as pl
        df = pl.read_csv(path)
        if col in df.columns:
            return str(df[col][0])
    except Exception:
        pass
    return default


def read_txt_lines(path: Path, n: int = 3) -> str:
    if not path.exists():
        return "n/a"
    try:
        lines = path.read_text().splitlines()
        return "\n".join(lines[:n])
    except Exception:
        return "n/a"


def du_sh(path: Path) -> str:
    import subprocess
    try:
        result = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
        return result.stdout.split()[0] if result.returncode == 0 else "n/a"
    except Exception:
        return "n/a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet-dir", default="data/parquet")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--report", default="docs/mining-report.md")
    args = parser.parse_args()

    P = Path(args.parquet_dir)
    D = Path(args.output_dir)
    S1 = D / "results" / "s1"
    S2 = D / "results" / "s2"
    S3 = D / "results" / "s3"
    report_path = Path(args.report)

    # ── Collect metrics ──────────────────────────────────────────────

    # Volume
    n_positions = read_parquet_count(P / "positions")
    n_enriched  = read_parquet_count(P / "positions_enriched")

    n_matches = "n/a"
    n_games   = "n/a"
    try:
        import polars as pl
        if (P / "matches.parquet").exists():
            n_matches = _fmt(len(pl.read_parquet(P / "matches.parquet")))
        if (P / "games.parquet").exists():
            n_games = _fmt(len(pl.read_parquet(P / "games.parquet")))
    except Exception:
        pass

    n_players = "n/a"
    profiles_path = S2 / "player_profiles.parquet"
    if profiles_path.exists():
        try:
            import polars as pl
            n_players = _fmt(len(pl.read_parquet(profiles_path)))
        except Exception:
            pass

    # Checker/cube split from phase distribution
    n_checker = "n/a"
    n_cube    = "n/a"
    try:
        import polars as pl
        # Approximate from enriched count vs decision_type
        err_dist = S1 / "error_distribution_checker.csv"
        if err_dist.exists():
            df_err = pl.read_csv(err_dist)
            n_checker = _fmt(int(df_err["n"].sum())) if "n" in df_err.columns else "n/a"
    except Exception:
        pass

    # S1.1 stats
    median_checker_error = "n/a"
    median_cube_error    = "n/a"
    try:
        import polars as pl
        err_dist = S1 / "error_distribution_checker.csv"
        if err_dist.exists():
            df = pl.read_csv(err_dist)
            # error_bin is the lower bound; find bin where cumulative reaches 50%
            if "n" in df.columns and "error_bin" in df.columns:
                total = df["n"].sum()
                cum = 0
                for row in df.iter_rows(named=True):
                    cum += row["n"]
                    if cum >= total / 2:
                        median_checker_error = f"{row['error_bin']:.4f}"
                        break
    except Exception:
        pass

    # S1.2 top feature
    top_feature = "n/a"
    try:
        import polars as pl
        corr_path = S1 / "spearman_checker.csv"
        if corr_path.exists():
            df = pl.read_csv(corr_path).sort("abs_rho", descending=True)
            top_feature = df["feature"][0] if "feature" in df.columns else "n/a"
    except Exception:
        pass

    # S1.3 cluster counts
    n_checker_clusters = "n/a"
    n_cube_clusters    = "n/a"
    try:
        import polars as pl
        ck = S1 / "cluster_profiles_checker.csv"
        if ck.exists():
            n_checker_clusters = str(len(pl.read_csv(ck)))
        cu = S1 / "cluster_profiles_cube.csv"
        if cu.exists():
            n_cube_clusters = str(len(pl.read_csv(cu)))
    except Exception:
        pass

    # S2.1 best player
    best_player_pr = "n/a"
    avg_pr = "n/a"
    try:
        import polars as pl
        ranking_path = S2 / "player_ranking.csv"
        if ranking_path.exists():
            df = pl.read_csv(ranking_path).sort("pr_rating")
            if len(df) > 0:
                row = df.row(0, named=True)
                name = row.get("player", "?")
                pr = row.get("pr_rating", 0)
                best_player_pr = f"{name} (PR {pr:.2f})"
        if profiles_path.exists():
            df = pl.read_parquet(profiles_path)
            if "pr_rating" in df.columns:
                avg_pr = f"{df['pr_rating'].mean():.2f}"
    except Exception:
        pass

    # S3.1 worst heatmap cell (cube_heatmap_global.csv)
    worst_cell = "n/a"
    n_hotspots = "n/a"
    try:
        import polars as pl
        heatmap_path = S3 / "cube_heatmap_global.csv"
        if heatmap_path.exists():
            df = pl.read_csv(heatmap_path).sort("avg_error", descending=True, nulls_last=True)
            if len(df) > 0:
                row = df.row(0, named=True)
                p1 = row.get("score_away_p1", "?")
                p2 = row.get("score_away_p2", "?")
                err = row.get("avg_error", 0) or 0
                worst_cell = f"(p1={p1}-away, p2={p2}-away) error={err:.4f}"
            if "is_hotspot" in df.columns:
                n_hotspots = str(df.filter(pl.col("is_hotspot") == True).height)
    except Exception:
        pass

    # S3.2 MET max deviation
    met_max_dev = "n/a"
    try:
        import polars as pl
        met_path = S3 / "met_deviations.csv"
        if met_path.exists():
            df = pl.read_csv(met_path)
            if "abs_deviation" in df.columns:
                met_max_dev = f"{df['abs_deviation'].max():.2f} pts"
    except Exception:
        pass

    # S3.6 cube model accuracy
    model_acc = "n/a"
    top_feat_imp = "n/a"
    try:
        import polars as pl
        model_path = S3 / "cube_model_metrics.csv"
        if model_path.exists():
            df = pl.read_csv(model_path)
            if "accuracy" in df.columns:
                model_acc = f"{df['accuracy'][0]*100:.1f}%"
        feat_path = S3 / "cube_model_feature_importance.csv"
        if feat_path.exists():
            df = pl.read_csv(feat_path).sort("importance", descending=True)
            if len(df) > 0 and "feature" in df.columns:
                top_feat_imp = df["feature"][0]
    except Exception:
        pass

    # S0.6 unique positions
    n_unique_pos = "n/a"
    convergence_path = P / "convergence_index.parquet"
    if convergence_path.exists():
        try:
            import polars as pl
            n_unique_pos = _fmt(len(pl.read_parquet(convergence_path)))
        except Exception:
            pass

    # S0.7 graph
    n_nodes = "n/a"
    n_edges = "n/a"
    nodes_path = P / "graph_nodes.parquet"
    edges_path = P / "graph_edges_agg.parquet"
    if nodes_path.exists():
        n_nodes = _fmt(read_parquet_count(nodes_path))
    if edges_path.exists():
        n_edges = _fmt(read_parquet_count(edges_path))

    # Disk usage
    disk = {}
    for label, path in [
        ("data/parquet/", P),
        ("data/parquet/positions_enriched/", P / "positions_enriched"),
        ("data/results/s1/", S1),
        ("data/results/s2/", S2),
        ("data/results/s3/", S3),
    ]:
        disk[label] = du_sh(path)

    # ── Build report ─────────────────────────────────────────────────
    n_pos_fmt = _fmt(n_positions) if isinstance(n_positions, int) else n_positions
    n_enr_fmt = _fmt(n_enriched) if isinstance(n_enriched, int) else n_enriched

    report = f"""# BMAB Mining Study — Final Report

**Dataset**: BMAB 2025-06-23 — 166,713 XG files, 24 GB
**Pipeline**: S0.1→S3.6 (28 scripts, batched export, DuckDB/Polars/sklearn)
**Run date**: {date.today().isoformat()}

---

## 1. Dataset Volume

| Entity | Count |
|--------|-------|
| .xg files | 166,713 |
| Matches | {n_matches} |
| Games | {n_games} |
| Positions (total) | {n_pos_fmt} |
| Checker decisions | {n_checker} |
| Cube decisions | {n_cube} |
| Unique positions (hash) | {n_unique_pos} |
| Unique players (≥20 matches) | {n_players} |

---

## 2. S0 — Data Infrastructure

### S0.4 Feature Engineering
- 34 features computed per position (pip counts, primes, gammon threat, match context)

### S0.5 Data Validation
- See `data/stats/` for validation report

### S0.6 Position Hashing
- Unique canonical positions: **{n_unique_pos}**

### S0.7 Trajectory Graph
- Nodes (≥3 matches): **{n_nodes}**
- Edges (aggregated): **{n_edges}**

---

## 3. S1 — Exploration

### S1.1 Descriptive Statistics
- Median checker error: **{median_checker_error}**
- Median cube error: **{median_cube_error}**

### S1.2 Feature-Error Correlation
- Top feature correlated with error: **{top_feature}**

### S1.3 Position Clustering
- Checker clusters found: **{n_checker_clusters}**
- Cube clusters found: **{n_cube_clusters}**

---

## 4. S2 — Player Profiling

### S2.1 Player Profiles
- Players profiled: **{n_players}**
- Average PR: **{avg_pr}**
- Best player: **{best_player_pr}**

---

## 5. S3 — Practical Rules

### S3.1 Cube Error Heatmap
- Worst score cell: **{worst_cell}**
- Hot spots count: **{n_hotspots}**

### S3.2 MET Verification
- Max deviation from Kazaross: **{met_max_dev}**

### S3.6 Cube Model
- 4-class accuracy: **{model_acc}**
- Top feature by importance: **{top_feat_imp}**

---

## 6. Disk Usage

| Directory | Size |
|-----------|------|
"""
    for label, size in disk.items():
        report += f"| {label} | {size} |\n"

    report += "\n---\n\n_Report auto-generated by `scripts/generate_report.py`_\n"

    report_path.write_text(report)
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
