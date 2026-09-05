"""Predictive model: Logistic Regression with optional calibration.

The model is trained ONCE on training data and then FROZEN. All four
strategies consume the exact same frozen predictions. The model predicts
P(recovery | transaction_features, candidate_action).

Because the action is not a raw feature, we train an action-conditioned
logistic model: features + an action one-hot indicator, so the model learns
intercept-level action effects exactly. After training we freeze it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    auc as sklearn_auc,
)
from sklearn.metrics import (
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

from config import (
    CALIBRATION_METHOD,
    LOGREG_C,
    LOGREG_MAX_ITER,
    MODEL_SEED,
    PROB_EPS,
    Action,
)
from data_generation import Transaction, logit_recovery_probability
from feature_engineering import FeatureTransformer, _to_frame

ACTIONS = [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
           Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION]


@dataclass
class ModelMetrics:
    """Quality metrics for a single evaluation split."""

    n: int
    roc_auc: float
    brier: float
    precision: float
    recall: float
    f1: float
    mean_pred: float
    actual_rate: float
    calibration_slope: float
    calibration_intercept: float
    ece: float  # expected calibration error (10 bins)


def _stable_prob(p: np.ndarray) -> np.ndarray:
    return np.clip(p, PROB_EPS, 1.0 - PROB_EPS)


class ActionAwareLogistic:
    """Frozen action-conditional Logistic Regression with calibration."""

    def __init__(self, c: float = LOGREG_C, max_iter: int = LOGREG_MAX_ITER,
                 seed: int = MODEL_SEED, calibration: str = CALIBRATION_METHOD) -> None:
        self._transformer: Optional[FeatureTransformer] = None
        self._model: Optional[LogisticRegression] = None
        self._calibrator: Optional[CalibratedClassifierCV] = None
        self._n_features = 0
        self._is_frozen = False
        self._actions = ACTIONS
        self.c = c
        self.max_iter = max_iter
        self.seed = seed
        self.calibration = calibration

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def _build_action_conditioned_samples(
        self,
        transactions: Sequence[Transaction],
        X_base: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Expand every transaction into len(actions) rows with action indicator.

        Rows:  (X_base_features, onehot(action))
        Target: hidden-ground-truth stochastic recovery draw for that action.
        """
        rows_per_t = len(self._actions)
        n = len(transactions)
        Xs = np.zeros((n * rows_per_t, X_base.shape[1] + len(self._actions)), dtype=float)
        y = np.zeros(n * rows_per_t, dtype=int)
        rng = np.random.default_rng(MODEL_SEED + 7 + n)
        for j, action in enumerate(self._actions):
            start = j * n
            Xs[start : start + n, : X_base.shape[1]] = X_base
            Xs[start : start + n, X_base.shape[1] + j] = 1.0
            prob = logit_recovery_probability(transactions, action)
            y[start : start + n] = (rng.random(n) < prob).astype(int)
        return Xs, y

    def fit(
        self,
        train_transactions: Sequence[Transaction],
        val_transactions: Sequence[Transaction],
        y_train: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
    ) -> "ActionAwareLogistic":
        """Train + calibrate (calibration on val), then freeze."""
        transformer = FeatureTransformer()
        X_train_base = transformer.fit_transform(train_transactions)
        X_val_base = transformer.transform(val_transactions)
        self._transformer = transformer
        self._n_features = transformer.n_features

        X_train, y_train = self._build_action_conditioned_samples(train_transactions, X_train_base)
        X_val, y_val = self._build_action_conditioned_samples(val_transactions, X_val_base)

        model = LogisticRegression(
            C=self.c,
            max_iter=self.max_iter,
            solver="lbfgs",
            random_state=self.seed,
        )
        model.fit(X_train, y_train)

        if self.calibration == "none":
            self._model = model
            self._calibrator = None
        else:
            cal = CalibratedClassifierCV(
                model,
                method=self.calibration,  # "sigmoid" | "isotonic"
                cv=3,
            )
            cal.fit(X_val, y_val)
            self._model = model  # keep raw model too
            self._calibrator = cal

        self._is_frozen = True
        return self

    # ------------------------------------------------------------------
    # Frozen prediction
    # ------------------------------------------------------------------
    def predict_proba(self, transactions: Sequence[Transaction]) -> Dict[Action, np.ndarray]:
        """Frozen per-action recovery probability.

        Returns dict action -> array length n. Can only run after fit().
        Throws if model was not frozen.
        """
        if not self._is_frozen or self._transformer is None:
            raise RuntimeError("Model must be fit() before predict_proba")
        X_base = self._transformer.transform(transactions)
        n = len(transactions)
        ncols = self._transformer.n_features
        out: Dict[Action, np.ndarray] = {}
        for action in self._actions:
            X_action = np.zeros((n, ncols + len(self._actions)), dtype=float)
            X_action[:, :ncols] = X_base
            j = self._actions.index(action)
            X_action[:, ncols + j] = 1.0
            if self._calibrator is not None:
                p = self._calibrator.predict_proba(X_action)[:, 1]
            else:
                p = self._model.predict_proba(X_action)[:, 1]
            out[action] = _stable_prob(np.asarray(p, dtype=float))
        return out

    @property
    def frozen(self) -> bool:
        return self._is_frozen


