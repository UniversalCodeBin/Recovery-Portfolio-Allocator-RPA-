"""Prediction Service.

A clean service interface over the *frozen* Step 2 model. It:

  * loads the frozen model artifact (never re-trains),
  * scores transaction/action context into calibrated recovery probabilities,
  * preserves model version metadata on every record,
  * validates inputs (required columns, type) and outputs (probabilities in
    [0, 1], no NaN, pair completeness).

It does NOT duplicate the ML pipeline — scoring delegates to
:class:`ml.model.TrainedLogisticModel.predict_proba` via the Step 2 feature
pipeline, and loading delegations to :func:`rpa.loading.load_frozen_model`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ml.model import TrainedLogisticModel
from ml.versioning import now_iso
from rpa.config import DEFAULT_MODEL_IDENTIFIER, MODEL_FEATURE_FLAGS
from rpa.loading import (
    ActionSpec,
    live_score,
    load_actions,
    load_customers,
    load_frozen_model,
    load_transactions,
)


class PredictionValidationError(ValueError):
    """Raised when prediction inputs or outputs are invalid."""


@dataclass
class PredictionResult:
    """Output of the prediction service for one batch."""

    probabilities: np.ndarray  # (n_txn, n_action)
    frame: pd.DataFrame  # long-form (txn, action, p, model_id)
    model_identifier: str
    model_metadata: dict
    feature_spec: dict
    n_transactions: int
    n_actions: int
    scored_at: str = field(default_factory=now_iso)


class PredictionService:
    """Frozen-model prediction service (load-once, score-many)."""

    def __init__(
        self,
        model: TrainedLogisticModel | None = None,
        model_id: str = DEFAULT_MODEL_IDENTIFIER,
        model_dir: Path | None = None,
        flags=MODEL_FEATURE_FLAGS,
    ) -> None:
        self.model_id = model_id
        self.flags = flags
        self._model = model
        self._model_dir = model_dir
        self._metadata: dict | None = None

    # -- lazy load so tests can inject a model directly -----------------
    @property
    def model(self) -> TrainedLogisticModel:
        if self._model is None:
            self._model = load_frozen_model(
                self.model_id, self._model_dir or Path("models")
            )
        return self._model

    @property
    def metadata(self) -> dict:
        if self._metadata is None:
            loaded = self.model
            meta = {
                "model_identifier": loaded.model_identifier or self.model_id,
                "n_features": loaded.preprocessor.n_features,
                "chosen_calibration": loaded.chosen_calibration,
                "feature_names": list(loaded.preprocessor.feature_names),
                "feature_spec": loaded.feature_spec,
            }
            self._metadata = meta
        return self._metadata

    # -- input validation ------------------------------------------------
    def validate_inputs(
        self,
        transactions: pd.DataFrame,
        customers: pd.DataFrame,
        actions: list[ActionSpec],
    ) -> None:
        required = ["transaction_id", "amount", "customer_id"]
        missing = [c for c in required if c not in transactions.columns]
        if missing:
            raise PredictionValidationError(f"transactions missing columns: {missing}")
        if "customer_id" not in customers.columns:
            raise PredictionValidationError("customers missing column: customer_id")
        if not actions:
            raise PredictionValidationError("no actions provided")
        if transactions.empty:
            raise PredictionValidationError("transactions empty")
        if transactions["amount"].isna().any():
            raise PredictionValidationError("transaction amount contains NaN")
        if (transactions["amount"] <= 0).any():
            raise PredictionValidationError("transaction amount must be positive")

    # -- output validation -----------------------------------------------
    def validate_output(self, probs: np.ndarray) -> None:
        if probs.ndim != 2:
            raise PredictionValidationError(
                f"expected 2D probability matrix, got {probs.ndim}D"
            )
        if np.isnan(probs).any():
            raise PredictionValidationError("prediction output contains NaN")
        if (probs < 0.0).any() or (probs > 1.0).any():
            raise PredictionValidationError("prediction probability out of [0, 1]")

    # -- main entry -------------------------------------------------------
    def score(
        self,
        transactions: pd.DataFrame,
        customers: pd.DataFrame,
        actions: list[ActionSpec],
    ) -> PredictionResult:
        """Score a transaction/action context with the frozen model."""
        self.validate_inputs(transactions, customers, actions)
        frame = live_score(self.model, transactions, customers, actions, self.flags)
        # Verify all (txn, action) pairs are present.
        n_txn = len(transactions)
        n_act = len(actions)
        if len(frame) != n_txn * n_act:
            raise PredictionValidationError(
                f"expected {n_txn * n_act} pairs, got {len(frame)}"
            )
        probs = frame["predicted_recovery_probability"].to_numpy().reshape(n_txn, n_act)
        self.validate_output(probs)
        frame["model_identifier"] = self.model.model_identifier or self.model_id
        meta = self.metadata
        return PredictionResult(
            probabilities=probs,
            frame=frame,
            model_identifier=meta["model_identifier"],
            model_metadata=meta,
            feature_spec=meta.get("feature_spec", {}),
            n_transactions=n_txn,
            n_actions=n_act,
        )

    # -- convenience for a named split -----------------------------------
    def score_split(
        self,
        split: str = "demo",
        actions: list[ActionSpec] | None = None,
        transactions: pd.DataFrame | None = None,
        customers: pd.DataFrame | None = None,
    ) -> PredictionResult:
        transactions = (
            transactions if transactions is not None else load_transactions(split)
        )
        customers = customers if customers is not None else load_customers()
        actions = actions if actions is not None else load_actions()
        return self.score(transactions, customers, actions)


__all__ = ["PredictionResult", "PredictionService", "PredictionValidationError"]
