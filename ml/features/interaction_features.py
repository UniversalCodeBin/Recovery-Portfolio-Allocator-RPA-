"""Interaction features (configurable).

The previous RPA experiment was NEUTRAL, so interactions are *not* assumed
to be useful. We define a small, defensible set of plausible interactions and
let the ablation tell us whether they actually contribute.

Plausible interactions (one is created per row in the labeled (txn, action)
frame so they live at the (txn, action) level, not the txn level):

* ``retry_count_x_action``        — retry_count * action_cost
* ``days_overdue_x_action``        — days_overdue * action_cost
* ``ltv_x_action``                 — log_customer_ltv * action_cost
* ``recovery_rate_x_action``       — historical_recovery_rate * action_cost
* ``behavior_x_action``            — customer_behavior_score * action_cost
* ``failure_reason_x_retry_action``— (failure_reason=='insufficient_funds') *
                                    uses_retry
* ``payment_method_x_messaging``   — (payment_method=='upi') * uses_messaging

Every interaction is computed deterministically from columns that already
exist in the joined feature frame, so re-running on the same data + seed
produces identical interaction columns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INTERACTION_OUTPUT_COLUMNS: list[str] = [
    "retry_count_x_action",
    "days_overdue_x_action",
    "ltv_x_action",
    "recovery_rate_x_action",
    "behavior_x_action",
    "failure_insufficient_x_retry_action",
    "payment_upi_x_messaging",
]


def build_interaction_features(joined: pd.DataFrame) -> pd.DataFrame:
    """Add interaction columns to ``joined`` (which must already contain the
    constituent columns).

    Required input columns:
        transaction_id, action_id, retry_count, days_overdue,
        log_customer_ltv, historical_recovery_rate, customer_behavior_score,
        failure_reason, payment_method, action_cost, uses_retry,
        uses_messaging
    """
    out = pd.DataFrame({"transaction_id": joined["transaction_id"],
                        "action_id": joined["action_id"]})
    rc = pd.to_numeric(joined["retry_count"], errors="coerce").fillna(0.0).astype(float)
    do = pd.to_numeric(joined["days_overdue"], errors="coerce").fillna(0.0).astype(float)
    ltv = pd.to_numeric(joined["log_customer_ltv"], errors="coerce").fillna(0.0).astype(float)
    rr = pd.to_numeric(joined["historical_recovery_rate"], errors="coerce").fillna(0.0).astype(float)
    bh = pd.to_numeric(joined["customer_behavior_score"], errors="coerce").fillna(0.0).astype(float)
    cost = pd.to_numeric(joined["action_cost"], errors="coerce").fillna(0.0).astype(float)
    uses_retry = pd.to_numeric(joined["uses_retry"], errors="coerce").fillna(0).astype(float)
    uses_msg = pd.to_numeric(joined["uses_messaging"], errors="coerce").fillna(0).astype(float)

    out["retry_count_x_action"] = rc * cost
    out["days_overdue_x_action"] = do * cost
    out["ltv_x_action"] = ltv * cost
    out["recovery_rate_x_action"] = rr * cost
    out["behavior_x_action"] = bh * cost

    fr = joined["failure_reason"].astype(str) == "insufficient_funds"
    out["failure_insufficient_x_retry_action"] = (fr.astype(int) * uses_retry).astype(float)

    pm = joined["payment_method"].astype(str) == "upi"
    out["payment_upi_x_messaging"] = (pm.astype(int) * uses_msg).astype(float)

    return out[["transaction_id", "action_id"] + INTERACTION_OUTPUT_COLUMNS]


__all__ = [
    "INTERACTION_OUTPUT_COLUMNS",
    "build_interaction_features",
]
