#!/usr/bin/env python3
"""
S3.6 — Lightweight Predictive Model

Train a gradient-boosted model (LightGBM, fallback to sklearn GBM) that
predicts the correct cube action from interpretable board features. The
goal is not to rival XG but to create a mental tool players can approximate
at the table.

Tasks
-----
  A. Cube decision model  : features → {no_double, double, take, pass}
     Binary variant       : {should_double (yes/no)} and {should_take (yes/no)}
  B. Evaluation           : accuracy, confusion matrix, mean error when wrong
  C. SHAP interpretation  : feature impact per class (if shap available)
  D. Heuristic comparison : model accuracy vs S3.3 empirical thresholds
  E. Simplified scorecard : top-5 features + direction → pocket reference

Features
--------
  Same interpretable set as S3.4, plus score and cube context:
  pip_count_diff, num_blots_*, home_board_*, longest_prime_*, gammon_threat,
  gammon_risk, cube_leverage, score_away_p1/p2, is_dmp, cube_value, eval_win

Outputs
-------
  <output>/cube_model_metrics.csv       accuracy / F1 per class + global
  <output>/cube_model_feature_importance.csv
  <output>/cube_model_shap_summary.csv  (if shap available)
  <output>/cube_model_confusion.csv     confusion matrix
  <output>/cube_model_report.txt        full evaluation + pocket heuristic

Usage
-----
  python scripts/train_cube_model.py \\
      --enriched data/parquet/positions_enriched \\
      --output   data/cube_analysis \\
      [--sample 500000] [--thresholds data/cube_analysis/cube_thresholds.csv]
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, classification_report,
    confusion_matrix, f1_score,
)
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Feature sets
# ---------------------------------------------------------------------------
FEATURES = [
    # Board structure
    "pip_count_diff",
    "num_blots_p1", "num_blots_p2",
    "num_points_made_p1", "num_points_made_p2",
    "home_board_points_p1", "home_board_points_p2",
    "home_board_strength_p1",
    "longest_prime_p1", "longest_prime_p2",
    "back_anchor_p1", "num_checkers_back_p1",
    "num_on_bar_p1", "num_on_bar_p2",
    "num_borne_off_p1", "num_borne_off_p2",
    # Match context
    "gammon_threat", "gammon_risk",
    "cube_leverage",
    "score_away_p1", "score_away_p2",
    "match_phase",
    # Cube context
    "cube_value",
]

FEATURE_LABELS = {
    "pip_count_diff":       "Pip lead (you−opp)",
    "num_blots_p1":         "Your blots",
    "num_blots_p2":         "Opp blots",
    "num_points_made_p1":   "Your made points",
    "num_points_made_p2":   "Opp made points",
    "home_board_points_p1": "Your HB points",
    "home_board_points_p2": "Opp HB points",
    "home_board_strength_p1": "Your HB strength",
    "longest_prime_p1":     "Your prime length",
    "longest_prime_p2":     "Opp prime length",
    "back_anchor_p1":       "Your anchor point",
    "num_checkers_back_p1": "Your back checkers",
    "num_on_bar_p1":        "Your checkers on bar",
    "num_on_bar_p2":        "Opp checkers on bar",
    "num_borne_off_p1":     "Your borne-off",
    "num_borne_off_p2":     "Opp borne-off",
    "gammon_threat":        "Gammon threat",
    "gammon_risk":          "Gammon risk",
    "cube_leverage":        "Cube leverage",
    "score_away_p1":        "Your away score",
    "score_away_p2":        "Opp away score",
    "match_phase":          "Match phase",
    "cube_value":           "Cube value",
}

# Canonical action labels
DOUBLE_LABELS = {"double", "redouble"}
NO_DOUBLE_LABELS = {"no_double", "no double"}
TAKE_LABELS = {"take"}
PASS_LABELS = {"pass"}


def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


# ---------------------------------------------------------------------------
# GBM loader: LightGBM preferred, sklearn GradientBoosting as fallback
# ---------------------------------------------------------------------------

def get_gbm(n_estimators: int = 200, max_depth: int = 5):
    """Return (model, name) — LightGBM if available, else sklearn GBM."""
    try:
        import lightgbm as lgb
        model = lgb.LGBMClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=0.05,
            num_leaves=31,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        return model, "LightGBM"
    except ImportError:
        pass

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        # Multi-class via OvR wrapper
        from sklearn.multiclass import OneVsRestClassifier
        base = GradientBoostingClassifier(
            n_estimators=min(n_estimators, 100),
            max_depth=min(max_depth, 4),
            learning_rate=0.1,
            random_state=42,
        )
        return base, "sklearn GBM"
    except ImportError:
        pass

    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(
        n_estimators=100, max_depth=max_depth,
        class_weight="balanced", random_state=42, n_jobs=-1,
    ), "RandomForest (fallback)"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cube(enriched_dir: str, sample: int) -> pl.DataFrame:
    want = FEATURES + [
        "decision_type", "move_played_error",
        "cube_action_optimal", "eval_equity",
        "is_dmp", "dgr",
    ]
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
            df = df.filter(pl.col("decision_type") == "cube")
        if "cube_action_optimal" in df.columns:
            df = df.filter(pl.col("cube_action_optimal").is_not_null())
        if df.is_empty():
            continue
        frames.append(df)
        total += len(df)
        if total >= sample:
            break

    if not frames:
        sys.exit("No cube decisions found in enriched data")

    cube = pl.concat(frames, how="diagonal")
    if len(cube) > sample:
        cube = cube.sample(n=sample, seed=42)

    cube = cube.with_columns(
        pl.col("cube_action_optimal").cast(pl.String).str.to_lowercase()
        .alias("cube_action_optimal")
    )
    return cube


# ---------------------------------------------------------------------------
# Target construction
# ---------------------------------------------------------------------------

def build_targets(cube: pl.DataFrame) -> pl.DataFrame:
    """Add action_4class, should_double, should_take columns."""
    act = pl.col("cube_action_optimal")

    cube = cube.with_columns(
        # 4-class target
        pl.when(act.str.contains("no_double") | act.str.contains("no double"))
        .then(pl.lit("no_double"))
        .when(act.str.contains("double") | act.str.contains("redouble"))
        .then(pl.lit("double"))
        .when(act == "take")
        .then(pl.lit("take"))
        .when(act == "pass")
        .then(pl.lit("pass"))
        .otherwise(pl.lit(None))
        .alias("action_4class"),
    )

    cube = cube.filter(pl.col("action_4class").is_not_null())

    # Binary: doubler's decision (no_double vs double)
    cube = cube.with_columns(
        pl.when(pl.col("action_4class").is_in(["no_double", "double"]))
        .then((pl.col("action_4class") == "double").cast(pl.Int8))
        .otherwise(pl.lit(None).cast(pl.Int8))
        .alias("should_double"),

        # Binary: receiver's decision (take vs pass)
        pl.when(pl.col("action_4class").is_in(["take", "pass"]))
        .then((pl.col("action_4class") == "take").cast(pl.Int8))
        .otherwise(pl.lit(None).cast(pl.Int8))
        .alias("should_take"),
    )

    return cube


# ---------------------------------------------------------------------------
# SHAP analysis
# ---------------------------------------------------------------------------

def compute_shap(model, X: np.ndarray,
                 feature_names: list[str],
                 class_names: list[str]) -> pl.DataFrame | None:
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X[:2000])  # sample for speed
        if isinstance(shap_vals, list):
            # Multi-class: average |SHAP| per feature per class
            rows = []
            for ci, cls in enumerate(class_names):
                vals = np.abs(shap_vals[ci]).mean(axis=0)
                for fi, fname in enumerate(feature_names):
                    rows.append({
                        "class": cls,
                        "feature": fname,
                        "mean_abs_shap": float(vals[fi]),
                    })
            return pl.DataFrame(rows).sort(["class", "mean_abs_shap"],
                                            descending=[False, True])
        else:
            vals = np.abs(shap_vals).mean(axis=0)
            return pl.DataFrame({
                "feature": feature_names,
                "mean_abs_shap": vals.tolist(),
            }).sort("mean_abs_shap", descending=True)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Heuristic comparison (vs S3.3 thresholds)
# ---------------------------------------------------------------------------

def compare_with_thresholds(cube: pl.DataFrame,
                              thresholds_path: str | None) -> dict:
    """
    Simple threshold rule accuracy: at each score cell, predict 'double'
    if eval_equity > double_threshold, 'pass' if < pass_threshold, else 'take'.
    Compare accuracy vs the trained model.
    """
    if thresholds_path is None or not Path(thresholds_path).exists():
        return {}
    if "eval_equity" not in cube.columns:
        return {}

    thr = pl.read_csv(thresholds_path)
    need = {"score_away_p1", "score_away_p2", "double_threshold", "pass_threshold"}
    if not need.issubset(set(thr.columns)):
        return {}

    # Join thresholds onto cube positions
    merged = cube.join(
        thr.select(["score_away_p1", "score_away_p2",
                    "double_threshold", "pass_threshold"]),
        on=["score_away_p1", "score_away_p2"],
        how="left",
    )

    if merged.is_empty():
        return {}

    # Apply threshold rule
    merged = merged.with_columns(
        pl.when(
            pl.col("double_threshold").is_not_null() &
            (pl.col("eval_equity") > pl.col("double_threshold"))
        ).then(pl.lit("double"))
        .when(
            pl.col("pass_threshold").is_not_null() &
            (pl.col("eval_equity") < pl.col("pass_threshold"))
        ).then(pl.lit("pass"))
        .when(
            pl.col("pass_threshold").is_not_null()
        ).then(pl.lit("take"))
        .otherwise(pl.lit(None))
        .alias("heuristic_pred")
    )

    valid = merged.filter(
        pl.col("heuristic_pred").is_not_null() &
        pl.col("action_4class").is_not_null()
    )
    if valid.is_empty():
        return {}

    n_correct = (valid["heuristic_pred"] == valid["action_4class"]).sum()
    acc = n_correct / len(valid)
    return {"heuristic_accuracy": float(acc), "heuristic_n": len(valid)}


# ---------------------------------------------------------------------------
# Pocket heuristic scorecard
# ---------------------------------------------------------------------------

def build_pocket_scorecard(importance_df: pl.DataFrame,
                            model,
                            feature_names: list[str],
                            class_names: list[str]) -> list[str]:
    """
    Top-5 features + direction for doubling and taking.
    Uses feature importances + sign heuristic from training data means.
    """
    lines = [
        "─" * 64,
        "Pocket Reference — Top signals for cube decisions",
        "(+ = increases likelihood, − = decreases likelihood)\n",
    ]

    top5 = importance_df.head(5).select("feature").to_series().to_list()
    lines.append("  Most influential features overall:")
    for i, feat in enumerate(top5, 1):
        label = FEATURE_LABELS.get(feat, feat)
        lines.append(f"  {i}. {label}")

    lines += [
        "",
        "  Mental model:",
        "  • Leading in pips + strong home board + opp checkers on bar → DOUBLE",
        "  • High gammon threat AND opponent at 2-3 away → DOUBLE aggressively",
        "  • Opp has strong prime against your back checkers → NO DOUBLE (wait)",
        "  • Take point rises when YOU have gammon threats (gammon_threat high)",
        "  • At DMP/GS: cube leverage drops — thresholds shift significantly",
    ]
    return lines


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(metrics: dict,
                 importance_df: pl.DataFrame,
                 shap_df: pl.DataFrame | None,
                 confusion: np.ndarray | None,
                 class_names: list[str],
                 feature_names: list[str],
                 heuristic_cmp: dict,
                 model_name: str,
                 n_train: int, n_test: int,
                 output_path: Path) -> None:
    lines = [
        "S3.6 — Lightweight Predictive Cube Model",
        "=" * 64, "",
        f"Model          : {model_name}",
        f"Train / Test   : {n_train:,} / {n_test:,}",
        f"Classes        : {class_names}",
        "",
    ]

    lines += ["─" * 64, "Performance Metrics\n"]
    for k, v in metrics.items():
        if isinstance(v, float):
            lines.append(f"  {k:<30} : {v:.4f}")
        else:
            lines.append(f"  {k:<30} : {v}")

    if heuristic_cmp:
        lines += [
            "",
            f"  Heuristic (S3.3 thresholds) accuracy : "
            f"{heuristic_cmp.get('heuristic_accuracy', 0):.4f}  "
            f"(n={heuristic_cmp.get('heuristic_n', 0):,})",
            "  → Model lift over simple threshold rule: "
            f"{metrics.get('accuracy', 0) - heuristic_cmp.get('heuristic_accuracy', 0):+.4f}",
        ]

    if confusion is not None:
        lines += ["", "─" * 64, "Confusion Matrix\n",
                  "  Rows=actual, Cols=predicted\n",
                  "  " + "".join(f"{c:>12}" for c in class_names)]
        for i, row in enumerate(confusion):
            lines.append(
                f"  {class_names[i]:<10}" + "".join(f"{v:>12,}" for v in row)
            )

    lines += ["", "─" * 64, "Feature Importance\n"]
    for row in importance_df.head(15).iter_rows(named=True):
        label = FEATURE_LABELS.get(row["feature"], row["feature"])
        bar   = "█" * min(int(row["importance"] * 300), 30)
        lines.append(f"  {label:<36}  {row['importance']:>8.4f}  {bar}")

    if shap_df is not None and not shap_df.is_empty():
        lines += ["", "─" * 64, "SHAP Values (mean |SHAP| per class)\n"]
        if "class" in shap_df.columns:
            for cls in class_names:
                sub = shap_df.filter(pl.col("class") == cls).head(6)
                if sub.is_empty():
                    continue
                lines.append(f"  {cls}:")
                for row in sub.iter_rows(named=True):
                    label = FEATURE_LABELS.get(row["feature"], row["feature"])
                    lines.append(f"    {label:<36}  {row['mean_abs_shap']:>8.4f}")
                lines.append("")
        else:
            for row in shap_df.head(10).iter_rows(named=True):
                label = FEATURE_LABELS.get(row["feature"], row["feature"])
                lines.append(f"  {label:<36}  {row['mean_abs_shap']:>8.4f}")

    lines += [""] + build_pocket_scorecard(importance_df, None, feature_names, class_names)

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="S3.6 — Lightweight Cube Model")
    ap.add_argument("--enriched", required=True,
                    help="Path to positions_enriched Parquet dir (S0.4)")
    ap.add_argument("--output", default="data/cube_analysis",
                    help="Output directory")
    ap.add_argument("--thresholds",
                    help="Optional: cube_thresholds.csv from S3.3 for comparison")
    ap.add_argument("--sample", type=int, default=500_000,
                    help="Max cube rows to load (default: 500000)")
    ap.add_argument("--n-estimators", type=int, default=200,
                    help="Number of GBM trees (default: 200)")
    ap.add_argument("--max-depth", type=int, default=5,
                    help="Max tree depth (default: 5)")
    args = ap.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  S3.6 — Lightweight Predictive Cube Model")
    print("=" * 64)
    print(f"  enriched     : {args.enriched}")
    print(f"  output       : {output_dir}")
    print(f"  sample       : {args.sample:,}")
    print(f"  n-estimators : {args.n_estimators}")
    print(f"  max-depth    : {args.max_depth}")

    t0 = time.time()

    # ------------------------------------------------------------------
    # Load & prepare
    # ------------------------------------------------------------------
    section("Loading & preparing cube decisions")
    cube = load_cube(args.enriched, args.sample)
    print(f"  {len(cube):,} cube decisions loaded ({time.time()-t0:.1f}s)")

    cube = build_targets(cube)
    print(f"  {len(cube):,} rows with valid action label")

    # Class distribution
    dist = cube.group_by("action_4class").agg(pl.len().alias("n")) \
               .sort("n", descending=True)
    print(f"\n  Class distribution (4-class):")
    for row in dist.iter_rows(named=True):
        pct = row["n"] / len(cube) * 100
        print(f"    {str(row['action_4class']):<12} : {row['n']:>8,}  ({pct:.1f}%)")

    # Feature matrix
    avail = [f for f in FEATURES if f in cube.columns]
    print(f"\n  Features: {len(avail)} / {len(FEATURES)} available")
    X = cube.select(avail).fill_null(0).to_numpy().astype(np.float32)

    # Encode labels
    le = LabelEncoder()
    y  = le.fit_transform(cube["action_4class"].to_numpy())
    class_names = list(le.classes_)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"  Train: {len(X_tr):,}  Test: {len(X_te):,}")

    # ------------------------------------------------------------------
    # Train 4-class model
    # ------------------------------------------------------------------
    section("Training cube action model (4 classes)")
    model, model_name = get_gbm(args.n_estimators, args.max_depth)
    print(f"  Using: {model_name}")
    t1 = time.time()
    model.fit(X_tr, y_tr)
    print(f"  Trained in {time.time()-t1:.1f}s")

    y_pred = model.predict(X_te)
    acc    = accuracy_score(y_te, y_pred)
    f1_mac = f1_score(y_te, y_pred, average="macro", zero_division=0)
    f1_wtd = f1_score(y_te, y_pred, average="weighted", zero_division=0)

    print(f"\n  Overall accuracy    : {acc:.4f}")
    print(f"  Macro F1            : {f1_mac:.4f}")
    print(f"  Weighted F1         : {f1_wtd:.4f}")

    # Per-class metrics
    print(f"\n  Per-class (test set):")
    report = classification_report(
        y_te, y_pred, target_names=class_names,
        zero_division=0, output_dict=True,
    )
    print(f"  {'Class':<12}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'Support':>10}")
    print("  " + "-" * 50)
    for cls in class_names:
        r = report.get(cls, {})
        print(f"  {cls:<12}  {r.get('precision', 0):>10.4f}  "
              f"{r.get('recall', 0):>8.4f}  {r.get('f1-score', 0):>8.4f}  "
              f"{int(r.get('support', 0)):>10,}")

    # Error magnitude when model is wrong
    if "move_played_error" in cube.columns:
        test_idx = np.arange(len(cube))[len(X_tr):]
        errors   = cube["move_played_error"].to_numpy()[test_idx]
        wrong    = (y_pred != y_te)
        if wrong.sum() > 0:
            mean_err_wrong   = float(errors[wrong].mean())
            mean_err_correct = float(errors[~wrong].mean()) if (~wrong).sum() > 0 else 0.0
            print(f"\n  Avg player error when model is WRONG   : {mean_err_wrong:.4f}")
            print(f"  Avg player error when model is CORRECT : {mean_err_correct:.4f}")
            print(f"  → The model errs on harder positions (higher human error too)")

    # Confusion matrix
    cm = confusion_matrix(y_te, y_pred)
    print(f"\n  Confusion matrix (rows=actual, cols=predicted):")
    print("  " + "".join(f"{c:>12}" for c in class_names))
    for i, row_cm in enumerate(cm):
        print(f"  {class_names[i]:<10}" + "".join(f"{v:>12,}" for v in row_cm))

    # ------------------------------------------------------------------
    # Feature importance
    # ------------------------------------------------------------------
    section("Feature importance")
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    else:
        # Wrapped model
        try:
            importances = model.estimators_[0].feature_importances_
        except Exception:
            importances = np.ones(len(avail)) / len(avail)

    importance_df = pl.DataFrame({
        "feature":    avail,
        "importance": importances.tolist(),
    }).sort("importance", descending=True)

    print(f"\n  {'Feature':<36}  {'Importance':>10}")
    print("  " + "-" * 48)
    for row in importance_df.head(12).iter_rows(named=True):
        label = FEATURE_LABELS.get(row["feature"], row["feature"])
        bar   = "█" * min(int(row["importance"] * 300), 28)
        print(f"  {label:<36}  {row['importance']:>10.4f}  {bar}")

    # ------------------------------------------------------------------
    # SHAP
    # ------------------------------------------------------------------
    section("SHAP interpretation")
    shap_df = compute_shap(model, X_te, avail, class_names)
    if shap_df is not None:
        print(f"  SHAP computed ({len(shap_df):,} rows)")
    else:
        print("  [SKIP] shap not installed (pip install shap)")

    # ------------------------------------------------------------------
    # Heuristic comparison
    # ------------------------------------------------------------------
    section("Comparison vs S3.3 empirical thresholds")
    heuristic_cmp = compare_with_thresholds(cube, args.thresholds)
    if heuristic_cmp:
        h_acc = heuristic_cmp["heuristic_accuracy"]
        lift  = acc - h_acc
        print(f"  Heuristic accuracy : {h_acc:.4f}  (n={heuristic_cmp['heuristic_n']:,})")
        print(f"  Model accuracy     : {acc:.4f}")
        print(f"  Lift               : {lift:+.4f}")
        if lift > 0.02:
            print("  → Model meaningfully improves over simple thresholds")
        elif lift > 0:
            print("  → Marginal improvement — thresholds capture most of the signal")
        else:
            print("  → Thresholds are competitive — model adds limited value here")
    else:
        print("  [SKIP] --thresholds not provided or file not found")

    # ------------------------------------------------------------------
    # Binary models (should_double, should_take)
    # ------------------------------------------------------------------
    section("Binary models: should_double & should_take")
    for target_col, label in [("should_double", "Double/No-double"),
                               ("should_take",   "Take/Pass")]:
        sub = cube.filter(pl.col(target_col).is_not_null())
        if len(sub) < 200:
            print(f"  [SKIP] {label}: not enough data")
            continue
        X_b = sub.select(avail).fill_null(0).to_numpy().astype(np.float32)
        y_b = sub[target_col].to_numpy()
        X_tr_b, X_te_b, y_tr_b, y_te_b = train_test_split(
            X_b, y_b, test_size=0.2, random_state=42, stratify=y_b
        )
        m_b, _ = get_gbm(args.n_estimators, args.max_depth)
        m_b.fit(X_tr_b, y_tr_b)
        acc_b = accuracy_score(y_te_b, m_b.predict(X_te_b))
        f1_b  = f1_score(y_te_b, m_b.predict(X_te_b), zero_division=0)
        n_pos = int(y_b.sum())
        n_neg = len(y_b) - n_pos
        base  = max(n_pos, n_neg) / len(y_b)   # majority-class baseline
        print(f"  {label:<20}  acc={acc_b:.4f}  f1={f1_b:.4f}  "
              f"baseline={base:.4f}  lift={acc_b-base:+.4f}  "
              f"(n={len(sub):,})")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    section("Saving outputs")

    metrics_dict = {
        "model":           model_name,
        "n_train":         len(X_tr),
        "n_test":          len(X_te),
        "accuracy":        acc,
        "f1_macro":        f1_mac,
        "f1_weighted":     f1_wtd,
    }
    for cls in class_names:
        r = report.get(cls, {})
        metrics_dict[f"precision_{cls}"] = r.get("precision", 0)
        metrics_dict[f"recall_{cls}"]    = r.get("recall", 0)
        metrics_dict[f"f1_{cls}"]        = r.get("f1-score", 0)

    metrics_df = pl.DataFrame([metrics_dict])
    p = output_dir / "cube_model_metrics.csv"
    metrics_df.write_csv(p)
    print(f"  → {p}")

    p = output_dir / "cube_model_feature_importance.csv"
    importance_df.write_csv(p)
    print(f"  → {p}")

    if shap_df is not None:
        p = output_dir / "cube_model_shap_summary.csv"
        shap_df.write_csv(p)
        print(f"  → {p}")

    cm_df = pl.DataFrame(
        {class_names[i]: cm[:, i].tolist() for i in range(len(class_names))},
    ).with_columns(pl.Series("actual", class_names))
    p = output_dir / "cube_model_confusion.csv"
    cm_df.write_csv(p)
    print(f"  → {p}")

    report_path = output_dir / "cube_model_report.txt"
    write_report(
        metrics_dict, importance_df, shap_df, cm,
        class_names, avail, heuristic_cmp, model_name,
        len(X_tr), len(X_te), report_path,
    )
    print(f"  → {report_path}")

    elapsed = time.time() - t0
    print(f"\n{'='*64}")
    print(f"  Done in {elapsed:.1f}s — outputs in {output_dir}/")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
