"""Feature engineering package for Step 2.

Modules are *pure functions* of (transactions, customers, recovery_actions,
historical_outcomes). They never touch the label and never see the test
split during fit. The orchestrator :mod:`ml.features.pipeline` joins the
per-group outputs into a single feature matrix that downstream preprocessing
turns into a numeric matrix.
"""
from __future__ import annotations

from .transaction_features import build_transaction_features
from .customer_features import build_customer_features
from .temporal_features import build_temporal_features
from .payment_features import build_payment_features
from .action_features import build_action_features
from .interaction_features import build_interaction_features
from .pipeline import (
    FeatureSpec,
    FEATURE_GROUPS,
    build_step2_feature_frame,
    resolve_feature_spec,
)

__all__ = [
    "build_transaction_features",
    "build_customer_features",
    "build_temporal_features",
    "build_payment_features",
    "build_action_features",
    "build_interaction_features",
    "FeatureSpec",
    "FEATURE_GROUPS",
    "build_step2_feature_frame",
    "resolve_feature_spec",
]