# ---------------------------------------------------------------------------
# Model quality evaluation on a split (uses true hidden probabilities info)
# ---------------------------------------------------------------------------
def _true_action_probs(transactions: Sequence[Transaction], action: Action) -> np.ndarray:
    return logit_recovery_probability(transactions, action)


def evaluate_model_on_split(
    model: ActionAwareLogistic,
    transactions: Sequence[Transaction],
    split_name: str,
) -> ModelMetrics:
    """Evaluate frozen model quality against hidden ground truth on a split.

    Labels are stochastic draws from the ground truth (reproducible via a
    fixed seed derived from split_name). Calibration uses true probabilities
    pooled across action-conditioned rows.
    """
    probs_all: List[np.ndarray] = []
    labels_all: List[np.ndarray] = []
    for action in ACTIONS:
        p_true = _true_action_probs(transactions, action)
        rng = np.random.default_rng(_stable_int(f"eval:{split_name}"))
        y_true = (rng.random(len(transactions)) < p_true).astype(int)
        p_pred = model.predict_proba(transactions)[action]
        probs_all.append(p_pred)
        labels_all.append(y_true)

    probs = np.concatenate(probs_all)
    y = np.concatenate(labels_all)

    roc, brier = _compute_metrics(probs, y)
    precision, recall, f1 = _compute_precision_recall(probs, y)
    cal = _calibration_stats(probs, y)
    return ModelMetrics(
        n=int(len(y)),
        roc_auc=roc,
        brier=brier,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_pred=float(probs.mean()),
        actual_rate=float(y.mean()),
        calibration_slope=cal[0],
        calibration_intercept=cal[1],
        ece=cal[2],
    )


def _stable_int(key: str, salt: int = MODEL_SEED) -> int:
    """Deterministic integer from a string key (no python-hash randomization)."""
    import hashlib
    digest = hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()
    return int(digest[:12], 16)


def _compute_metrics(probs: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    roc = 0.0
    if y.std() > 0:
        roc = roc_auc_score(y, probs)
    brier = brier_score_loss(y, probs)
    return float(roc), float(brier)


def _compute_precision_recall(probs: np.ndarray, y: np.ndarray) -> Tuple[float, float, float]:
    """Precision/recall at probability threshold 0.5 plus F1."""
    pred = (probs >= 0.5).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def _calibration_stats(probs: np.ndarray, y: np.ndarray) -> Tuple[float, float, float]:
    """Linear calibration fit (logit slope/intercept) and ECE (10 bins)."""
    p = np.clip(probs, PROB_EPS, 1.0 - PROB_EPS)
    bins = np.linspace(0.0, 1.0, 11)
    idx = np.digitize(p, bins) - 1
    idx = np.clip(idx, 0, 9)
    ece = 0.0
    for b in range(10):
        mask = idx == b
        if mask.sum() == 0:
            continue
        ece += np.abs(p[mask].mean() - y[mask].mean()) * mask.sum() / len(p)

    logit_p = np.log(p / (1.0 - p))
    coeffs = np.polyfit(logit_p, y, 1)
    return float(coeffs[0]), float(coeffs[1]), float(ece)