#!/usr/bin/env python3
"""
BE.3 — 1-Away Crawford / Post-Crawford Cell Split

Reads barycentric_v2.parquet and produces:
  cell_keys.parquet   — canonical (score_p1, score_p2, crawford_variant) lookup
                        with display_label and is_one_away columns
  crawford_audit.txt  — data-quality report on variant counts, cube distribution,
                        anomalous rows, and per-match Crawford-game counts

The crawford_variant rules:
  - not 1-away                          → "normal"
  - 1-away AND crawford==True           → "crawford"
  - 1-away AND is_post_crawford==True   → "post_crawford"
  - 1-away AND both False               → "normal"  (anomalous; logged)

This mapping is also inlined in bootstrap_cells.py (BE.2) so that BE.2
and BE.3 can run independently. BE.3 is the authoritative source for the
canonical cell_keys table consumed by the query service (BE.4) and the
frontend (BE.6).

Usage
-----
  python scripts/compute_cell_keys.py \\
      --input  data/barycentric/barycentric_v2.parquet \\
      --output data/barycentric/cell_keys.parquet \\
      --audit  data/barycentric/crawford_audit.txt
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import polars as pl


# ---------------------------------------------------------------------------
# Variant derivation (canonical; mirrored in bootstrap_cells.py)
# ---------------------------------------------------------------------------

def add_crawford_variant(df: pl.DataFrame) -> pl.DataFrame:
    is_one_away = (
        (pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1)
    )
    variant = (
        pl.when(~is_one_away)
        .then(pl.lit("normal"))
        .when(pl.col("crawford"))
        .then(pl.lit("crawford"))
        .when(pl.col("is_post_crawford"))
        .then(pl.lit("post_crawford"))
        .otherwise(pl.lit("normal"))
    )
    return df.with_columns(
        variant.alias("crawford_variant"),
        is_one_away.alias("is_one_away"),
    )


def display_label(a: int, b: int, variant: str) -> str:
    base = f"{a}a-{b}a"
    if variant == "crawford":
        return f"{base} CRA"
    if variant == "post_crawford":
        return f"{base} PCR"
    return base


# ---------------------------------------------------------------------------
# Build cell_keys table
# ---------------------------------------------------------------------------

def build_cell_keys(df: pl.DataFrame) -> pl.DataFrame:
    """One row per distinct (score_away_p1, score_away_p2, crawford_variant)."""
    keys = (
        df.select([
            "score_away_p1", "score_away_p2",
            "crawford_variant", "is_one_away",
        ])
        .unique()
        .sort(["score_away_p1", "score_away_p2", "crawford_variant"])
    )

    # Stable cell_id string
    cell_id = (
        pl.lit("a") + pl.col("score_away_p1").cast(pl.Utf8)
        + pl.lit("_b") + pl.col("score_away_p2").cast(pl.Utf8)
        + pl.lit("_") + pl.col("crawford_variant")
    )
    keys = keys.with_columns(cell_id.alias("cell_id"))

    # display_label (vectorised via map_elements)
    labels = [
        display_label(row["score_away_p1"], row["score_away_p2"],
                      row["crawford_variant"])
        for row in keys.iter_rows(named=True)
    ]
    keys = keys.with_columns(pl.Series("display_label", labels))

    # Column order
    return keys.select([
        "cell_id", "score_away_p1", "score_away_p2",
        "crawford_variant", "display_label", "is_one_away",
    ])


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------

def write_audit(df: pl.DataFrame, path: Path, n_total: int) -> None:
    lines = [
        "BE.3 — Crawford / Post-Crawford Audit",
        "=" * 60, "",
        f"Total rows in barycentric_v2 : {n_total:,}", "",
    ]

    # 1. Positions per variant
    variant_counts = (
        df.group_by("crawford_variant")
        .agg(pl.len().alias("n"))
        .sort("crawford_variant")
    )
    lines.append("Positions per variant:")
    for row in variant_counts.iter_rows(named=True):
        pct = 100.0 * row["n"] / n_total
        lines.append(f"  {row['crawford_variant']:<16}: {row['n']:>10,}  ({pct:.2f}%)")
    lines.append("")

    # 2. Anomalous rows at 1-away (both flags false)
    one_away = df.filter(
        (pl.col("score_away_p1") == 1) | (pl.col("score_away_p2") == 1)
    )
    anomalous = one_away.filter(
        ~pl.col("crawford") & ~pl.col("is_post_crawford")
    )
    n_one_away = len(one_away)
    n_anomalous = len(anomalous)
    pct_anomalous = 100.0 * n_anomalous / max(n_one_away, 1)
    lines += [
        f"1-away rows total  : {n_one_away:,}",
        f"Anomalous (neither flag): {n_anomalous:,}  ({pct_anomalous:.2f}% of 1-away)",
    ]
    if pct_anomalous >= 1.0:
        lines.append("  [WARN] Anomalous rate >= 1% — check source pipeline flags.")
    lines.append("")

    # 3. Cube distribution per variant (only when cube_value present)
    if "cube_value" in df.columns:
        lines.append("Cube distribution per variant:")
        lines.append(f"  {'variant':<16}  {'cube=1':>8}  {'cube=2':>8}  "
                     f"{'cube=4':>8}  {'cube>=8':>8}  {'total':>8}")
        lines.append("  " + "-" * 58)
        for variant in ("normal", "crawford", "post_crawford"):
            sub = df.filter(pl.col("crawford_variant") == variant)
            if sub.is_empty():
                continue
            n_c1 = sub.filter(pl.col("cube_value") <= 1)["cube_value"].len()
            n_c2 = sub.filter(pl.col("cube_value") == 2)["cube_value"].len()
            n_c4 = sub.filter(pl.col("cube_value") == 4)["cube_value"].len()
            n_c8 = sub.filter(pl.col("cube_value") >= 8)["cube_value"].len()
            tot = len(sub)
            lines.append(f"  {variant:<16}  {n_c1:>8,}  {n_c2:>8,}  "
                         f"{n_c4:>8,}  {n_c8:>8,}  {tot:>8,}")
        lines.append("")

    # 4. Per-match Crawford-game count check (sample up to 500 matches)
    if "match_id" in df.columns:
        crawford_rows = df.filter(pl.col("crawford_variant") == "crawford")
        if not crawford_rows.is_empty():
            # Count distinct games per match that are crawford
            cra_games_per_match = (
                crawford_rows
                .group_by(["match_id"])
                .agg(pl.col("game_id").n_unique().alias("n_cra_games"))
            )
            n_matches = len(cra_games_per_match)
            # Matches with more than 1 Crawford game (data quality issue)
            over_one = cra_games_per_match.filter(
                pl.col("n_cra_games") > 1
            )
            lines += [
                f"Per-match Crawford-game check (all {n_matches:,} matches with CRA rows):",
                f"  Matches with == 1 Crawford game : "
                f"{n_matches - len(over_one):,}",
                f"  Matches with  > 1 Crawford game : {len(over_one):,}",
            ]
            if not over_one.is_empty():
                lines.append("  [WARN] Some matches have >1 Crawford game — "
                             "check match boundaries in games.parquet.")
            lines.append("")

    # 5. Cell count summary
    n_cells_normal = df.filter(
        pl.col("crawford_variant") == "normal"
    ).select(["score_away_p1", "score_away_p2"]).unique().height
    n_cells_cra = df.filter(
        pl.col("crawford_variant") == "crawford"
    ).select(["score_away_p1", "score_away_p2"]).unique().height
    n_cells_pcr = df.filter(
        pl.col("crawford_variant") == "post_crawford"
    ).select(["score_away_p1", "score_away_p2"]).unique().height

    lines += [
        "Distinct score cells per variant:",
        f"  normal        : {n_cells_normal}",
        f"  crawford      : {n_cells_cra}",
        f"  post_crawford : {n_cells_pcr}",
        f"  total cells   : {n_cells_normal + n_cells_cra + n_cells_pcr}",
        "",
    ]

    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="BE.3 — Compute canonical cell_keys.parquet")
    ap.add_argument("--input",
                    default="data/barycentric/barycentric_v2.parquet",
                    help="Input barycentric_v2 parquet")
    ap.add_argument("--output",
                    default="data/barycentric/cell_keys.parquet",
                    help="Output cell_keys parquet")
    ap.add_argument("--audit",
                    default="data/barycentric/crawford_audit.txt",
                    help="Audit text report")
    args = ap.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = Path(args.audit)

    print("=" * 60)
    print("  BE.3 — Crawford / Post-Crawford Cell Split")
    print("=" * 60)
    print(f"  input  : {args.input}")
    print(f"  output : {output_path}")
    print(f"  audit  : {audit_path}")

    t0 = time.time()

    # Load only needed columns for cell_keys; also load cube_value + match/game
    # ids for the audit if they exist.
    probe = pl.read_parquet(args.input, n_rows=1)
    audit_cols = ["cube_value", "match_id", "game_id"]
    needed = (
        ["score_away_p1", "score_away_p2", "crawford", "is_post_crawford"]
        + [c for c in audit_cols if c in probe.columns]
    )
    print("\n  Loading positions...")
    df = pl.read_parquet(args.input, columns=needed)
    n_total = len(df)
    print(f"  {n_total:,} rows ({time.time()-t0:.1f}s)")

    df = add_crawford_variant(df)

    # Build cell_keys
    cell_keys = build_cell_keys(df)
    print(f"\n  {len(cell_keys)} distinct cells")
    print(cell_keys.group_by("crawford_variant")
          .agg(pl.len().alias("n")).sort("crawford_variant").to_pandas()
          .to_string(index=False))

    # Uniqueness check
    dupes = len(cell_keys) - cell_keys.select(
        ["score_away_p1", "score_away_p2", "crawford_variant"]
    ).unique().height
    if dupes:
        print(f"  [ERROR] {dupes} duplicate (score, variant) combos — check logic")
    else:
        print("  Uniqueness check: OK")

    # Write cell_keys
    cell_keys.write_parquet(output_path)
    print(f"\n  -> {output_path}")

    # Write audit
    write_audit(df, audit_path, n_total)
    print(f"  -> {audit_path}")

    print(f"\n{'='*60}")
    print(f"  Done in {time.time()-t0:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
