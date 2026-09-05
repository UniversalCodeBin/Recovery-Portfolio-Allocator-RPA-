"""Calibration utilities for Step 2.

We evaluate three calibration options on the validation split and pick the
one with the lowest Brier score:

* ``"none"``     — raw logistic probabilities
* ``"sigmoid"``  — Platt scaling (1-parameter logistic fitted on the raw
                  probability scores; equivalent to sklearn's
                  CalibratedClassifierCV(method='sigmoid') but without the
                  cv='prefit' API which is not portable across sklearn
                  versions).
* ``"isotonic"`` — isotonic regression (non-parametric).

Calibration is *never* performed on the test set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass
class _PlattState:
    """Single-parameter Platt scaling: logit(p) -> a*logit(p) + b."""

    a: float
    b: float


@dataclass
class CalibrationResult:
    method: str
    calibrator: object
    val_brier_raw: float
    val_brier_calibrated: float
    chosen: bool


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def fit_sigmoid_calibrator(model: LogisticRegression, X_val: np.ndarray,
                           y_val: np.ndarray) -> _PlattState:
    """Fit a 1-parameter Platt scaling (sigmoid) on raw probs."""
    raw = model.predict_proba(X_val)[:, 1]
    z = _logit(raw).reshape(-1, 1)
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(z, y_val)
    a = float(lr.coef_.ravel()[0])
    b = float(lr.intercept_.ravel()[0])
    return _PlattState(a=a, b=b)


def fit_isotonic_calibrator(model: LogisticRegression, X_val: np.ndarray,
                            y_val: np.ndarray) -> IsotonicRegression:
    """Isotonic regression on raw probabilities."""
    raw = model.predict_proba(X_val)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw, y_val)
    return iso


def predict_with_calibrator(calibrator: object, raw_probs: np.ndarray,
                            method: str) -> np.ndarray:
    if method == "sigmoid":
        z = _logit(raw_probs)
        return _sigmoid(calibrator.a * z + calibrator.b)
    if method == "isotonic":
        return calibrator.predict(raw_probs)
    raise ValueError(method)


def evaluate_calibration(
    model: LogisticRegression,
    X_val: np.ndarray,
    y_val: np.ndarray,
    methods=("none", "sigmoid", "isotonic"),
) -> Dict[str, CalibrationResult]:
    """Fit each candidate calibrator on the validation split and report Brier."""
    raw = model.predict_proba(X_val)[:, 1]
    brier_raw = _brier(y_val, raw)
    out: Dict[str, CalibrationResult] = {}
    out["none"] = CalibrationResult(method="none", calibrator=None,
                                     val_brier_raw=brier_raw,
                                     val_brier_calibrated=brier_raw,
                                     chosen=False)
    if "sigmoid" in methods:
        cal_sig = fit_sigmoid_calibrator(model, X_val, y_val)
        p_sig = predict_with_calibrator(cal_sig, raw, "sigmoid")
        out["sigmoid"] = CalibrationResult(method="sigmoid", calibrator=cal_sig,
                                            val_brier_raw=brier_raw,
                                            val_brier_calibrated=_brier(y_val, p_sig),
                                            chosen=False)
    if "isotonic" in methods:
        cal_iso = fit_isotonic_calibrator(model, X_val, y_val)
        p_iso = predict_with_calibrator(cal_iso, raw, "isotonic")
        out["isotonic"] = CalibrationResult(method="isotonic", calibrator=cal_iso,
                                             val_brier_raw=brier_raw,
                                             val_brier_calibrated=_brier(y_val, p_iso),
                                             chosen=False)
    best_method = min(out.keys(), key=lambda m: out[m].val_brier_calibrated)
    out = {
        k: CalibrationResult(m.method, m.calibrator,
                              m.val_brier_raw, m.val_brier_calibrated,
                              chosen=(k == best_method))
        for k, m in out.items()
    }
    return out


__all__ = [
    "CalibrationResult",
    "fit_sigmoid_calibrator",
    "fit_isotonic_calibrator",
    "predict_with_calibrator",
    "evaluate_calibration",
]
