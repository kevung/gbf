#!/usr/bin/env python3
"""
S2.4 — Individual Strengths/Weaknesses Analysis

For each player, identify specific strengths and weaknesses by comparing
their average error per position cluster (S1.3) and per away-score zone
to the global population average for the same cluster/zone.

Method
------
  1. Load positions_enriched (S0.4) + cluster labels (S1.3) + matches
  2. Resolve player names from (match_id, player_on_roll)
  3. Compute global avg error + std per cluster and per score zone
  4. Per player: avg error per cluster/zone → z-score vs population
  5. z > +1  → weakness (above-average error)
     z < -1  → strength (below-average error)
  6. Generate a plain-text report for each player (or a selected one)

Outputs
-------
  <output>/player_cluster_errors.parquet   player × cluster × error stats
  <output>/player_zone_errors.parquet      player × score_zone × error stats
  <output>/strengths_weaknesses.csv        player × dimension × z_score × label
  <output>/reports/<player>.txt            individual report per player

Usage
-----
  # Full run (all players)
  python scripts/analyze_strengths_weaknesses.py \\
      --enriched   data/parquet/positions_enriched \\
      --clusters   data/clusters/clusters_checker.parquet \\
      --parquet    data/parquet \\
      --profiles   data/player_profiles/player_profiles.parquet \\
      --output     data/player_profiles \\
      [--sample 5000000] [--min-positions 50] [--z-threshold 1.0]

  # Report for a single player
  python scripts/analyze_strengths_weaknesses.py ... --player "Alice"
"""

import argparse
import sys
import time
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ERROR_COL = "move_played_error"
STRENGTH_Z = -1.0    # z < this → strength
WEAKNESS_Z = +1.0    # z > this → weakness
MIN_N_CLUSTER = 10   # minimum positions in a cluster to report it

SCORE_ZONES = [
    ("DMP (2away-2away)",  "(away_p1 <= 2) & (away_p2 <= 2)"),
    ("GS (3away or less)", "((away_p1 <= 3) | (away_p2 <= 3)) & ~((away_p1 <= 2) & (away_p2 <= 2))"),
    ("4-5 away",           "((away_p1 <= 5) | (away_p2 <= 5)) & (away_p1 > 3) & (away_p2 > 3)"),
    ("6-9 away",           "((away_p1 <= 9) | (away_p2 <= 9)) & (away_p1 > 5) & (away_p2 > 5)"),
    ("10+ away (money)",   "(away_p1 > 9) & (away_p2 > 9)"),
]


def section(title: str) -> None:
    print(f"\n{'─'*62}")
    print(f"  {title}")
    print(f"{'─'*62}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_enriched(enriched_dir: str, sample: int) -> pl.DataFrame:
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    want = [
        "position_id", "game_id", "match_id", "player_on_roll",
        "decision_type", ERROR_COL,
        "score_away_p1", "score_away_p2",
        "match_phase",
    ]
    frames, total = [], 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols = [c for c in want if c in probe.columns]
            df = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "checker")
        if ERROR_COL in df.columns:
            df = df.filter(pl.col(ERROR_COL).is_not_null())
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No enriched checker data found")
    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def load_clusters(clusters_path: str) -> pl.DataFrame | None:
    p = Path(clusters_path)
    if not p.exists():
        print(f"  [WARN] Cluster file not found: {clusters_path}", file=sys.stderr)
        return None
    df = pl.read_parquet(p)
    # Normalise column name: 'cluster' or 'cluster_id'
    if "cluster" in df.columns and "cluster_id" not in df.columns:
        df = df.rename({"cluster": "cluster_id"})
    return df


def load_matches(parquet_dir: str) -> pl.DataFrame:
    p = Path(parquet_dir) / "matches.parquet"
    if not p.exists():
        sys.exit(f"matches.parquet not found in {parquet_dir}")
    return pl.read_parquet(p, columns=["match_id", "player1", "player2"])


def load_profiles(profiles_path: str) -> pl.DataFrame:
    p = Path(profiles_path)
    if not p.exists():
        return pl.DataFrame()
    return pl.read_parquet(p) if str(p).endswith(".parquet") else pl.read_csv(p)


# ---------------------------------------------------------------------------
# Player resolution
# ---------------------------------------------------------------------------

