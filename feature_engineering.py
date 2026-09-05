"""Feature engineering: transform raw Transactions into a numeric feature matrix.

The FeatureTransformer fits on training data only (to avoid leakage) and then
transforms validation/test/demo data with the fitted statistics. No target
information is used here.
"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np
import pandas as pd

from config import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from data_generation import Transaction


class FeatureTransformer:
    """Fit numeric scalers + one-hot encode categoricals on train data only."""

    def __init__(self) -> None:
        self._numeric_mean: np.ndarray | None = None
        self._numeric_std: np.ndarray | None = None
        self._category_vocab: dict[str, list[str]] = {}
        self._fitted: bool = False

    def fit(self, transactions: Sequence[Transaction]) -> "FeatureTransformer":
        """Fit on training transactions only."""
        df = _to_frame(transactions)
        num = df[NUMERIC_FEATURES].to_numpy(dtype=float)
        self._numeric_mean = num.mean(axis=0)
        self._numeric_std = num.std(axis=0)
        self._numeric_std[self._numeric_std < 1e-9] = 1.0

        for col in CATEGORICAL_FEATURES:
            # Preserve the category ordering seen during fit.
            self._category_vocab[col] = sorted(df[col].dropna().unique().tolist())

        self._fitted = True
        return self

    def transform(self, transactions: Sequence[Transaction]) -> np.ndarray:
        """Transform transactions into a numeric feature matrix.

        Transformer must already be fitted (raise otherwise).
        """
        if not self._fitted:
            raise RuntimeError("FeatureTransformer.transform called before fit()")
        df = _to_frame(transactions)

        num = df[NUMERIC_FEATURES].to_numpy(dtype=float)
        num = (num - self._numeric_mean) / self._numeric_std

        onehot_cols: list[np.ndarray] = []
        for col in CATEGORICAL_FEATURES:
            vocab = self._category_vocab[col]
            raw = df[col].tolist()
            mat = np.zeros((len(raw), len(vocab)), dtype=float)
            for i, val in enumerate(raw):
                if val in vocab:
                    mat[i, vocab.index(val)] = 1.0
            onehot_cols.append(mat)

        if onehot_cols:
            return np.hstack([num] + onehot_cols)
        return num

    def fit_transform(self, transactions: Sequence[Transaction]) -> np.ndarray:
        return self.fit(transactions).transform(transactions)

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def n_features(self) -> int:
        if not self._fitted:
            raise RuntimeError("n_features before fit()")
        n_onehot = sum(len(v) for v in self._category_vocab.values())
        return len(NUMERIC_FEATURES) + n_onehot


def build_action_augmented_frame(
    transactions: Sequence[Transaction],
    actions: Sequence[str],
    transformer: FeatureTransformer,
) -> np.ndarray:
    """Build augmented feature matrix: each (txn, action) pair duplicated.

    Returns X of shape (n * len(actions), n_features) where the action is NOT
    encoded as a feature (the model gets a per-action prediction via a shared
    action-effect handled by the caller). This helper keeps the matrix layout
    simple; the strategies handle action effects at prediction time.
    """
    base = transformer.transform(transactions)
    n = len(transactions)
    m = len(actions)
    return np.tile(base, (m, 1))


def build_labeled_frame(
    transactions: Sequence[Transaction],
    action: str,
) -> pd.DataFrame:
    """Add a target 'recovered' column for one action using ground truth.

    Used to build the supervised training set: for each transaction and a
    chosen action, draw an outcome from the hidden ground-truth model.
    """
    from data_generation import logit_recovery_probability

    prob = logit_recovery_probability(transactions, Action(value=action))
    rng = np.random.default_rng(0)  # fixed for reproducibility of labels
    recovered = (rng.random(len(transactions)) < prob).astype(int)
    df = _to_frame(transactions)
    df["action"] = action
    df["p_true"] = prob
    df["recovered"] = recovered
    return df


def _to_frame(transactions: Sequence[Transaction]) -> pd.DataFrame:
    return pd.DataFrame([t.to_dict() for t in transactions])
