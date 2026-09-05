"""Feature ablation runner.

Trains one model per :class:`ml.config.AblationSpec` and reports per-spec
metrics on train/val/test. The point is *not* to find the highest-AUC spec —
the point is to see whether each feature group contributes *useful*
predictive signal.

The chosen production model is the spec that achieves the lowest validation
Brier score after calibration. If no spec meaningfully improves on
``A_basic`` we still report that honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .calibration import evaluate_calibration
from .config import (
    ABLATION_SPECS,
    CALIBRATION_CANDIDATES,
    LOGREG_C,
    LOGREG_CLASS_WEIGHT,
    LOGREG_MAX_ITER,
    RANDOM_SEED,
)
from .data_io import Step2Datasets, build_labeled_pairs
from .evaluation import EvalMetrics, evaluate_predictions
from .features import build_step2_feature_frame
from .model import TrainedLogisticModel, train_logistic
from .preprocessing import fit_preprocessor


@dataclass
class AblationResult:
    spec_name: str
    description: str
    n_features: int
    train_metrics: EvalMetrics
    val_metrics_raw: EvalMetrics
    val_metrics_calibrated: EvalMetrics
    test_metrics: EvalMetrics
    chosen_calibration: str
    model_identifier: str


def _frame_with_labels(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    recovery_actions: pd.DataFrame,
    action_outcomes: pd.DataFrame,
    flags,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Build the per-(txn, action) feature frame *with* the label column."""
    action_ids = recovery_actions["action_id"].tolist()
    feat_df = build_step2_feature_frame(
        transactions, customers, recovery_actions, action_ids, flags
    )
    labels = build_labeled_pairs(transactions, action_outcomes,
                                  recovery_actions, seed=seed)
    feat_df = feat_df.merge(
        labels[["transaction_id", "action_id", "recovered"]],
        on=["transaction_id", "action_id"], how="left",
    )
    y = feat_df["recovered"].astype(int).to_numpy()
    return feat_df, y


def run_ablation(
    datasets: Step2Datasets,
    seed: int = RANDOM_SEED,
    specs: Optional[Dict[str, "AblationSpec"]] = None,
    logreg_c: float = LOGREG_C,
    class_weight: Optional[str] = LOGREG_CLASS_WEIGHT,
    max_iter: int = LOGREG_MAX_ITER,
) -> Dict[str, AblationResult]:
    """Train + evaluate one model per ablation spec."""
    specs = specs or ABLATION_SPECS
    out: Dict[str, AblationResult] = {}

    train_tx = datasets.splits["train"]
    val_tx = datasets.splits["val"]
    test_tx = datasets.splits["test"]

    for name, spec in specs.items():
        flags = spec.flags

        def _build(tx):
            return _frame_with_labels(
                tx, datasets.customers, datasets.recovery_actions,
                datasets.action_outcomes, flags=flags, seed=seed,
            )

        train_feat, y_train = _build(train_tx)
        val_feat, y_val = _build(val_tx)
        test_feat, y_test = _build(test_tx)

        pp = fit_preprocessor(train_feat, _resolve_spec_from_flags(flags))
        X_train = pp.transform(train_feat)
        X_val = pp.transform(val_feat)
        X_test = pp.transform(test_feat)

        model = train_logistic(
            X_train, y_train,
            c=logreg_c, class_weight=class_weight, max_iter=max_iter, seed=seed,
        )

        cal_results = evaluate_calibration(model, X_val, y_val, methods=CALIBRATION_CANDIDATES)
        chosen_name = min(cal_results.keys(), key=lambda m: cal_results[m].val_brier_calibrated)

        trained = TrainedLogisticModel(
            model=model,
            preprocessor=pp,
            calibrator=cal_results[chosen_name].calibrator,
            model_identifier=f"rpa-recovery-logreg-{name}-v1",
            chosen_calibration=chosen_name,
            seed=seed,
            logreg_c=logreg_c,
            logreg_class_weight=class_weight,
            logreg_max_iter=max_iter,
        )

        p_train = trained.predict_proba(train_feat)
        p_val = trained.predict_proba(val_feat)
        p_test = trained.predict_proba(test_feat)

        m_train = evaluate_predictions(y_train, p_train)
        m_val = evaluate_predictions(y_val, p_val)
        m_test = evaluate_predictions(y_test, p_test)

        p_val_raw = np.clip(model.predict_proba(X_val)[:, 1], 1e-6, 1 - 1e-6)
        m_val_raw = evaluate_predictions(y_val, p_val_raw)

        out[name] = AblationResult(
            spec_name=name,
            description=spec.description,
            n_features=int(pp.n_features),
            train_metrics=m_train,
            val_metrics_raw=m_val_raw,
            val_metrics_calibrated=m_val,
            test_metrics=m_test,
            chosen_calibration=chosen_name,
            model_identifier=trained.model_identifier,
        )
    return out


def _resolve_spec_from_flags(flags):
    """Tiny indirection so we can call fit_preprocessor with FeatureSpec from flags."""
    from ml.features import resolve_feature_spec
    return resolve_feature_spec(flags)


def ablation_to_dataframe(results: Dict[str, AblationResult]) -> pd.DataFrame:
    rows = {}
    for name, r in results.items():
        rows[name] = {
            "description": r.description,
            "n_features": r.n_features,
            "chosen_calibration": r.chosen_calibration,
            "train_roc_auc": r.train_metrics.roc_auc,
            "train_brier": r.train_metrics.brier,
            "train_ece": r.train_metrics.ece_10bins,
            "val_raw_roc_auc": r.val_metrics_raw.roc_auc,
            "val_raw_brier": r.val_metrics_raw.brier,
            "val_cal_roc_auc": r.val_metrics_calibrated.roc_auc,
            "val_cal_brier": r.val_metrics_calibrated.brier,
            "val_cal_ece": r.val_metrics_calibrated.ece_10bins,
            "test_roc_auc": r.test_metrics.roc_auc,
            "test_brier": r.test_metrics.brier,
            "test_ece": r.test_metrics.ece_10bins,
        }
    return pd.DataFrame(rows).T


__all__ = [
    "AblationResult",
    "run_ablation",
    "ablation_to_dataframe",
]
