#!/usr/bin/env python3
"""
S3.4 — Heuristics by Position Type

For each position cluster (S1.3), train a shallow decision tree (depth ≤ 4)
that predicts whether a player makes a significant error. Tree branches
produce interpretable rules describing *when* errors occur in each
position type, and are translated into plain-language heuristics.

Two tree targets
----------------
  blunder_target  : move_played_error > 0.080 (booleans — "when do blunders occur?")
  error_target    : move_played_error > 0.025 (non-trivial error)

Per cluster the script:
  1. Trains a DT on 80% train / 20% holdout
  2. Extracts all leaf-level rules (feature path + prediction)
  3. Translates each rule to a natural-language sentence
  4. Keeps only "danger rules" (predicted=blunder, precision > MIN_PRECISION)

Global analysis (all clusters combined) identifies universal danger patterns.

Outputs
-------
  <output>/heuristics.csv            cluster × rule × precision × support
  <output>/heuristics_report.txt     plain-language catalogue
  <output>/tree_feature_importance.csv  global feature importances

Usage
-----
  python scripts/extract_heuristics.py \\
      --enriched  data/parquet/positions_enriched \\
      --clusters  data/clusters/clusters_checker.parquet \\
      --output    data/cube_analysis \\
      [--sample 1000000] [--max-depth 4] [--min-support 50] [--min-precision 0.15]
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLUNDER_THR    = 0.080
ERROR_THR      = 0.025
MIN_CLUSTER_N  = 200     # minimum positions in a cluster to train a tree
MIN_PRECISION  = 0.15    # keep rules where precision (blunder rate) ≥ this
MIN_SUPPORT    = 50      # minimum leaf support to report a rule

FEATURES = [
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
    "gammon_threat", "gammon_risk",
    "cube_leverage",
]

# Human-readable feature labels for rule translation
FEATURE_LABELS = {
    "pip_count_p1":       "your pip count",
    "pip_count_p2":       "opponent pip count",
    "pip_count_diff":     "pip difference (you − opponent)",
    "num_blots_p1":       "your blots",
    "num_blots_p2":       "opponent blots",
    "num_points_made_p1": "your made points",
    "num_points_made_p2": "opponent made points",
    "home_board_points_p1": "your home-board points",
    "home_board_points_p2": "opponent home-board points",
    "home_board_strength_p1": "your home-board strength",
    "longest_prime_p1":   "your prime length",
    "longest_prime_p2":   "opponent prime length",
    "back_anchor_p1":     "your back-checker anchor point",
    "num_checkers_back_p1": "your back checkers",
    "num_builders_p1":    "your builders",
    "outfield_blots_p1":  "your outfield blots (pts 7-18)",
    "num_on_bar_p1":      "your checkers on bar",
    "num_on_bar_p2":      "opponent checkers on bar",
    "num_borne_off_p1":   "your borne-off checkers",
    "num_borne_off_p2":   "opponent borne-off checkers",
    "match_phase":        "match phase (0=contact, 1=race, 2=bearoff)",
    "gammon_threat":      "gammon threat",
    "gammon_risk":        "gammon risk",
    "cube_leverage":      "cube leverage",
}

PHASE_NAMES = {0: "contact", 1: "race", 2: "bearoff"}


def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_enriched(enriched_dir: str, sample: int) -> pl.DataFrame:
    want = list(dict.fromkeys(FEATURES + [
        "position_id", "decision_type", "move_played_error", "match_phase",
    ]))
    paths = sorted(Path(enriched_dir).glob("**/*.parquet"))
    if not paths:
        sys.exit(f"No parquet files in {enriched_dir}")

    frames, total = [], 0
    for p in paths:
        try:
            probe = pl.read_parquet(p, n_rows=1)
            cols  = [c for c in want if c in probe.columns]
            df    = pl.read_parquet(p, columns=cols)
        except Exception as exc:
            print(f"  [WARN] {p.name}: {exc}", file=sys.stderr)
            continue
        if "decision_type" in df.columns:
            df = df.filter(pl.col("decision_type") == "checker")
        if "move_played_error" in df.columns:
            df = df.filter(pl.col("move_played_error").is_not_null())
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No checker data found")
    combined = pl.concat(frames, how="diagonal")
    if len(combined) > sample:
        combined = combined.sample(n=sample, seed=42)
    return combined


def load_clusters(clusters_path: str) -> pl.DataFrame | None:
    p = Path(clusters_path)
    if not p.exists():
        print(f"  [WARN] Cluster file not found: {p}", file=sys.stderr)
        return None
    df = pl.read_parquet(p)
    if "cluster" in df.columns and "cluster_id" not in df.columns:
        df = df.rename({"cluster": "cluster_id"})
    return df


# ---------------------------------------------------------------------------
# Decision tree rule extraction
# ---------------------------------------------------------------------------

def extract_rules(tree: DecisionTreeClassifier,
                  feature_names: list[str],
                  class_names: list[str],
                  min_support: int,
                  min_precision: float) -> list[dict]:
    """
    Walk the tree and collect all leaf nodes that predict class_names[1]
    (= blunder) with precision ≥ min_precision and support ≥ min_support.
    Returns list of dicts: {conditions, prediction, precision, support, recall}.
    """
    from sklearn.tree import _tree

    t          = tree.tree_
    feat       = t.feature
    threshold  = t.threshold
    n_classes  = t.n_classes[0]

    rules = []

    def recurse(node: int, conditions: list[str]) -> None:
        if t.feature[node] == _tree.TREE_UNDEFINED:
            # Leaf
            values = t.value[node][0]
            support = int(values.sum())
            pred_class = int(np.argmax(values))
            precision  = float(values[pred_class] / support) if support > 0 else 0.0

            if (pred_class == 1          # predicts "blunder"
                    and precision >= min_precision
                    and support >= min_support):
                rules.append({
                    "conditions": list(conditions),
                    "prediction": class_names[pred_class],
                    "precision":  precision,
                    "support":    support,
                    "n_blunder":  int(values[1]) if n_classes > 1 else 0,
                })
            return

        fname = feature_names[feat[node]]
        thr   = threshold[node]

        # Left branch: feature <= threshold
        recurse(t.children_left[node], conditions + [f"{fname} ≤ {thr:.2f}"])
        # Right branch: feature > threshold
        recurse(t.children_right[node], conditions + [f"{fname} > {thr:.2f}"])

    recurse(0, [])
    return sorted(rules, key=lambda r: -r["precision"])


def rule_to_natural_language(rule: dict) -> str:
    """Convert a rule dict to a readable English sentence."""
    conds = []
    for cond in rule["conditions"]:
        # Parse "feature_name ≤/> value"
        for op in [" ≤ ", " > "]:
            if op in cond:
                feat, val_str = cond.split(op)
                feat   = feat.strip()
                val    = float(val_str)
                label  = FEATURE_LABELS.get(feat, feat)
                symbol = "≤" if op == " ≤ " else ">"

                # Special formatting for integer-valued features
                if feat in ("match_phase",):
                    if feat == "match_phase":
                        phase_val = int(val)
                        if symbol == "≤":
                            phase_str = "/".join(PHASE_NAMES[k] for k in range(phase_val + 1)
                                                 if k in PHASE_NAMES) or str(phase_val)
                            conds.append(f"phase in {{{phase_str}}}")
                        else:
                            conds.append(f"phase = bearoff")
                        break
                elif val == round(val) and abs(val) < 100:
                    conds.append(f"{label} {symbol} {int(val)}")
                else:
                    conds.append(f"{label} {symbol} {val:.2f}")
                break

    cond_str = " AND ".join(conds) if conds else "(unconditional)"
    pct      = rule["precision"] * 100
    sup      = rule["support"]
    return (f"IF {cond_str} → "
            f"blunder risk {pct:.1f}% (n={sup:,})")


# ---------------------------------------------------------------------------
# Training & evaluation
# ---------------------------------------------------------------------------

def train_cluster_tree(X: np.ndarray, y: np.ndarray,
                        feature_names: list[str],
                        max_depth: int,
                        min_support: int,
                        min_precision: float) -> tuple[DecisionTreeClassifier,
                                                        dict, list[dict]]:
    """Train DT, evaluate on holdout, extract rules."""
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if y.mean() > 0.02 else None
    )

    clf = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=min_support,
        class_weight="balanced",
        random_state=42,
    )
    clf.fit(X_tr, y_tr)
    y_pred = clf.predict(X_te)

    metrics = {
        "n_train": int(len(X_tr)),
        "n_test":  int(len(X_te)),
        "blunder_rate_train": float(y_tr.mean()),
        "blunder_rate_test":  float(y_te.mean()),
        "accuracy":  float((y_pred == y_te).mean()),
        "precision": float(precision_score(y_te, y_pred, zero_division=0)),
        "recall":    float(recall_score(y_te, y_pred, zero_division=0)),
        "f1":        float(f1_score(y_te, y_pred, zero_division=0)),
    }

    rules = extract_rules(clf, feature_names, ["no_blunder", "blunder"],
                          min_support=min_support, min_precision=min_precision)
    return clf, metrics, rules


# ---------------------------------------------------------------------------
# Phase-specific analysis
# ---------------------------------------------------------------------------

def phase_analysis(df: pl.DataFrame,
                   feature_names: list[str],
                   max_depth: int, min_support: int,
                   min_precision: float) -> dict[str, list[dict]]:
    """
    Train one tree per match phase (contact/race/bearoff) on the full dataset.
    Useful even without cluster labels.
    """
    if "match_phase" not in df.columns:
        return {}

    results = {}
    for phase_val, phase_name in PHASE_NAMES.items():
        sub = df.filter(pl.col("match_phase") == phase_val)
        if len(sub) < MIN_CLUSTER_N:
            continue

        avail = [f for f in feature_names if f in sub.columns and f != "match_phase"]
        X = sub.select(avail).fill_null(0).to_numpy().astype(np.float32)
        y = (sub["move_played_error"] >= BLUNDER_THR).to_numpy().astype(int)

        if y.mean() < 0.01:
            continue

        _, metrics, rules = train_cluster_tree(
            X, y, avail, max_depth, min_support, min_precision
        )
        results[phase_name] = {"metrics": metrics, "rules": rules}

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(cluster_rules: dict,
                 phase_rules: dict,
                 global_importance: pl.DataFrame,
                 output_path: Path) -> None:
    lines = [
        "S3.4 — Heuristics by Position Type",
        "=" * 64,
        "",
        "Rules are extracted from shallow decision trees (depth ≤ 4).",
        f"Target: blunder (error > {BLUNDER_THR:.3f}).",
        f"Minimum precision: {MIN_PRECISION*100:.0f}%  (population blunder rate ≈ baseline).",
        "",
    ]

    # Global feature importance
    if not global_importance.is_empty():
        lines += ["─" * 64, "Global Feature Importance (all positions)", ""]
        for row in global_importance.head(12).iter_rows(named=True):
            bar = "█" * min(int(row["importance"] * 200), 30)
            label = FEATURE_LABELS.get(row["feature"], row["feature"])
            lines.append(f"  {label:<36} {row['importance']:>6.4f}  {bar}")
        lines.append("")

    # Per-phase heuristics
    if phase_rules:
        lines += ["─" * 64, "Phase-Level Heuristics", ""]
        for phase, data in phase_rules.items():
            m = data["metrics"]
            lines.append(f"  ── {phase.upper()} ──")
            lines.append(f"     Baseline blunder rate : {m['blunder_rate_train']*100:.1f}%")
            lines.append(f"     Tree accuracy         : {m['accuracy']*100:.1f}%  "
                          f"(precision={m['precision']*100:.1f}%, recall={m['recall']*100:.1f}%)")
            if data["rules"]:
                lines.append(f"     Danger rules ({len(data['rules'])} found):")
                for rule in data["rules"][:5]:
                    lines.append(f"       • {rule_to_natural_language(rule)}")
            else:
                lines.append("     No high-precision danger rules found.")
            lines.append("")

    # Per-cluster heuristics
    if cluster_rules:
        lines += ["─" * 64, "Per-Cluster Heuristics", ""]
        for cluster_id, data in sorted(cluster_rules.items()):
            m = data["metrics"]
            lines.append(f"  ── Cluster {cluster_id} ──")
            lines.append(f"     N={m['n_train']+m['n_test']:,}  "
                          f"blunder rate={m['blunder_rate_train']*100:.1f}%  "
                          f"f1={m['f1']:.3f}")
            if data["rules"]:
                lines.append(f"     Danger rules ({len(data['rules'])} found):")
                for rule in data["rules"][:4]:
                    lines.append(f"       • {rule_to_natural_language(rule)}")
            else:
                lines.append("     No danger rules above threshold.")
            lines.append("")

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S3.4 — Heuristics by Position Type")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--clusters",
                    help="Path to clusters_checker.parquet (S1.3 output, optional)")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--sample", type=int, default=1_000_000,
                    help="Max positions to load (default: 1000000)")
    ap.add_argument("--max-depth", type=int, default=4,
                    help="Max decision tree depth (default: 4)")
    ap.add_argument("--min-support", type=int, default=50,
                    help="Min leaf support to report a rule (default: 50)")
    ap.add_argument("--min-precision", type=float, default=0.15,
                    help="Min blunder precision to keep a rule (default: 0.15)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  S3.4 — Heuristics by Position Type")
    print("=" * 64)
    print(f"  enriched    : {args.enriched}")
    print(f"  clusters    : {args.clusters or '(none — phase analysis only)'}")
    print(f"  output      : {output_dir}")
    print(f"  max-depth   : {args.max_depth}")
    print(f"  min-support : {args.min_support}")
    print(f"  min-precision: {args.min_precision}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    section("Loading enriched positions")
    pos = load_enriched(args.enriched, args.sample)
    print(f"  {len(pos):,} checker positions loaded ({time.time()-t0:.1f}s)")

    avail_features = [f for f in FEATURES if f in pos.columns]
    print(f"  Available features: {len(avail_features)} / {len(FEATURES)}")

    blunder_rate = float((pos["move_played_error"] >= BLUNDER_THR).mean())
    print(f"  Global blunder rate: {blunder_rate*100:.2f}%")

    # ------------------------------------------------------------------
    # Phase analysis (always run, no cluster file needed)
    # ------------------------------------------------------------------
    section("Phase-level heuristics (contact / race / bearoff)")
    phase_rules = phase_analysis(
        pos, avail_features, args.max_depth,
        args.min_support, args.min_precision
    )
    for phase, data in phase_rules.items():
        m = data["metrics"]
        n_rules = len(data["rules"])
        print(f"  {phase:<10} : N={m['n_train']+m['n_test']:>8,}  "
              f"blunder={m['blunder_rate_train']*100:.1f}%  "
              f"f1={m['f1']:.3f}  rules={n_rules}")
        for rule in data["rules"][:3]:
            print(f"    • {rule_to_natural_language(rule)}")

    # ------------------------------------------------------------------
    # Global tree (feature importance)
    # ------------------------------------------------------------------
    section("Global tree — feature importance")
    X_all = pos.select(avail_features).fill_null(0).to_numpy().astype(np.float32)
    y_all = (pos["move_played_error"] >= BLUNDER_THR).to_numpy().astype(int)

    global_clf = DecisionTreeClassifier(
        max_depth=args.max_depth,
        min_samples_leaf=args.min_support,
        class_weight="balanced",
        random_state=42,
    )
    global_clf.fit(X_all, y_all)
    importances = global_clf.feature_importances_

    importance_df = pl.DataFrame({
        "feature":    avail_features,
        "importance": importances.tolist(),
    }).sort("importance", descending=True)

    print(f"\n  Top-10 features predicting blunders (global):")
    print(f"  {'Feature':<36}  {'Importance':>10}")
    print("  " + "-" * 48)
    for row in importance_df.head(10).iter_rows(named=True):
        label = FEATURE_LABELS.get(row["feature"], row["feature"])
        print(f"  {label:<36}  {row['importance']:>10.4f}")

    # ------------------------------------------------------------------
    # Cluster-level trees
    # ------------------------------------------------------------------
    cluster_rules: dict = {}
    all_rule_rows: list[dict] = []

    if args.clusters:
        section("Per-cluster heuristics (S1.3 labels)")
        clusters = load_clusters(args.clusters)

        if clusters is not None and "position_id" in clusters.columns and \
                "position_id" in pos.columns:
            pos_with_cluster = pos.join(
                clusters.select(["position_id", "cluster_id"]),
                on="position_id",
                how="inner",
            ).filter(pl.col("cluster_id") >= 0)

            cluster_ids = sorted(pos_with_cluster["cluster_id"].unique().to_list())
            print(f"  {len(cluster_ids)} clusters, {len(pos_with_cluster):,} joined rows")

            for cid in cluster_ids:
                sub = pos_with_cluster.filter(pl.col("cluster_id") == cid)
                if len(sub) < MIN_CLUSTER_N:
                    continue

                feats = [f for f in avail_features if f in sub.columns]
                X = sub.select(feats).fill_null(0).to_numpy().astype(np.float32)
                y = (sub["move_played_error"] >= BLUNDER_THR).to_numpy().astype(int)

                if y.mean() < 0.005:
                    continue

                clf_c, metrics_c, rules_c = train_cluster_tree(
                    X, y, feats,
                    args.max_depth, args.min_support, args.min_precision
                )
                cluster_rules[cid] = {"metrics": metrics_c, "rules": rules_c}

                n_rules = len(rules_c)
                print(f"  Cluster {cid:>3} : N={len(sub):>8,}  "
                      f"blunder={metrics_c['blunder_rate_train']*100:.1f}%  "
                      f"f1={metrics_c['f1']:.3f}  rules={n_rules}")

                for rule in rules_c:
                    for i, cond in enumerate(rule["conditions"]):
                        all_rule_rows.append({
                            "cluster_id":  cid,
                            "rule_index":  rules_c.index(rule),
                            "condition_n": i,
                            "condition":   cond,
                            "precision":   rule["precision"],
                            "support":     rule["support"],
                            "n_blunder":   rule["n_blunder"],
                            "nl_rule":     rule_to_natural_language(rule),
                        })
        else:
            print("  [SKIP] No cluster file or position_id not in enriched data")

    # Phase rules → rows
    for phase, data in phase_rules.items():
        for rule in data["rules"]:
            all_rule_rows.append({
                "cluster_id":  f"phase_{phase}",
                "rule_index":  data["rules"].index(rule),
                "condition_n": 0,
                "condition":   "; ".join(rule["conditions"]),
                "precision":   rule["precision"],
                "support":     rule["support"],
                "n_blunder":   rule["n_blunder"],
                "nl_rule":     rule_to_natural_language(rule),
            })

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    if all_rule_rows:
        heuristics_df = pl.DataFrame(all_rule_rows)
        p = output_dir / "heuristics.csv"
        heuristics_df.write_csv(p)
        print(f"  → {p}  ({len(heuristics_df):,} rows)")

    p = output_dir / "tree_feature_importance.csv"
    importance_df.write_csv(p)
    print(f"  → {p}")

    report_path = output_dir / "heuristics_report.txt"
    write_report(cluster_rules, phase_rules, importance_df, report_path)
    print(f"  → {report_path}")

    # Print the report to stdout (first 80 lines)
    section("Heuristics catalogue (excerpt)")
    report_text = report_path.read_text()
    for line in report_text.split("\n")[:80]:
        print(f"  {line}")

    elapsed = time.time() - t0
    print(f"\n{'='*64}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
