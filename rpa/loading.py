"""Data loading for Step 3 (prediction service + backend).

Bridges Step 1 (data foundation) and Step 2 (frozen model + predictions) into
the shapes Step 3 components consume. Reuses ``data_core.io.read_frame`` and
Step 2's ``TrainedLogisticModel`` — it does NOT re-train or re-engineer
features; it only loads artifacts already produced by Steps 1/2.

This module is deliberately thin: it locates and loads:
  * transactions (from a Step 1 split)
  * customers (from Step 1 validated)
  * recovery actions (from Step 1 validated)  -> ``ActionSpec`` dict
  * predictions (Step 2 CSV, or Step 2 DB, or frozen model live-score)

The live-scoring path calls the frozen model's ``predict_proba`` through the
Step 2 feature pipeline so the backend can score arbitrary in-flight
transactions without touching the DB.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from data_core.config import SPLITS_DIR, VALIDATED_DIR
from data_core.io import read_frame
from ml.config import FeatureFlags
from ml.features import build_step2_feature_frame
from ml.model import TrainedLogisticModel
from rpa.config import (
    DEFAULT_MODEL_IDENTIFIER,
    MODEL_DIR,
    MODEL_FEATURE_FLAGS,
    PREDICTIONS_DIR,
)


# ---------------------------------------------------------------------------
# Action spec (data-driven economics + resource consumption)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ActionSpec:
    """Economics of a single recovery action, read from Step 1 data."""

    action_id: str
    action_type: str
    action_cost: float  # rupee handling cost
    resource_requirements: dict[str, float]  # e.g. {"incentive_budget": 50.0, ...}
    enabled: bool = True

    @property
    def is_no_op(self) -> bool:
        return self.action_type == "no_intervention"

    def resource_units(self, resource_key: str) -> float:
        return float(self.resource_requirements.get(resource_key, 0.0))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_actions(
    path: pathlib.Path = VALIDATED_DIR / "recovery_actions.csv",
) -> list[ActionSpec]:
    df = read_frame(path, "recovery_actions")
    specs: list[ActionSpec] = []
    for row in df.to_dict(orient="records"):
        specs.append(
            ActionSpec(
                action_id=row["action_id"],
                action_type=row["action_type"],
                action_cost=float(row["action_cost"]),
                resource_requirements=dict(row.get("resource_requirements") or {}),
                enabled=bool(row.get("enabled", True)),
            )
        )
    return specs


def load_transactions(name: str = "demo") -> pd.DataFrame:
    """Load a Step 1 transaction split (demo/test/etc.) as a DataFrame."""
    p = SPLITS_DIR / f"split_{name}.csv"
    if not p.exists():
        raise FileNotFoundError(f"split not found: {p} (run Step 1 first)")
    return read_frame(p, "transactions")


def load_customers() -> pd.DataFrame:
    p = VALIDATED_DIR / "customers.csv"
    if not p.exists():
        raise FileNotFoundError(f"customers not found: {p} (run Step 1 first)")
    return read_frame(p, "customers")


def load_predictions_csv(
    model_id: str = DEFAULT_MODEL_IDENTIFIER, split: str = "demo"
) -> pd.DataFrame:
    """Load Step 2 prediction CSV for a split."""
    p = PREDICTIONS_DIR / f"predictions_{split}_{model_id}.csv"
    if not p.exists():
        # Fall back to the generic name written by the pipeline.
        p = PREDICTIONS_DIR / "recovery_predictions.csv"
    if not p.exists():
        raise FileNotFoundError(f"predictions not found for {split}/{model_id}")
    return pd.read_csv(p)


# ---------------------------------------------------------------------------
# Frozen-model live scoring (prediction service back-end)
# ---------------------------------------------------------------------------
def load_frozen_model(
    model_id: str = DEFAULT_MODEL_IDENTIFIER, model_dir: pathlib.Path = MODEL_DIR
) -> TrainedLogisticModel:
    """Load the frozen Step 2 model artifact. Raises if not found."""
    from ml.versioning import artifact_paths

    paths = artifact_paths(model_id, base_dir=MODEL_DIR.parent)
    if not paths["model_dir"].exists():
        raise FileNotFoundError(
            f"frozen model artifact not found at {paths['model_dir']}. Run Step 2 first."
        )
    return TrainedLogisticModel.load(paths["model_dir"])


def live_score(
    model: TrainedLogisticModel,
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    actions: list[ActionSpec],
    flags: FeatureFlags = MODEL_FEATURE_FLAGS,
) -> pd.DataFrame:
    """Score every (txn, action) with the frozen model, return predictions.

    Mirrors :func:`ml.prediction.generate_predictions` but accepts an already
    loaded model + action specs so the backend never re-trains.
    """
    action_ids = [a.action_id for a in actions]
    feat = build_step2_feature_frame(
        transactions, customers, _actions_frame(actions), action_ids, flags
    )
    p = model.predict_proba(feat)
    return pd.DataFrame(
        {
            "transaction_id": feat["transaction_id"].tolist(),
            "action_id": feat["action_id"].tolist(),
            "predicted_recovery_probability": p.astype(float),
            "model_identifier": model.model_identifier,
        }
    )


def _actions_frame(actions: list[ActionSpec]) -> pd.DataFrame:
    import json

    return pd.DataFrame(
        [
            {
                "action_id": a.action_id,
                "action_type": a.action_type,
                "action_cost": a.action_cost,
                "resource_requirements": json.dumps(a.resource_requirements),
                "enabled": a.enabled,
            }
            for a in actions
        ]
    )


def predictions_matrix(
    predictions: pd.DataFrame,
    transactions: pd.DataFrame,
    actions: list[ActionSpec],
) -> np.ndarray:
    """Predictions -> (n_transactions, n_actions) probability matrix.

    Rows indexed by transaction order in `transactions`; columns aligned to
    `actions` order. Missing pairs default to 0.0 (no-op prior).
    """
    txn_ids = transactions["transaction_id"].tolist()
    action_ids = [a.action_id for a in actions]
    idx = {t: i for i, t in enumerate(txn_ids)}
    jdx = {a: j for j, a in enumerate(action_ids)}
    mat = np.zeros((len(txn_ids), len(action_ids)), dtype=float)
    for row in predictions.to_dict(orient="records"):
        i = idx.get(row.get("transaction_id"))
        j = jdx.get(row.get("action_id"))
        if i is not None and j is not None:
            mat[i, j] = float(row.get("predicted_recovery_probability", 0.0))
    return mat


__all__ = [
    "ActionSpec",
    "live_score",
    "load_actions",
    "load_customers",
    "load_frozen_model",
    "load_predictions_csv",
    "load_transactions",
    "predictions_matrix",
]
