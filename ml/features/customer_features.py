"""Customer-history features.

Pure pass-through of the *static* per-customer properties already materialized
at Step 1 generation time. These do not aggregate over the transaction set —
they are pre-computed properties of the customer that any predictor could
reasonably access at inference time without leakage.

Documented rationale
--------------------
* ``customer_ltv``              — total customer lifetime value (signal of
                                 importance / ability-to-pay).
* ``historical_success_rate``   — past success rate on attempted payments;
                                 a known predictor of future recovery.
* ``historical_recovery_rate``  — past recovery rate from failed payments;
                                 the most direct historical analogue of
                                 the target.
* ``customer_behavior_score``   — composite latent behavior score (Step 1
                                 latent dimension; sign and magnitude carry
                                 risk information).
* ``customer_tenure_days``      — how long the customer has been a customer.
* ``log_customer_ltv``          — log(1 + ltv) to reduce skew.
* ``log_customer_tenure``       — log(1 + tenure_days).
* ``is_business_segment``       — 1 iff customer_segment == 'business'.
* ``is_enterprise_segment``     — 1 iff customer_segment == 'enterprise'.

These features are *always available at prediction time* — they live on the
customer record, not the transaction — so they are 100% leakage-safe.

No aggregate is built over a customer's own transactions (Step 1 forbids
that to prevent per-customer leakage across splits; even within a single
split, doing so would inflate importance of repeated transactions).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CUSTOMER_NUMERIC_FEATURES: list[str] = [
    "customer_ltv",
    "log_customer_ltv",
    "historical_success_rate",
    "historical_recovery_rate",
    "customer_behavior_score",
    "customer_tenure_days",
    "log_customer_tenure",
    "is_business_segment",
    "is_enterprise_segment",
]

CUSTOMER_OUTPUT_COLUMNS: list[str] = CUSTOMER_NUMERIC_FEATURES


def build_customer_features(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
) -> pd.DataFrame:
    """Return per-transaction customer features (one row per transaction)."""
    if transactions.empty:
        return pd.DataFrame(columns=["transaction_id"] + CUSTOMER_OUTPUT_COLUMNS)

    cust = customers[
        ["customer_id", "customer_segment", "customer_ltv",
         "historical_success_rate", "historical_recovery_rate",
         "customer_behavior_score", "customer_tenure_days"]
    ].copy()

    cust["customer_ltv"] = pd.to_numeric(cust["customer_ltv"], errors="coerce").astype(float)
    cust["historical_success_rate"] = pd.to_numeric(cust["historical_success_rate"], errors="coerce").astype(float)
    cust["historical_recovery_rate"] = pd.to_numeric(cust["historical_recovery_rate"], errors="coerce").astype(float)
    cust["customer_behavior_score"] = pd.to_numeric(cust["customer_behavior_score"], errors="coerce").astype(float)
    cust["customer_tenure_days"] = pd.to_numeric(cust["customer_tenure_days"], errors="coerce").fillna(0).astype(float)

    cust["log_customer_ltv"] = np.log1p(cust["customer_ltv"]).astype(float)
    cust["log_customer_tenure"] = np.log1p(cust["customer_tenure_days"]).astype(float)
    cust["is_business_segment"] = (cust["customer_segment"] == "business").astype(int)
    cust["is_enterprise_segment"] = (cust["customer_segment"] == "enterprise").astype(int)

    keep = ["customer_id"] + CUSTOMER_OUTPUT_COLUMNS
    return transactions[["transaction_id", "customer_id"]].merge(cust[keep], on="customer_id", how="left")


__all__ = [
    "CUSTOMER_NUMERIC_FEATURES",
    "CUSTOMER_OUTPUT_COLUMNS",
    "build_customer_features",
]
