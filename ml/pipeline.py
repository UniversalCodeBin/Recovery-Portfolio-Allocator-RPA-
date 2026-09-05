"""Step 2 end-to-end pipeline orchestrator.

    Load Step 1 data + splits
        |
        v
    Feature engineering (per spec, fit on train only)
        |
        v
    Logistic Regression (fit on train)
        |
        v
    Calibration (chosen on val)
        |
        v
    Evaluate (train / val / test)
        |
        v
    Ablation (A_basic, B_customer, C_action, D_interactions)
        |
        v
    Generate predictions (test, demo) + write artifacts
        |
        v
    Persist predictions to DB
        |
        v
    Markdown + JSON report

Run with: ``python scripts/run_step2.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .ablation import ablation_to_dataframe, run_ablation
from .calibration import evaluate_calibration
from .config import (
    ABLATION_SPECS,
    CALIBRATION_CANDIDATES,
    DEFAULT_MODEL_VERSION,
    LOGREG_C,
    LOGREG_CLASS_WEIGHT,
    LOGREG_MAX_ITER,
    PREDICTIONS_DIR,
    RANDOM_SEED,
    REPORTS_ML_DIR,
    REPORTS_ABLATION_DIR,
    STEP2_REPORT_JSON_PATH,
    STEP2_REPORT_PATH,
    FeatureFlags,
)
from .data_io import (
    Step2Datasets,
    assert_customer_split_isolation,
    build_labeled_pairs,
    load_step2_data,
)
from .evaluation import EvalMetrics, evaluate_predictions, metrics_to_dataframe
from .features import build_step2_feature_frame, resolve_feature_spec
from .model import TrainedLogisticModel, train_logistic
from .prediction import (
    generate_predictions,
    insert_predictions_to_db,
    predictions_with_truth,
    save_predictions_csv,
)
from .preprocessing import fit_preprocessor
from .versioning import artifact_paths, default_version, now_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _frame_with_labels(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    recovery_actions: pd.DataFrame,
    action_outcomes: pd.DataFrame,
    flags: FeatureFlags,
    seed: int,
) -> pd.DataFrame:
    """Build the per-(txn, action) feature frame *with* the label column."""
    action_ids = recovery_actions["action_id"].tolist()
    feat_df = build_step2_feature_frame(
        transactions, customers, recovery_actions, action_ids, flags
    )
    labels = build_labeled_pairs(transactions, action_outcomes,
                                  recovery_actions, seed=seed)
    return feat_df.merge(
        labels[["transaction_id", "action_id", "recovered", "recovered_amount"]],
        on=["transaction_id", "action_id"], how="left",
    )


def _train_full_model(
    datasets: Step2Datasets,
    flags: FeatureFlags,
    *,
    seed: int,
    logreg_c: float,
    class_weight: Optional[str],
    max_iter: int,
) -> TrainedLogisticModel:
    """Train + calibrate the full-feature production model."""
    train = _frame_with_labels(
        datasets.splits["train"], datasets.customers,
        datasets.recovery_actions, datasets.action_outcomes,
        flags, seed=seed,
    )
    val = _frame_with_labels(
        datasets.splits["val"], datasets.customers,
        datasets.recovery_actions, datasets.action_outcomes,
        flags, seed=seed,
    )
    test = _frame_with_labels(
        datasets.splits["test"], datasets.customers,
        datasets.recovery_actions, datasets.action_outcomes,
        flags, seed=seed,
    )

    spec = resolve_feature_spec(flags)
    pp = fit_preprocessor(train, spec)
    X_train = pp.transform(train)
    X_val = pp.transform(val)
    X_test = pp.transform(test)
    y_train = train["recovered"].astype(int).to_numpy()
    y_val = val["recovered"].astype(int).to_numpy()
    y_test = test["recovered"].astype(int).to_numpy()

    model = train_logistic(X_train, y_train, c=logreg_c, class_weight=class_weight,
                           max_iter=max_iter, seed=seed)

    cal = evaluate_calibration(model, X_val, y_val, methods=CALIBRATION_CANDIDATES)
    chosen_name = min(cal.keys(), key=lambda m: cal[m].val_brier_calibrated)
    chosen = cal[chosen_name]

    p_train = np.clip(model.predict_proba(X_train)[:, 1], 1e-6, 1 - 1e-6)
    p_val_raw = np.clip(model.predict_proba(X_val)[:, 1], 1e-6, 1 - 1e-6)
    p_test_raw = np.clip(model.predict_proba(X_test)[:, 1], 1e-6, 1 - 1e-6)

    # Re-evaluate calibrated outputs.
    from .calibration import predict_with_calibrator
    raw_probs = {
        "train": p_train,
        "val": p_val_raw,
        "test": p_test_raw,
    }
    cal_probs: Dict[str, np.ndarray] = {}
    if chosen_name != "none":
        cal_probs = {
            split: predict_with_calibrator(chosen.calibrator, raw, chosen_name)
            for split, raw in raw_probs.items()
        }
    else:
        cal_probs = dict(raw_probs)

    m_train_raw = evaluate_predictions(y_train, raw_probs["train"])
    m_val_raw = evaluate_predictions(y_val, raw_probs["val"])
    m_test_raw = evaluate_predictions(y_test, raw_probs["test"])
    m_train_cal = evaluate_predictions(y_train, cal_probs["train"])
    m_val_cal = evaluate_predictions(y_val, cal_probs["val"])
    m_test_cal = evaluate_predictions(y_test, cal_probs["test"])

    trained = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator if chosen_name != "none" else None,
        model_identifier=default_version(group="full"),
        chosen_calibration=chosen_name,
        seed=seed,
        logreg_c=logreg_c,
        logreg_class_weight=class_weight,
        logreg_max_iter=max_iter,
        feature_spec={
            "numeric": spec.numeric_columns,
            "categorical": spec.categorical_columns,
            "interaction": spec.interaction_columns,
            "enabled_groups": spec.enabled_groups,
        },
        train_metrics=m_train_cal.to_dict(),
        val_metrics_raw=m_val_raw.to_dict(),
        val_metrics_calibrated=m_val_cal.to_dict(),
    )

    return trained, {
        "raw": {"train": m_train_raw, "val": m_val_raw, "test": m_test_raw},
        "calibrated": {"train": m_train_cal, "val": m_val_cal, "test": m_test_cal},
        "calibration_chosen": chosen_name,
        "calibration_candidates": {m: cal[m].val_brier_calibrated for m in cal},
        "y_test": y_test,
    }


def _save_metrics_report(metrics: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "model_metrics.json"
    payload = {}
    for split, m in metrics.items():
        if hasattr(m, "to_dict"):
            payload[split] = m.to_dict()
        else:
            payload[split] = m
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    # CSV too
    pd.DataFrame({k: v.to_dict() for k, v in metrics.items() if hasattr(v, "to_dict")}).T.to_csv(
        out_dir / "model_metrics.csv"
    )
    return p


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
@dataclass
class Step2Result:
    model_identifier: str
    metrics: Dict[str, EvalMetrics]
    calibration_chosen: str
    ablation_table: pd.DataFrame
    n_predictions_test: int
    n_predictions_demo: int
    db_inserted: int
    artifact_paths: Dict[str, Path]
    summary: Dict[str, Any] = field(default_factory=dict)


def run_step2(
    *,
    seed: int = RANDOM_SEED,
    logreg_c: float = LOGREG_C,
    class_weight: Optional[str] = LOGREG_CLASS_WEIGHT,
    max_iter: int = LOGREG_MAX_ITER,
    load_db: bool = False,
    save_db: bool = False,
    flags: Optional[FeatureFlags] = None,
) -> Step2Result:
    """Run the full Step 2 pipeline."""
    flags = flags or FeatureFlags()

    # 1) Load Step 1 data.
    datasets = load_step2_data()
    assert_customer_split_isolation(datasets.splits)

    # 2) Train + calibrate the full model.
    trained, eval_info = _train_full_model(
        datasets, flags,
        seed=seed, logreg_c=logreg_c, class_weight=class_weight, max_iter=max_iter,
    )

    # Persist model artifacts.
    paths = artifact_paths(trained.model_identifier)
    trained.save(paths)

    metrics = {
        "train": eval_info["calibrated"]["train"],
        "val": eval_info["calibrated"]["val"],
        "test": eval_info["calibrated"]["test"],
    }
    raw_metrics = {
        "train": eval_info["raw"]["train"],
        "val": eval_info["raw"]["val"],
        "test": eval_info["raw"]["test"],
    }
    _save_metrics_report(metrics, REPORTS_ML_DIR)

    # 3) Ablation.
    ablation = run_ablation(datasets, seed=seed, logreg_c=logreg_c,
                            class_weight=class_weight, max_iter=max_iter)
    ablation_df = ablation_to_dataframe(ablation)
    REPORTS_ABLATION_DIR.mkdir(parents=True, exist_ok=True)
    ablation_df.to_csv(REPORTS_ABLATION_DIR / "ablation_results.csv")

    # 4) Predictions for test and demo.
    test_preds = generate_predictions(
        trained, datasets.splits["test"], datasets.customers,
        datasets.recovery_actions, flags,
    )
    test_preds_with_truth = predictions_with_truth(
        test_preds, datasets.splits["test"], datasets.action_outcomes,
        datasets.recovery_actions,
    )
    save_predictions_csv(
        test_preds_with_truth,
        PREDICTIONS_DIR / f"predictions_test_{trained.model_identifier}.csv",
    )

    n_test = len(test_preds)

    n_demo = 0
    if "demo" in datasets.splits and len(datasets.splits["demo"]) > 0:
        demo_preds = generate_predictions(
            trained, datasets.splits["demo"], datasets.customers,
            datasets.recovery_actions, flags,
        )
        demo_preds_with_truth = predictions_with_truth(
            demo_preds, datasets.splits["demo"], datasets.action_outcomes,
            datasets.recovery_actions,
        )
        save_predictions_csv(
            demo_preds_with_truth,
            PREDICTIONS_DIR / f"predictions_demo_{trained.model_identifier}.csv",
        )
        n_demo = len(demo_preds)

    # 5) Persist to DB (optional).
    db_inserted = 0
    if save_db:
        db_inserted = insert_predictions_to_db(test_preds, reset_table=True)

    # 6) Build a tiny summary and the markdown report.
    summary: Dict[str, Any] = {
        "model_identifier": trained.model_identifier,
        "calibration_chosen": eval_info["calibration_chosen"],
        "calibration_candidates_val_brier": eval_info["calibration_candidates"],
        "seed": seed,
        "logreg_c": logreg_c,
        "logreg_class_weight": class_weight,
        "logreg_max_iter": max_iter,
        "n_features": trained.preprocessor.n_features,
        "metrics_train_calibrated": metrics["train"].to_dict(),
        "metrics_val_calibrated": metrics["val"].to_dict(),
        "metrics_test_calibrated": metrics["test"].to_dict(),
        "metrics_train_raw": raw_metrics["train"].to_dict(),
        "metrics_val_raw": raw_metrics["val"].to_dict(),
        "metrics_test_raw": raw_metrics["test"].to_dict(),
        "ablation_table": ablation_df.reset_index().rename(columns={"index": "spec"}).to_dict(orient="records"),
        "n_predictions_test": n_test,
        "n_predictions_demo": n_demo,
        "n_db_inserted": db_inserted,
        "artifact_paths": {k: str(v) for k, v in paths.items()},
    }

    STEP2_REPORT_JSON_PATH.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    md = _build_markdown_report(summary, ablation_df)
    STEP2_REPORT_PATH.write_text(md, encoding="utf-8")

    return Step2Result(
        model_identifier=trained.model_identifier,
        metrics=metrics,
        calibration_chosen=eval_info["calibration_chosen"],
        ablation_table=ablation_df,
        n_predictions_test=n_test,
        n_predictions_demo=n_demo,
        db_inserted=db_inserted,
        artifact_paths=paths,
        summary=summary,
    )


def _fmt4(x):
    try:
        return f"{float(x):.4f}"
    except Exception:
        return "n/a"


def _build_markdown_report(summary: Dict[str, Any], ablation_df: pd.DataFrame) -> str:
    out = []
    out.append("# Step 2 — Model & Feature Engineering Report\n")
    out.append(f"_Generated at {now_iso()}._\n")
    out.append("## 1. Production model\n")
    out.append(f"- **Model identifier:** `{summary['model_identifier']}`")
    out.append(f"- **Calibration chosen (val):** `{summary['calibration_chosen']}`")
    out.append(f"- **Candidate calibration val-Brier:** {summary['calibration_candidates_val_brier']}")
    out.append(f"- **Random seed:** {summary['seed']}")
    out.append(f"- **Logreg C / max_iter / class_weight:** "
               f"{summary['logreg_c']} / {summary['logreg_max_iter']} / {summary['logreg_class_weight']}")
    out.append(f"- **#features:** {summary['n_features']}\n")

    out.append("## 2. Metrics (calibrated)\n")
    out.append("| Split | n | pos rate | mean pred | ROC-AUC | AP | Brier | ECE |")
    out.append("|---|---|---|---|---|---|---|---|")
    for split in ("train", "val", "test"):
        m = summary[f"metrics_{split}_calibrated"]
        out.append(
            f"| {split} | {m['n']} | {m['positive_rate']:.3f} | {m['mean_pred']:.3f} | "
            f"{'n/a' if m['roc_auc'] is None else _fmt4(m['roc_auc'])} | "
            f"{'n/a' if m['average_precision'] is None else _fmt4(m['average_precision'])} | "
            f"{m['brier']:.4f} | {m['ece_10bins']:.4f} |"
        )
    out.append("")

    out.append("## 3. Metrics (raw, un-calibrated)\n")
    out.append("| Split | n | ROC-AUC | Brier | ECE |")
    out.append("|---|---|---|---|---|")
    for split in ("train", "val", "test"):
        m = summary[f"metrics_{split}_raw"]
        out.append(
            f"| {split} | {m['n']} | "
            f"{'n/a' if m['roc_auc'] is None else _fmt4(m['roc_auc'])} | "
            f"{m['brier']:.4f} | {m['ece_10bins']:.4f} |"
        )
    out.append("")

    out.append("## 4. Feature ablation\n")
    out.append("| spec | " + " | ".join(ablation_df.columns) + " |")
    out.append("|" + "|".join(["---"] * (len(ablation_df.columns) + 1)) + "|")
    for idx, row in ablation_df.round(4).iterrows():
        cells = [str(idx)] + [str(v) for v in row.tolist()]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")

    out.append("## 5. Predictions\n")
    out.append(f"- **#test predictions:** {summary['n_predictions_test']}")
    out.append(f"- **#demo predictions:** {summary['n_predictions_demo']}")
    out.append(f"- **#rows inserted into DB:** {summary['n_db_inserted']}\n")

    out.append("## 6. Artifacts\n")
    for k, v in summary["artifact_paths"].items():
        out.append(f"- `{k}`: `{v}`")
    return "\n".join(out) + "\n"


__all__ = ["Step2Result", "run_step2"]
