"""Temporal features derived from transaction timestamps.

All features here are *deterministic functions of the transaction's own
timestamps* (already validated in Step 1 to be internally consistent with
``due_date`` and the reference date ``2026-09-04``).

Documented rationale
--------------------
* ``day_of_week``        — 0..6 (Monday..Sunday). Failure recovery behaviour
                           often differs on weekends (customer reachability,
                           support capacity).
* ``hour_of_day``        — 0..23, bucketed into 4 bins: night, morning,
                           afternoon, evening. Hour is rarely informative
                           on its own in a small dataset, but a coarse
                           bucket can carry signal.
* ``is_weekend``         — 1 iff day_of_week in {5, 6}.
* ``days_overdue``       — already in transaction_features; *intentionally*
                           not duplicated here to keep the column set clean.
* ``due_in_future``      — 1 iff due_date > reference_date (anomalous but
                           useful signal).
* ``txn_age_days``       — (reference_date - transaction_timestamp).days. A
                           proxy for how stale the transaction is.

The reference date is fixed by Step 1 (``DEFAULT_REFERENCE_DATE``) so the
features are deterministic across runs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_core.config import DEFAULT_REFERENCE_DATE

TEMPORAL_NUMERIC_FEATURES: list[str] = [
    "day_of_week",
    "hour_of_day",
    "is_weekend",
    "is_morning",
    "is_afternoon",
    "is_evening",
    "is_night",
    "txn_age_days",
    "due_in_future",
]

TEMPORAL_OUTPUT_COLUMNS: list[str] = TEMPORAL_NUMERIC_FEATURES


def _safe_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def build_temporal_features(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return per-transaction temporal features."""
    if transactions.empty:
        return pd.DataFrame(columns=["transaction_id"] + TEMPORAL_OUTPUT_COLUMNS)

    txn_ts = _safe_dt(transactions["transaction_timestamp"])
    due_dt = _safe_dt(transactions["due_date"])
    ref = pd.Timestamp(DEFAULT_REFERENCE_DATE, tz="UTC")

    df = pd.DataFrame({"transaction_id": transactions["transaction_id"]})
    df["day_of_week"] = txn_ts.dt.dayofweek.fillna(0).astype(int)
    df["hour_of_day"] = txn_ts.dt.hour.fillna(0).astype(int)
    df["is_weekend"] = ((df["day_of_week"] == 5) | (df["day_of_week"] == 6)).astype(int)
    df["is_morning"] = ((df["hour_of_day"] >= 6) & (df["hour_of_day"] < 12)).astype(int)
    df["is_afternoon"] = ((df["hour_of_day"] >= 12) & (df["hour_of_day"] < 18)).astype(int)
    df["is_evening"] = ((df["hour_of_day"] >= 18) & (df["hour_of_day"] < 22)).astype(int)
    df["is_night"] = ((df["hour_of_day"] >= 22) | (df["hour_of_day"] < 6)).astype(int)
    df["txn_age_days"] = ((ref - txn_ts).dt.total_seconds() / 86400.0).fillna(0.0)
    df["due_in_future"] = (due_dt > ref).astype(int)
    return df[["transaction_id"] + TEMPORAL_OUTPUT_COLUMNS]


__all__ = [
    "TEMPORAL_NUMERIC_FEATURES",
    "TEMPORAL_OUTPUT_COLUMNS",
    "build_temporal_features",
]