def resolve_player_names(pos: pl.DataFrame, matches: pl.DataFrame) -> pl.DataFrame:
    if "match_id" not in pos.columns:
        return pos.with_columns(pl.lit(None).cast(pl.String).alias("player"))
    m1 = matches.select([
        "match_id",
        pl.lit(1).cast(pl.Int8).alias("player_on_roll"),
        pl.col("player1").cast(pl.String).alias("player"),
    ])
    m2 = matches.select([
        "match_id",
        pl.lit(2).cast(pl.Int8).alias("player_on_roll"),
        pl.col("player2").cast(pl.String).alias("player"),
    ])
    lookup = pl.concat([m1, m2], how="vertical")
    if "player_on_roll" in pos.columns and pos["player_on_roll"].dtype != pl.Int8:
        pos = pos.with_columns(pl.col("player_on_roll").cast(pl.Int8))
    return pos.join(lookup, on=["match_id", "player_on_roll"], how="left")


# ---------------------------------------------------------------------------
# Cluster error analysis
# ---------------------------------------------------------------------------

def compute_global_cluster_stats(df: pl.DataFrame) -> pl.DataFrame:
    """Global avg error + std + count per cluster_id."""
    return (
        df.group_by("cluster_id")
        .agg([
            pl.len().alias("global_n"),
            pl.col(ERROR_COL).mean().alias("global_mean"),
            pl.col(ERROR_COL).std().alias("global_std"),
        ])
        .filter(pl.col("global_n") >= MIN_N_CLUSTER)
    )


def compute_player_cluster_errors(df: pl.DataFrame,
                                   min_positions: int) -> pl.DataFrame:
    """Per-player × per-cluster avg error."""
    return (
        df.group_by(["player", "cluster_id"])
        .agg([
            pl.len().alias("n"),
            pl.col(ERROR_COL).mean().alias("player_mean"),
        ])
        .filter(pl.col("n") >= min_positions)
    )


def compute_cluster_zscores(player_errors: pl.DataFrame,
                              global_stats: pl.DataFrame) -> pl.DataFrame:
    """Merge and compute z-score = (player_mean - global_mean) / global_std."""
    merged = player_errors.join(global_stats, on="cluster_id", how="inner")
    merged = merged.with_columns([
        pl.when(pl.col("global_std").is_null() | (pl.col("global_std") == 0))
        .then(pl.lit(0.0))
        .otherwise(
            (pl.col("player_mean") - pl.col("global_mean")) / pl.col("global_std")
        )
        .alias("z_score"),
    ])
    merged = merged.with_columns(
        pl.when(pl.col("z_score") >= WEAKNESS_Z).then(pl.lit("weakness"))
        .when(pl.col("z_score") <= STRENGTH_Z).then(pl.lit("strength"))
        .otherwise(pl.lit("average"))
        .alias("label")
    )
    return merged.sort(["player", "z_score"], descending=[False, True])


# ---------------------------------------------------------------------------
# Away-score zone analysis
# ---------------------------------------------------------------------------

def assign_score_zone(df: pl.DataFrame) -> pl.DataFrame:
    """Add a score_zone column from score_away_p1/p2."""
    if "score_away_p1" not in df.columns or "score_away_p2" not in df.columns:
        return df.with_columns(pl.lit("unknown").alias("score_zone"))

    p1 = pl.col("score_away_p1")
    p2 = pl.col("score_away_p2")

    return df.with_columns(
        pl.when((p1 <= 2) & (p2 <= 2))
        .then(pl.lit("DMP (2away-2away)"))
        .when((p1 <= 3) | (p2 <= 3))
        .then(pl.lit("GS (3away or less)"))
        .when((p1 <= 5) | (p2 <= 5))
        .then(pl.lit("4-5 away"))
        .when((p1 <= 9) | (p2 <= 9))
        .then(pl.lit("6-9 away"))
        .otherwise(pl.lit("10+ away (money)"))
        .alias("score_zone")
    )


def compute_global_zone_stats(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by("score_zone")
        .agg([
            pl.len().alias("global_n"),
            pl.col(ERROR_COL).mean().alias("global_mean"),
            pl.col(ERROR_COL).std().alias("global_std"),
        ])
        .filter(pl.col("global_n") >= MIN_N_CLUSTER)
    )


def compute_player_zone_errors(df: pl.DataFrame,
                                 min_positions: int) -> pl.DataFrame:
    return (
        df.group_by(["player", "score_zone"])
        .agg([
            pl.len().alias("n"),
            pl.col(ERROR_COL).mean().alias("player_mean"),
        ])
        .filter(pl.col("n") >= min_positions)
    )


