"""Step 2 evaluation metrics.

Reports ROC-AUC, average precision, precision/recall/F1 (at threshold 0.5),
Brier score, calibration slope/intercept and Expected Calibration Error (ECE,
10 equal-width bins).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)


@dataclass
class EvalMetrics:
    n: int
    positive_rate: float
    mean_pred: float
    roc_auc: Optional[float]
    average_precision: Optional[float]
    precision_at_05: Optional[float]
    recall_at_05: Optional[float]
    f1_at_05: Optional[float]
    brier: float
    ece_10bins: float
    calibration_slope: Optional[float]
    calibration_intercept: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _safe_auc(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    if len(np.unique(y)) < 2:
        return None
    try:
        return float(roc_auc_score(y, p))
    except ValueError:
        return None


def _safe_ap(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    if len(np.unique(y)) < 2:
        return None
    try:
        return float(average_precision_score(y, p))
    except ValueError:
        return None


def _ece(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    p = np.clip(p, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(p, edges) - 1
    idx = np.clip(idx, 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        ece += abs(p[mask].mean() - y[mask].mean()) * mask.sum() / len(p)
    return float(ece)


def _calibration_slope_intercept(y: np.ndarray, p: np.ndarray):
    eps = 1e-6
    p = np.clip(p, eps, 1 - eps)
    logit = np.log(p / (1 - p))
    if len(np.unique(y)) < 2 or len(p) < 5:
        return None, None
    try:
        slope, intercept = np.polyfit(logit, y, 1)
        return float(slope), float(intercept)
    except (np.linalg.LinAlgError, ValueError):
        return None, None


def evaluate_predictions(y_true: np.ndarray, p_pred: np.ndarray) -> EvalMetrics:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(p_pred, dtype=float)
    n = int(len(y))
    if n == 0:
        return EvalMetrics(0, 0.0, 0.0, None, None, None, None, None, 0.0, 0.0, None, None)

    yhat = (p >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y, yhat, labels=[1], zero_division=0
    )

    slope, intercept = _calibration_slope_intercept(y, p)
    return EvalMetrics(
        n=n,
        positive_rate=float(y.mean()),
        mean_pred=float(p.mean()),
        roc_auc=_safe_auc(y, p),
        average_precision=_safe_ap(y, p),
        precision_at_05=float(precision[0]) if len(precision) else None,
        recall_at_05=float(recall[0]) if len(recall) else None,
        f1_at_05=float(f1[0]) if len(f1) else None,
        brier=float(brier_score_loss(y, p)),
        ece_10bins=_ece(y, p),
        calibration_slope=slope,
        calibration_intercept=intercept,
    )


def metrics_to_dataframe(rows: Dict[str, EvalMetrics]) -> pd.DataFrame:
    """Return a tidy DataFrame; one row per split, columns from EvalMetrics."""
    return pd.DataFrame({k: v.to_dict() for k, v in rows.items()}).T


__all__ = [
    "EvalMetrics",
    "evaluate_predictions",
    "metrics_to_dataframe",
]
