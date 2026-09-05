"""Transaction-level features.

Pure functions of the per-transaction row in
``data/validated/transactions.csv``. No customer-history, no temporal context,
no leakage.

Documented rationale for each feature
------------------------------------
* ``amount``             — raw rupee value of the failed payment.
* ``log_amount``         — log(1 + amount); amount is heavy-tailed (lognormal
                           in Step 1 generator) so the log scale is more
                           informative for a linear model.
* ``retry_count``        — number of previous attempts; correlates with how
                           badly the payment is failing.
* ``days_overdue``       — how long the payment has been overdue.
* ``is_pending``         — 1 iff transaction_status == 'pending'.
* ``is_charged_back``    — 1 iff transaction_status == 'charged_back' (rare
                           and indicates prior dispute).
* ``amount_over_ltv``    — amount / customer_ltv. Indicates whether the
                           transaction is large relative to the customer's
                           typical spend (a proxy for "outlier" payments
                           that may behave differently).

All numerics are emitted as float; categorical fields (``payment_method``,
``bank``, ``failure_reason``) are *not* duplicated here — they live in
:mod:`ml.features.payment_features`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Columns this module produces (the orchestrator will project to these).
TRANSACTION_NUMERIC_FEATURES: list[str] = [
    "amount",
    "log_amount",
    "retry_count",
    "days_overdue",
    "is_pending",
    "is_charged_back",
    "amount_over_ltv",
]

TRANSACTION_OUTPUT_COLUMNS: list[str] = TRANSACTION_NUMERIC_FEATURES


def build_transaction_features(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
) -> pd.DataFrame:
    """Return a DataFrame with transaction_id + the transaction feature columns.

    The customer DataFrame is required only for ``amount_over_ltv``; it must
    contain at minimum ``customer_id`` and ``customer_ltv``.
    """
    if transactions.empty:
        return pd.DataFrame(columns=["transaction_id"] + TRANSACTION_OUTPUT_COLUMNS)

    df = transactions[["transaction_id", "customer_id", "amount", "retry_count",
                       "days_overdue", "transaction_status"]].copy()

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").astype(float)
    df["retry_count"] = pd.to_numeric(df["retry_count"], errors="coerce").fillna(0).astype(float)
    df["days_overdue"] = pd.to_numeric(df["days_overdue"], errors="coerce").fillna(0).astype(float)
    df["log_amount"] = np.log1p(df["amount"]).astype(float)
    df["is_pending"] = (df["transaction_status"] == "pending").astype(int)
    df["is_charged_back"] = (df["transaction_status"] == "charged_back").astype(int)

    ltv = customers.set_index("customer_id")["customer_ltv"].astype(float)
    cust_ltv = df["customer_id"].map(ltv).fillna(ltv.median())
    df["amount_over_ltv"] = (df["amount"] / cust_ltv.replace(0, np.nan)).fillna(0.0)

    return df[["transaction_id"] + TRANSACTION_OUTPUT_COLUMNS]


__all__ = [
    "TRANSACTION_NUMERIC_FEATURES",
    "TRANSACTION_OUTPUT_COLUMNS",
    "build_transaction_features",
]
