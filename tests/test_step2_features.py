"""Step 2 feature-engineering tests.

Validates that the per-group feature builders:
* produce the expected columns,
* emit deterministic, in-range numerics,
* do not introduce unexpected NaNs,
* are reproducible across runs.

These tests do NOT train a model; the leakage / model / prediction tests live
in their respective files.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_core.generator import SyntheticDataGenerator
from ml.config import FeatureFlags
from ml.features import build_step2_feature_frame, resolve_feature_spec
from ml.features.action_features import build_action_features
from ml.features.customer_features import build_customer_features
from ml.features.interaction_features import build_interaction_features
from ml.features.payment_features import build_payment_features
from ml.features.temporal_features import build_temporal_features
from ml.features.transaction_features import build_transaction_features


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def generated():
    gen = SyntheticDataGenerator(42)
    return gen.generate(n_customers=60, target_total=600)


@pytest.fixture(scope="module")
def frames(generated):
    return generated.to_frames()


@pytest.fixture(scope="module")
def actions(frames):
    return frames["recovery_actions"]


# ---------------------------------------------------------------------------
# 1. Expected columns
# ---------------------------------------------------------------------------
EXPECTED_NUMERIC = {
    "transaction": ["amount", "log_amount", "retry_count", "days_overdue",
                    "is_pending", "is_charged_back", "amount_over_ltv"],
    "customer": ["customer_ltv", "log_customer_ltv", "historical_success_rate",
                 "historical_recovery_rate", "customer_behavior_score",
                 "customer_tenure_days", "log_customer_tenure",
                 "is_business_segment", "is_enterprise_segment"],
    "temporal": ["day_of_week", "hour_of_day", "is_weekend", "is_morning",
                 "is_afternoon", "is_evening", "is_night",
                 "txn_age_days", "due_in_future"],
    "payment": ["is_retry_exhausted", "is_long_overdue"],
    "action": ["action_cost", "action_resource_count", "uses_retry",
               "uses_messaging", "uses_incentive", "uses_human", "is_no_op"],
    "interaction": ["retry_count_x_action", "days_overdue_x_action",
                    "ltv_x_action", "recovery_rate_x_action",
                    "behavior_x_action",
                    "failure_insufficient_x_retry_action",
                    "payment_upi_x_messaging"],
}


def test_transaction_columns(frames):
    df = build_transaction_features(frames["transactions"], frames["customers"])
    for col in EXPECTED_NUMERIC["transaction"]:
        assert col in df.columns, f"missing transaction column {col}"
    assert (df["amount"] > 0).all()
    assert (df["log_amount"] >= 0).all()
    assert (df["retry_count"] >= 0).all()
    assert (df["days_overdue"] >= 0).all()
    assert df["is_pending"].isin([0, 1]).all()
    assert df["is_charged_back"].isin([0, 1]).all()


def test_customer_columns(frames):
    df = build_customer_features(frames["transactions"], frames["customers"])
    for col in EXPECTED_NUMERIC["customer"]:
        assert col in df.columns, f"missing customer column {col}"
    assert (df["customer_ltv"] > 0).all()
    assert (df["historical_success_rate"] >= 0).all() and (df["historical_success_rate"] <= 1).all()
    assert (df["historical_recovery_rate"] >= 0).all() and (df["historical_recovery_rate"] <= 1).all()
    assert df["is_business_segment"].isin([0, 1]).all()
    assert df["is_enterprise_segment"].isin([0, 1]).all()


def test_temporal_columns(frames):
    df = build_temporal_features(frames["transactions"])
    for col in EXPECTED_NUMERIC["temporal"]:
        assert col in df.columns, f"missing temporal column {col}"
    assert (df["day_of_week"] >= 0).all() and (df["day_of_week"] <= 6).all()
    assert (df["hour_of_day"] >= 0).all() and (df["hour_of_day"] <= 23).all()
    assert df["is_weekend"].isin([0, 1]).all()


def test_payment_columns(frames):
    df = build_payment_features(frames["transactions"])
    for col in EXPECTED_NUMERIC["payment"]:
        assert col in df.columns, f"missing payment column {col}"
    assert df["is_retry_exhausted"].isin([0, 1]).all()
    assert df["is_long_overdue"].isin([0, 1]).all()
    # categorical columns preserved
    assert "payment_method" in df.columns
    assert "bank" in df.columns
    assert "failure_reason" in df.columns


def test_action_columns(frames):
    action_ids = frames["recovery_actions"]["action_id"].tolist()
    df = build_action_features(action_ids, frames["recovery_actions"])
    for col in EXPECTED_NUMERIC["action"]:
        assert col in df.columns, f"missing action column {col}"
    assert "action_type" in df.columns
    assert (df["action_cost"] >= 0).all()
    assert df["is_no_op"].isin([0, 1]).all()
    assert (df["uses_retry"] | df["uses_messaging"] | df["uses_incentive"] | df["uses_human"]).sum() >= 0


# ---------------------------------------------------------------------------
# 2. No unexpected NaNs
# ---------------------------------------------------------------------------
def test_no_unexpected_nans(frames):
    spec = resolve_feature_spec(FeatureFlags())
    df = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        frames["recovery_actions"]["action_id"].tolist(), FeatureFlags(),
    )
    feature_cols = spec.numeric_columns + spec.categorical_columns + spec.interaction_columns
    for col in feature_cols:
        if col in df.columns:
            n_nan = int(df[col].isna().sum())
            assert n_nan == 0, f"unexpected NaNs in {col}: {n_nan}"


# ---------------------------------------------------------------------------
# 3. Categorical encoding is deterministic
# ---------------------------------------------------------------------------
def test_categorical_encoding_deterministic(frames):
    spec = resolve_feature_spec(FeatureFlags())
    a = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        frames["recovery_actions"]["action_id"].tolist(), FeatureFlags(),
    )
    b = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        frames["recovery_actions"]["action_id"].tolist(), FeatureFlags(),
    )
    for col in spec.categorical_columns:
        assert a[col].tolist() == b[col].tolist(), f"{col} is non-deterministic"


# ---------------------------------------------------------------------------
# 4. Interaction features are deterministic
# ---------------------------------------------------------------------------
def test_interactions_deterministic(frames):
    action_ids = frames["recovery_actions"]["action_id"].tolist()
    joined = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        action_ids, FeatureFlags(),
    )
    a = build_interaction_features(joined)
    b = build_interaction_features(joined)
    for col in a.columns:
        if col == "transaction_id" or col == "action_id":
            continue
        np.testing.assert_array_equal(a[col].to_numpy(), b[col].to_numpy())


# ---------------------------------------------------------------------------
# 5. Pipeline is reproducible
# ---------------------------------------------------------------------------
def test_feature_pipeline_reproducible(frames):
    action_ids = frames["recovery_actions"]["action_id"].tolist()
    a = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        action_ids, FeatureFlags(),
    )
    b = build_step2_feature_frame(
        frames["transactions"], frames["customers"], frames["recovery_actions"],
        action_ids, FeatureFlags(),
    )
    # All numeric columns must match bit-for-bit.
    spec = resolve_feature_spec(FeatureFlags())
    for col in spec.numeric_columns + spec.interaction_columns:
        np.testing.assert_array_equal(a[col].to_numpy(), b[col].to_numpy())


# ---------------------------------------------------------------------------
# 6. Feature spec respects flags
# ---------------------------------------------------------------------------
def test_feature_spec_flags():
    spec = resolve_feature_spec(FeatureFlags(
        transaction=True, customer=False, temporal=False,
        payment=True, action=False, interactions=False,
    ))
    # Transaction is on -> amount appears.
    assert "amount" in spec.numeric_columns
    # Customer is off -> customer columns absent.
    for col in EXPECTED_NUMERIC["customer"]:
        assert col not in spec.numeric_columns, f"{col} should be absent"
    # Action is off -> action_type absent.
    assert "action_type" not in spec.categorical_columns
    # Payment is on -> payment categoricals present.
    for col in ("payment_method", "bank", "failure_reason"):
        assert col in spec.categorical_columns


def test_feature_spec_toggle_groups():
    all_on = resolve_feature_spec(FeatureFlags())
    no_inter = resolve_feature_spec(FeatureFlags(interactions=False))
    # Disabling interactions removes interaction columns.
    for col in EXPECTED_NUMERIC["interaction"]:
        assert col in all_on.interaction_columns
        assert col not in no_inter.interaction_columns
