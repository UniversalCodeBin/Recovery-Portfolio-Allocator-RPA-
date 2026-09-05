"""Feature-pipeline orchestrator.

Joins per-group features into a single per-(transaction, action) frame
that downstream preprocessing turns into the numeric matrix X.

Public entry point: :func:`build_step2_feature_frame`.

The pipeline is **deterministic** and **leakage-safe** by construction:

* All feature modules are pure functions of the inputs (no fitted state).
* The action_outcomes table is used *only* for labels
  (:func:`ml.data_io.build_labeled_pairs`), never as features.
* Categorical vocabularies are not materialized here — that happens in
  :mod:`ml.preprocessing` (fit on train only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .action_features import ACTION_OUTPUT_COLUMNS, build_action_features
from .customer_features import CUSTOMER_OUTPUT_COLUMNS, build_customer_features
from .interaction_features import INTERACTION_OUTPUT_COLUMNS, build_interaction_features
from .payment_features import PAYMENT_OUTPUT_COLUMNS, build_payment_features
from .temporal_features import TEMPORAL_OUTPUT_COLUMNS, build_temporal_features
from .transaction_features import TRANSACTION_OUTPUT_COLUMNS, build_transaction_features

from ml.config import FeatureFlags


@dataclass(frozen=True)
class FeatureSpec:
    """Resolved set of feature columns and which groups are enabled."""

    numeric_columns: List[str] = field(default_factory=list)
    categorical_columns: List[str] = field(default_factory=list)
    interaction_columns: List[str] = field(default_factory=list)
    enabled_groups: Dict[str, bool] = field(default_factory=dict)


FEATURE_GROUPS: Dict[str, Dict[str, List[str]]] = {
    "transaction": {"numeric": TRANSACTION_OUTPUT_COLUMNS, "categorical": []},
    "customer":    {"numeric": CUSTOMER_OUTPUT_COLUMNS, "categorical": []},
    "temporal":    {"numeric": TEMPORAL_OUTPUT_COLUMNS, "categorical": []},
    "payment":     {"numeric": [c for c in PAYMENT_OUTPUT_COLUMNS
                                  if c not in ("payment_method", "bank", "failure_reason")],
                    "categorical": ["payment_method", "bank", "failure_reason"]},
    "action":      {"numeric": [c for c in ACTION_OUTPUT_COLUMNS if c != "action_type"],
                    "categorical": ["action_type"]},
    "interaction": {"numeric": INTERACTION_OUTPUT_COLUMNS, "categorical": []},
}


def resolve_feature_spec(flags: FeatureFlags) -> FeatureSpec:
    """Compute the column lists implied by a :class:`FeatureFlags` instance."""
    numeric: List[str] = []
    categorical: List[str] = []
    interaction: List[str] = []
    enabled: Dict[str, bool] = {
        "transaction": flags.transaction,
        "customer": flags.customer,
        "temporal": flags.temporal,
        "payment": flags.payment,
        "action": flags.action,
        "interactions": flags.interactions,
    }
    for group, on in enabled.items():
        if not on:
            continue
        cfg = FEATURE_GROUPS["interaction" if group == "interactions" else group]
        if group == "interactions":
            interaction += list(cfg["numeric"])
        else:
            numeric += list(cfg["numeric"])
            categorical += list(cfg["categorical"])
    # De-dup but preserve order.
    def _dedup(xs: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return FeatureSpec(
        numeric_columns=_dedup(numeric),
        categorical_columns=_dedup(categorical),
        interaction_columns=_dedup(interaction),
        enabled_groups=enabled,
    )


def build_step2_feature_frame(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    recovery_actions: pd.DataFrame,
    action_ids: List[str],
    flags: FeatureFlags,
) -> pd.DataFrame:
    """Build the per-(transaction, action) feature frame for one split.

    The returned DataFrame has columns:

        transaction_id, action_id, recovered, recovered_amount,
        <numeric features...>, <categorical features...>

    Categorical columns are kept as strings — :mod:`ml.preprocessing`
    performs the train-fitted one-hot encoding.
    """
    spec = resolve_feature_spec(flags)

    # Per-group feature frames (each carries transaction_id).
    txn_feat = build_transaction_features(transactions, customers) if flags.transaction else None
    cust_feat = build_customer_features(transactions, customers) if flags.customer else None
    temp_feat = build_temporal_features(transactions) if flags.temporal else None
    pay_feat = build_payment_features(transactions) if flags.payment else None

    # Build action feature rows (one per candidate action).
    act_feat = build_action_features(action_ids, recovery_actions) if flags.action else None

    # Cartesian product (transaction x action).
    base = pd.MultiIndex.from_product(
        [transactions["transaction_id"].tolist(), action_ids],
        names=["transaction_id", "action_id"],
    ).to_frame(index=False)

    pieces = [base]
    for feat in (txn_feat, cust_feat, temp_feat, pay_feat):
        if feat is not None:
            pieces.append(feat)
    joined = pieces[0]
    for feat in pieces[1:]:
        joined = joined.merge(feat, on="transaction_id", how="left")
    if act_feat is not None:
        joined = joined.merge(act_feat, on="action_id", how="left")

    if flags.interactions:
        inter = build_interaction_features(joined)
        joined = joined.merge(inter, on=["transaction_id", "action_id"], how="left")

    return joined


__all__ = [
    "FeatureSpec",
    "FEATURE_GROUPS",
    "resolve_feature_spec",
    "build_step2_feature_frame",
]
