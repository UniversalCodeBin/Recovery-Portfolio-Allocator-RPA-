"""Payment and failure-method features.

These features represent the *categorical* surface of the transaction that
the model needs as numeric input. One-hot encoding of categoricals happens
inside :mod:`ml.preprocessing` (fit on train only) so this module simply
preserves the categorical columns plus a few numeric flags:

* ``payment_method``         — string. One-hot encoded downstream.
* ``bank``                   — string. One-hot encoded downstream.
* ``failure_reason``         — string. One-hot encoded downstream.
* ``is_retry_exhausted``     — 1 iff retry_count >= 3 (proxy for "many
                               attempts already failed").
* ``is_long_overdue``        — 1 iff days_overdue >= 30.
"""
from __future__ import annotations

import pandas as pd

CATEGORICAL_COLUMNS: list[str] = [
    "payment_method",
    "bank",
    "failure_reason",
]

PAYMENT_NUMERIC_FEATURES: list[str] = [
    "is_retry_exhausted",
    "is_long_overdue",
]

PAYMENT_OUTPUT_COLUMNS: list[str] = CATEGORICAL_COLUMNS + PAYMENT_NUMERIC_FEATURES


def build_payment_features(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return per-transaction payment/failure categorical + numeric features."""
    if transactions.empty:
        return pd.DataFrame(columns=["transaction_id"] + PAYMENT_OUTPUT_COLUMNS)

    df = pd.DataFrame({
        "transaction_id": transactions["transaction_id"],
        "payment_method": transactions["payment_method"].astype(str),
        "bank": transactions["bank"].astype(str),
        "failure_reason": transactions["failure_reason"].astype(str),
    })
    rc = pd.to_numeric(transactions["retry_count"], errors="coerce").fillna(0).astype(int)
    do = pd.to_numeric(transactions["days_overdue"], errors="coerce").fillna(0).astype(int)
    df["is_retry_exhausted"] = (rc >= 3).astype(int)
    df["is_long_overdue"] = (do >= 30).astype(int)
    return df[["transaction_id"] + PAYMENT_OUTPUT_COLUMNS]


__all__ = [
    "CATEGORICAL_COLUMNS",
    "PAYMENT_NUMERIC_FEATURES",
    "PAYMENT_OUTPUT_COLUMNS",
    "build_payment_features",
]