def compute_zone_zscores(player_zone: pl.DataFrame,
                          global_zone: pl.DataFrame) -> pl.DataFrame:
    merged = player_zone.join(global_zone, on="score_zone", how="inner")
    merged = merged.with_columns([
        pl.when(pl.col("global_std").is_null() | (pl.col("global_std") == 0))
        .then(pl.lit(0.0))
        .otherwise(
            (pl.col("player_mean") - pl.col("global_mean")) / pl.col("global_std")
        )
        .alias("z_score"),
    ])
    merged = merged.with_columns(
        pl.when(pl.col("z_score") >= WEAKNESS_Z).then(pl.lit("weakness"))
        .when(pl.col("z_score") <= STRENGTH_Z).then(pl.lit("strength"))
        .otherwise(pl.lit("average"))
        .alias("label")
    )
    return merged.sort(["player", "z_score"], descending=[False, True])


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def player_report(player: str,
                   cluster_zscores: pl.DataFrame,
                   zone_zscores: pl.DataFrame,
                   profiles: pl.DataFrame,
                   has_clusters: bool) -> str:
    lines = [
        f"Strengths & Weaknesses Report — {player}",
        "=" * 62,
        "",
    ]

    # Overview from profiles
    if not profiles.is_empty():
        prow = profiles.filter(pl.col("player") == player)
        if not prow.is_empty():
            r = prow.row(0, named=True)
            lines.append("Overview")
            lines.append("-" * 40)
            for col, label in [
                ("pr_rating",         "PR Rating (×500 scale)"),
                ("avg_error_checker", "Avg checker error"),
                ("avg_error_cube",    "Avg cube error"),
                ("blunder_rate",      "Blunder rate"),
                ("error_std",         "Error std dev"),
                ("total_matches",     "Matches"),
                ("total_checker",     "Checker decisions"),
            ]:
                if col in r and r[col] is not None:
                    lines.append(f"  {label:<30} : {r[col]:>10.4f}" if isinstance(r[col], float)
                                 else f"  {label:<30} : {r[col]:>10}")
            lines.append("")

    # Phase profile
    if not profiles.is_empty():
        prow = profiles.filter(pl.col("player") == player)
        if not prow.is_empty():
            r = prow.row(0, named=True)
            phase_cols = [("avg_error_contact", "Contact"),
                          ("avg_error_race",    "Race"),
                          ("avg_error_bearoff", "Bearoff"),
                          ("avg_error_opening", "Opening (moves 1-10)"),
                          ("avg_error_midgame", "Midgame (11-30)"),
                          ("avg_error_endgame", "Endgame (31+)")]
            available = [(lbl, r[col]) for col, lbl in phase_cols
                         if col in r and r[col] is not None]
            if available:
                lines.append("Phase Profile")
                lines.append("-" * 40)
                for lbl, val in sorted(available, key=lambda x: x[1]):
                    bar = "▓" * min(int(val * 500), 20)
                    lines.append(f"  {lbl:<24} : {val:.4f}  {bar}")
                lines.append("")

    # Position cluster analysis
    if has_clusters:
        p_clusters = cluster_zscores.filter(pl.col("player") == player)
        if not p_clusters.is_empty():
            strengths = p_clusters.filter(pl.col("label") == "strength")
            weaknesses = p_clusters.filter(pl.col("label") == "weakness")
            lines.append("Position Cluster Analysis (vs population)")
            lines.append("-" * 40)
            lines.append(f"  {'Cluster':>8}  {'N':>6}  {'Player':>8}  "
                         f"{'Global':>8}  {'z-score':>8}  {'Label'}")
            lines.append("  " + "-" * 54)
            for row in p_clusters.iter_rows(named=True):
                flag = "★" if row["label"] == "strength" else "⚠" if row["label"] == "weakness" else " "
                lines.append(
                    f"  {row['cluster_id']:>8}  {row['n']:>6,}  "
                    f"{row['player_mean']:>8.4f}  "
                    f"{row['global_mean']:>8.4f}  "
                    f"{row['z_score']:>+8.2f}  {flag} {row['label']}"
                )
            lines.append("")
            if not strengths.is_empty():
                ids = strengths.select("cluster_id").to_series().to_list()
                lines.append(f"  ★ Strengths in clusters : {ids}")
            if not weaknesses.is_empty():
                ids = weaknesses.select("cluster_id").to_series().to_list()
                lines.append(f"  ⚠ Weaknesses in clusters: {ids}")
            lines.append("")

    # Score zone analysis
    p_zones = zone_zscores.filter(pl.col("player") == player)
    if not p_zones.is_empty():
        lines.append("Score Zone Analysis (vs population)")
        lines.append("-" * 40)
        lines.append(f"  {'Zone':<24}  {'N':>6}  {'Player':>8}  "
                     f"{'Global':>8}  {'z-score':>8}  {'Label'}")
        lines.append("  " + "-" * 68)
        for row in p_zones.iter_rows(named=True):
            flag = "★" if row["label"] == "strength" else "⚠" if row["label"] == "weakness" else " "
            lines.append(
                f"  {str(row['score_zone']):<24}  {row['n']:>6,}  "
                f"{row['player_mean']:>8.4f}  "
                f"{row['global_mean']:>8.4f}  "
                f"{row['z_score']:>+8.2f}  {flag} {row['label']}"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="S2.4 — Individual Strengths/Weaknesses Analysis")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--clusters",
                    help="Path to clusters_checker.parquet (S1.3 output)")
    ap.add_argument("--parquet", required=True,
                    help="Path to base Parquet dir (matches.parquet)")
    ap.add_argument("--profiles",
                    help="Path to player_profiles.parquet (S2.1 output)")
    ap.add_argument("--output", default="data/player_profiles",
                    help="Output directory")
    ap.add_argument("--player",
                    help="Generate report for a single player by name")
    ap.add_argument("--sample", type=int, default=5_000_000,
                    help="Max enriched rows to load (default: 5000000)")
    ap.add_argument("--min-positions", type=int, default=30,
                    help="Min positions per player×cluster cell (default: 30)")
    ap.add_argument("--z-threshold", type=float, default=1.0,
                    help="Z-score threshold for strength/weakness (default: 1.0)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(exist_ok=True)

    print("=" * 62)
    print("  S2.4 — Individual Strengths/Weaknesses Analysis")
    print("=" * 62)
    print(f"  enriched     : {args.enriched}")
    print(f"  clusters     : {args.clusters or '(none — cluster analysis skipped)'}")
    print(f"  parquet      : {args.parquet}")
    print(f"  output       : {output_dir}")
    print(f"  min-positions: {args.min_positions}")
    print(f"  z-threshold  : {args.z_threshold}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading data")
    matches = load_matches(args.parquet)
    print(f"  {len(matches):,} matches loaded")

    pos = load_enriched(args.enriched, args.sample)
    print(f"  {len(pos):,} checker positions loaded ({time.time()-t0:.1f}s)")

    pos = resolve_player_names(pos, matches)
    pos = pos.filter(pl.col("player").is_not_null())
    print(f"  {len(pos):,} rows with resolved player names")

    if args.player:
        pos = pos.filter(pl.col("player") == args.player)
        if pos.is_empty():
            sys.exit(f"Player '{args.player}' not found in data")
        print(f"  Filtered to player: {args.player}  ({len(pos):,} rows)")

    profiles = load_profiles(args.profiles) if args.profiles else pl.DataFrame()
    if not profiles.is_empty():
        print(f"  {len(profiles):,} player profiles loaded")

    # ------------------------------------------------------------------
    # Cluster analysis (optional, requires S1.3 output)
    # ------------------------------------------------------------------
    has_clusters = False
    cluster_zscores = pl.DataFrame()

    if args.clusters:
        section("Cluster-based analysis (S1.3 labels)")
        clusters = load_clusters(args.clusters)
        if clusters is not None and "position_id" in clusters.columns:
            # Join positions with cluster labels
            if "position_id" in pos.columns:
                pos_with_cluster = pos.join(
                    clusters.select(["position_id", "cluster_id"]),
                    on="position_id",
                    how="inner",
                )
                print(f"  Joined {len(pos_with_cluster):,} positions with cluster labels")

                # Remove noise cluster (-1)
                pos_with_cluster = pos_with_cluster.filter(pl.col("cluster_id") >= 0)

                global_cluster = compute_global_cluster_stats(pos_with_cluster)
                print(f"  {len(global_cluster):,} clusters in global stats")

                player_cluster = compute_player_cluster_errors(
                    pos_with_cluster, args.min_positions)
                print(f"  {len(player_cluster):,} player×cluster cells (min {args.min_positions} positions)")

                cluster_zscores = compute_cluster_zscores(player_cluster, global_cluster)
                has_clusters = True

                section("Cluster z-score summary (population)")
                n_strengths = (cluster_zscores["label"] == "strength").sum()
                n_weaknesses = (cluster_zscores["label"] == "weakness").sum()
                print(f"  Strength signals  : {n_strengths:,}")
                print(f"  Weakness signals  : {n_weaknesses:,}")
            else:
                print("  [SKIP] position_id not in enriched data — cannot join clusters")
        else:
            print("  [SKIP] Cluster file missing or no position_id column")
    else:
        section("Cluster analysis")
        print("  [SKIP] No --clusters path provided")

    # ------------------------------------------------------------------
    # Away-score zone analysis
    # ------------------------------------------------------------------
    section("Score zone analysis")
    pos_zoned = assign_score_zone(pos)
    global_zone = compute_global_zone_stats(pos_zoned)
    print(f"  {len(global_zone):,} score zones in global stats")

    player_zone = compute_player_zone_errors(pos_zoned, args.min_positions)
    print(f"  {len(player_zone):,} player×zone cells")

    zone_zscores = compute_zone_zscores(player_zone, global_zone)

    section("Zone z-score summary")
    print(f"  {'Zone':<24}  {'Global avg':>10}  {'N (global)':>12}")
    print("  " + "-" * 50)
    for row in global_zone.sort("score_zone").iter_rows(named=True):
        print(f"  {str(row['score_zone']):<24}  {row['global_mean']:>10.4f}  "
              f"{row['global_n']:>12,}")

    # ------------------------------------------------------------------
    # Save aggregate tables
    # ------------------------------------------------------------------
    section("Saving aggregate outputs")

    if has_clusters and not cluster_zscores.is_empty():
        p = output_dir / "player_cluster_errors.parquet"
        cluster_zscores.write_parquet(p)
        print(f"  → {p}  ({len(cluster_zscores):,} rows)")

    if not zone_zscores.is_empty():
        p = output_dir / "player_zone_errors.parquet"
        zone_zscores.write_parquet(p)
        print(f"  → {p}  ({len(zone_zscores):,} rows)")

    # Combined long-format strengths/weaknesses
    rows = []
    if has_clusters and not cluster_zscores.is_empty():
        for row in cluster_zscores.iter_rows(named=True):
            rows.append({
                "player": row["player"],
                "dimension_type": "cluster",
                "dimension": str(row["cluster_id"]),
                "n": row["n"],
                "player_mean": row["player_mean"],
                "global_mean": row["global_mean"],
                "z_score": row["z_score"],
                "label": row["label"],
            })
    for row in zone_zscores.iter_rows(named=True):
        rows.append({
            "player": row["player"],
            "dimension_type": "score_zone",
            "dimension": row["score_zone"],
            "n": row["n"],
            "player_mean": row["player_mean"],
            "global_mean": row["global_mean"],
            "z_score": row["z_score"],
            "label": row["label"],
        })

    if rows:
        sw_df = pl.DataFrame(rows).sort(["player", "dimension_type", "z_score"],
                                         descending=[False, False, True])
        p = output_dir / "strengths_weaknesses.csv"
        sw_df.write_csv(p)
        print(f"  → {p}  ({len(sw_df):,} rows)")

    # ------------------------------------------------------------------
    # Generate per-player reports
    # ------------------------------------------------------------------
    section("Generating player reports")

    if args.player:
        target_players = [args.player]
    else:
        # All players present in zone data (more permissive than clusters)
        target_players = zone_zscores.select("player").unique().to_series().to_list()

    print(f"  Generating {len(target_players):,} reports...")
    for player in sorted(target_players):
        text = player_report(
            player, cluster_zscores, zone_zscores, profiles, has_clusters)
        # Sanitise filename
        safe_name = "".join(c if c.isalnum() or c in " -_." else "_" for c in player)
        report_path = reports_dir / f"{safe_name}.txt"
        report_path.write_text(text)

    print(f"  → {reports_dir}/  ({len(target_players):,} .txt files)")

    # Show sample for the first player (or --player if specified)
    if target_players:
        sample_player = args.player if args.player else sorted(target_players)[0]
        section(f"Sample report — {sample_player}")
        text = player_report(
            sample_player, cluster_zscores, zone_zscores, profiles, has_clusters)
        # Print first 40 lines
        for line in text.split("\n")[:40]:
            print(f"  {line}")
        if len(text.split("\n")) > 40:
            print(f"  ... (see {reports_dir}/{sample_player}.txt for full report)")

    elapsed = time.time() - t0
    print(f"\n{'='*62}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
