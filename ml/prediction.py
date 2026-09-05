"""Step 2 prediction layer.

Given a trained frozen model, generate per-(transaction, action) probability
estimates for the test/demo/eval splits, persist them as CSV + populate the
``recovery_predictions`` table.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from .config import DB_PREDICTIONS_TABLE, PREDICTIONS_DIR
from .data_io import build_labeled_pairs
from .features import build_step2_feature_frame
from .model import TrainedLogisticModel
from .versioning import now_iso


def _new_prediction_id() -> str:
    return f"pred_{uuid.uuid4().hex[:12]}"


@dataclass
class PredictionRecord:
    prediction_id: str
    transaction_id: str
    action_id: str
    model_identifier: str
    predicted_recovery_probability: float
    prediction_timestamp: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "prediction_id": self.prediction_id,
            "transaction_id": self.transaction_id,
            "action_id": self.action_id,
            "model_identifier": self.model_identifier,
            "predicted_recovery_probability": self.predicted_recovery_probability,
            "prediction_timestamp": self.prediction_timestamp,
        }


def generate_predictions(
    model: TrainedLogisticModel,
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    recovery_actions: pd.DataFrame,
    feature_flags,
) -> pd.DataFrame:
    """Score every (transaction, action) pair with the frozen model.

    Returns a DataFrame with columns:
        transaction_id, action_id, predicted_recovery_probability,
        model_identifier, prediction_timestamp, prediction_id
    """
    action_ids = recovery_actions["action_id"].tolist()
    feat_df = build_step2_feature_frame(
        transactions, customers, recovery_actions, action_ids, feature_flags
    )
    p = model.predict_proba(feat_df)
    now = now_iso()
    pred_ids = [_new_prediction_id() for _ in range(len(feat_df))]
    out = pd.DataFrame({
        "transaction_id": feat_df["transaction_id"].tolist(),
        "action_id": feat_df["action_id"].tolist(),
        "predicted_recovery_probability": p.astype(float),
        "model_identifier": model.model_identifier,
        "prediction_timestamp": now,
        "prediction_id": pred_ids,
    })
    return out


def predictions_with_truth(
    predictions: pd.DataFrame,
    transactions: pd.DataFrame,
    action_outcomes: pd.DataFrame,
    recovery_actions: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the observed ``recovered`` label (for evaluation)."""
    labels = build_labeled_pairs(transactions, action_outcomes, recovery_actions, seed=0)
    labels = labels[["transaction_id", "action_id", "recovered"]]
    return predictions.merge(labels, on=["transaction_id", "action_id"], how="left")


def save_predictions_csv(
    predictions: pd.DataFrame,
    path: Optional[Path] = None,
) -> Path:
    path = path or (PREDICTIONS_DIR / "recovery_predictions.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(path, index=False)
    return path


def predictions_to_db_records(
    predictions: pd.DataFrame,
) -> List[Dict[str, object]]:
    """Convert prediction rows to DB insert dicts.

    Columns must match the ``recovery_predictions`` table from Step 1.
    """
    cols = ["prediction_id", "transaction_id", "action_id", "model_identifier",
            "predicted_recovery_probability", "prediction_timestamp"]
    return predictions[cols].to_dict(orient="records")


def insert_predictions_to_db(
    predictions: pd.DataFrame,
    schema: str = "rpa",
    table: str = DB_PREDICTIONS_TABLE,
    reset_table: bool = False,
) -> int:
    """Insert predictions into the ``recovery_predictions`` table.

    Returns the number of inserted rows. Silently skips if the DB is not
    reachable (logs to stdout). The Step 1 ``Database.load_frame`` handles
    column-quoting + COPY-based loading; we reuse it.
    """
    try:
        from data_core.db import Database
    except ImportError:
        print("[step2] data_core.db not importable; skipping DB insert")
        return 0
    try:
        from data_core.db import connect
        conn = connect()
    except Exception as exc:
        print(f"[step2] DB unavailable, skipping insert: {exc}")
        return 0

    df = predictions.copy()
    df["predicted_recovery_probability"] = pd.to_numeric(
        df["predicted_recovery_probability"], errors="coerce"
    ).astype(float)
    try:
        db = Database(schema=schema)
        n = db.load_frame(conn, table, df, reset_table=reset_table)
        conn.close()
        return int(n)
    except Exception as exc:
        print(f"[step2] DB insert failed: {exc}")
        try:
            conn.close()
        except Exception:
            pass
        return 0


__all__ = [
    "PredictionRecord",
    "generate_predictions",
    "predictions_with_truth",
    "save_predictions_csv",
    "predictions_to_db_records",
    "insert_predictions_to_db",
]
