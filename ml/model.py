"""Action-conditioned Logistic Regression model for Step 2.

Single multi-class-of-rows model:

    P(recovered=1 | transaction_features, action_features, interactions)

Trained once on the labeled (txn, action) feature frame for the *training*
split, then frozen. Supports optional calibration on the validation split.

Notes
-----
* Logistic Regression is used as the *primary interpretable baseline*. It is
  linear in the standardized features so coefficients can be inspected.
* The model is intentionally *one* model shared across all actions (the
  candidate action is itself a feature). Training a separate model per
  action was rejected because:

    - it wastes the cross-action signal in the data (some actions share
      customer/transaction features),
    - it produces a less stable per-action prediction (each model only sees
      a subset of the data),
    - it complicates the calibration story.
"""
from __future__ import annotations

import json
import pickle

import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression

from .config import (
    LOGREG_C,
    LOGREG_CLASS_WEIGHT,
    LOGREG_MAX_ITER,
    LOGREG_SOLVER,
    RANDOM_SEED,
)
from .preprocessing import FittedPreprocessor


@dataclass
class TrainedLogisticModel:
    """The frozen model + metadata needed to reload + score."""

    model: LogisticRegression
    preprocessor: FittedPreprocessor
    calibrator: Optional[object] = None
    model_identifier: str = ""
    feature_spec: Optional[dict] = None
    train_metrics: Optional[dict] = None
    val_metrics_raw: Optional[dict] = None
    val_metrics_calibrated: Optional[dict] = None
    chosen_calibration: str = "none"
    seed: int = RANDOM_SEED
    logreg_c: float = LOGREG_C
    logreg_class_weight: Optional[str] = LOGREG_CLASS_WEIGHT
    logreg_max_iter: int = LOGREG_MAX_ITER

    # ------------------------------------------------------------------
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Return calibrated (if available) or raw P(recovered=1) per row.

        Caller must pass the *full* feature frame (txn x action grid) so the
        action conditioning is preserved.
        """
        X = self.preprocessor.transform(df)
        raw = self.model.predict_proba(X)[:, 1]
        if self.calibrator is not None and self.chosen_calibration != "none":
            if self.chosen_calibration == "isotonic":
                # Isotonic regression exposes `predict` not `predict_proba`.
                p = self.calibrator.predict(raw)
            else:
                # Sigmoid (Platt): apply a*logit(raw)+b, then sigmoid.
                a = float(getattr(self.calibrator, "a", 1.0))
                b = float(getattr(self.calibrator, "b", 0.0))
                eps = 1e-6
                z = np.log(np.clip(raw, eps, 1 - eps) / np.clip(1 - raw, eps, 1 - eps))
                p = 1.0 / (1.0 + np.exp(-np.clip(a * z + b, -30.0, 30.0)))
        else:
            p = raw
        return np.clip(p, 1e-6, 1.0 - 1e-6)

    # ------------------------------------------------------------------
    def coefficients_table(self) -> pd.DataFrame:
        coef = self.model.coef_.ravel()
        names = list(self.preprocessor.feature_names)
        if len(coef) != len(names):
            # Defensive — should not happen
            names = names[: len(coef)]
        df = pd.DataFrame({
            "feature": names,
            "coefficient": coef,
            "abs_coefficient": np.abs(coef),
        })
        return df.sort_values("abs_coefficient", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    def save(self, paths: Dict[str, Path]) -> None:
        for name in ("model_pkl", "preprocessor_pkl", "calibrator_pkl",
                     "feature_spec_json", "feature_names_json",
                     "coefficients_csv", "metadata_json"):
            paths[name].parent.mkdir(parents=True, exist_ok=True)
        with open(paths["model_pkl"], "wb") as f:
            pickle.dump(self.model, f)
        self.preprocessor.save(paths["preprocessor_pkl"])
        if self.calibrator is not None:
            with open(paths["calibrator_pkl"], "wb") as f:
                pickle.dump(self.calibrator, f)
        else:
            # Remove any stale calibrator artifact from a previous run.
            try:
                paths["calibrator_pkl"].unlink()
            except FileNotFoundError:
                pass
        if self.feature_spec is not None:
            paths["feature_spec_json"].write_text(
                json.dumps(self.feature_spec, indent=2, default=str), encoding="utf-8"
            )
        paths["feature_names_json"].write_text(
            json.dumps(self.preprocessor.feature_names, indent=2), encoding="utf-8"
        )
        coef_df = self.coefficients_table()
        coef_df.to_csv(paths["coefficients_csv"], index=False)
        meta = {
            "model_identifier": self.model_identifier,
            "seed": self.seed,
            "logreg_c": self.logreg_c,
            "logreg_class_weight": self.logreg_class_weight,
            "logreg_max_iter": self.logreg_max_iter,
            "chosen_calibration": self.chosen_calibration,
            "n_features": int(self.preprocessor.n_features),
            "train_metrics": self.train_metrics,
            "val_metrics_raw": self.val_metrics_raw,
            "val_metrics_calibrated": self.val_metrics_calibrated,
        }
        paths["metadata_json"].write_text(json.dumps(meta, indent=2, default=str),
                                          encoding="utf-8")

    # ------------------------------------------------------------------
    @staticmethod
    def load(model_dir: Path) -> "TrainedLogisticModel":
        model_dir = Path(model_dir)
        with open(model_dir / "model.pkl", "rb") as f:
            model = pickle.load(f)
        pp = FittedPreprocessor.load(model_dir / "preprocessor.pkl")
        cal_path = model_dir / "calibrator.pkl"
        calibrator = None
        if cal_path.exists():
            with open(cal_path, "rb") as f:
                calibrator = pickle.load(f)
        meta_path = model_dir / "metadata.json"
        meta: dict = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return TrainedLogisticModel(
            model=model,
            preprocessor=pp,
            calibrator=calibrator,
            model_identifier=meta.get("model_identifier", ""),
            train_metrics=meta.get("train_metrics"),
            val_metrics_raw=meta.get("val_metrics_raw"),
            val_metrics_calibrated=meta.get("val_metrics_calibrated"),
            chosen_calibration=meta.get("chosen_calibration", "none"),
            seed=int(meta.get("seed", RANDOM_SEED)),
            logreg_c=float(meta.get("logreg_c", LOGREG_C)),
            logreg_class_weight=meta.get("logreg_class_weight"),
            logreg_max_iter=int(meta.get("logreg_max_iter", LOGREG_MAX_ITER)),
            feature_spec=meta.get("feature_spec"),
        )


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train_logistic(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    c: float = LOGREG_C,
    class_weight: Optional[str] = LOGREG_CLASS_WEIGHT,
    max_iter: int = LOGREG_MAX_ITER,
    seed: int = RANDOM_SEED,
) -> LogisticRegression:
    """Train a single Logistic Regression with the requested hyperparameters.

    Same hyperparameter signature as :class:`TrainedLogisticModel` expects.
    """
    model = LogisticRegression(
        C=c,
        max_iter=max_iter,
        solver=LOGREG_SOLVER,
        class_weight=class_weight,
        random_state=int(seed),
    )
    model.fit(X_train, y_train)
    return model


__all__ = ["TrainedLogisticModel", "train_logistic"]
