"""Step 2 preprocessing pipeline.

Transforms a per-(transaction, action) feature frame into a numeric matrix
``X`` plus a label vector ``y``.

The preprocessor is **fit on training data only** — same contract as
:mod:`feature_engineering.FeatureTransformer` in the Step 0 experiment layer
but parameterised by the :class:`ml.features.FeatureSpec` produced by the
feature orchestrator.

Steps
-----
1. Numeric standardization (z-score; constant columns -> 0).
2. Categorical one-hot encoding (vocabulary frozen at fit time).
3. Interaction columns are already numeric; standardized like other numerics.

The fitted preprocessor is pickleable (so it can be saved alongside the model)
and reloadable.
"""
from __future__ import annotations

import io
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ml.features.pipeline import FeatureSpec


@dataclass
class FittedPreprocessor:
    """State of a fitted preprocessor."""

    numeric_columns: List[str] = field(default_factory=list)
    categorical_columns: List[str] = field(default_factory=list)
    interaction_columns: List[str] = field(default_factory=list)
    numeric_mean: Dict[str, float] = field(default_factory=dict)
    numeric_std: Dict[str, float] = field(default_factory=dict)
    category_vocab: Dict[str, List[str]] = field(default_factory=dict)

    # Computed at fit/transform time.
    feature_names: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def n_features(self) -> int:
        return len(self.feature_names)

    # ------------------------------------------------------------------
    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Transform a feature frame into a numeric matrix."""
        # Numerics
        num_blocks: List[np.ndarray] = []
        for col in self.numeric_columns + self.interaction_columns:
            if col not in df.columns:
                vals = np.zeros(len(df), dtype=float)
            else:
                vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float).to_numpy()
            mean = float(self.numeric_mean.get(col, 0.0))
            std = float(self.numeric_std.get(col, 1.0))
            if std < 1e-9:
                std = 1.0
            standardized = ((vals - mean) / std).astype(float).reshape(-1, 1)
            num_blocks.append(standardized)

        # Categoricals (one-hot with frozen vocab)
        cat_blocks: List[np.ndarray] = []
        for col in self.categorical_columns:
            if col not in df.columns:
                vals = pd.Series([""] * len(df))
            else:
                vals = df[col].astype(str)
            vocab = self.category_vocab.get(col, [])
            mat = np.zeros((len(df), len(vocab)), dtype=float)
            lookup = {v: i for i, v in enumerate(vocab)}
            for i, v in enumerate(vals.tolist()):
                j = lookup.get(v)
                if j is not None:
                    mat[i, j] = 1.0
            cat_blocks.append(mat)

        if num_blocks and cat_blocks:
            return np.hstack(num_blocks + cat_blocks)
        if num_blocks:
            return np.hstack(num_blocks)
        if cat_blocks:
            return np.hstack(cat_blocks)
        return np.zeros((len(df), 0), dtype=float)

    # ------------------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        return path

    @staticmethod
    def load(path: str | Path) -> "FittedPreprocessor":
        with open(path, "rb") as f:
            obj = pickle.load(f)
        if not isinstance(obj, FittedPreprocessor):
            raise ValueError(f"object at {path} is not a FittedPreprocessor")
        return obj


def fit_preprocessor(
    train_df: pd.DataFrame,
    feature_spec: FeatureSpec,
) -> FittedPreprocessor:
    """Fit a preprocessor on training data.

    ``train_df`` is the per-(txn, action) feature frame produced by
    :func:`ml.features.build_step2_feature_frame` for the *training* split.
    """
    pp = FittedPreprocessor(
        numeric_columns=list(feature_spec.numeric_columns),
        categorical_columns=list(feature_spec.categorical_columns),
        interaction_columns=list(feature_spec.interaction_columns),
    )

    for col in pp.numeric_columns + pp.interaction_columns:
        if col in train_df.columns:
            vals = pd.to_numeric(train_df[col], errors="coerce").fillna(0.0).astype(float)
        else:
            vals = pd.Series([0.0] * len(train_df), dtype=float)
        m = float(vals.mean()) if len(vals) else 0.0
        s = float(vals.std()) if len(vals) else 0.0
        if not np.isfinite(m):
            m = 0.0
        if not np.isfinite(s) or s < 1e-9:
            s = 1.0
        pp.numeric_mean[col] = m
        pp.numeric_std[col] = s

    for col in pp.categorical_columns:
        if col in train_df.columns:
            vocab = sorted(train_df[col].astype(str).fillna("").unique().tolist())
        else:
            vocab = []
        pp.category_vocab[col] = vocab

    # Build the deterministic feature name list (numerics, then interactions,
    # then one-hot categories — same order used in transform()).
    names: List[str] = []
    for col in pp.numeric_columns + pp.interaction_columns:
        names.append(col)
    for col in pp.categorical_columns:
        for v in pp.category_vocab[col]:
            names.append(f"{col}={v}")
    pp.feature_names = names
    return pp


def transform_with(
    preprocessor: FittedPreprocessor,
    df: pd.DataFrame,
) -> np.ndarray:
    return preprocessor.transform(df)


__all__ = [
    "FittedPreprocessor",
    "fit_preprocessor",
    "transform_with",
]
