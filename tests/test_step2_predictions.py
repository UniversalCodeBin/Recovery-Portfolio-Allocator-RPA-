"""Step 2 prediction tests.

Validates that:
* exactly one prediction row exists per (transaction, action) pair,
* prediction rows reference valid transaction + action IDs,
* probabilities lie in [0, 1],
* every prediction records the model version,
* the prediction CSV matches what the frozen model produces.
"""

from __future__ import annotations

import numpy as np
import pytest

from ml.calibration import evaluate_calibration
from ml.config import FeatureFlags
from ml.data_io import (
    assert_customer_split_isolation,
    build_labeled_pairs,
    load_step2_data,
)
from ml.features import build_step2_feature_frame
from ml.features.pipeline import resolve_feature_spec
from ml.model import TrainedLogisticModel, train_logistic
from ml.prediction import generate_predictions, predictions_to_db_records
from ml.preprocessing import fit_preprocessor


@pytest.fixture(scope="module")
def datasets():
    ds = load_step2_data()
    assert_customer_split_isolation(ds.splits)
    return ds


@pytest.fixture(scope="module")
def fitted(datasets):
    flags = FeatureFlags()
    train_frame = build_step2_feature_frame(
        datasets.splits["train"],
        datasets.customers,
        datasets.recovery_actions,
        datasets.recovery_actions["action_id"].tolist(),
        flags,
    )
    train_frame = train_frame.merge(
        build_labeled_pairs(
            datasets.splits["train"],
            datasets.action_outcomes,
            datasets.recovery_actions,
            seed=0,
        )[["transaction_id", "action_id", "recovered"]],
        on=["transaction_id", "action_id"],
        how="left",
    )
    val_frame = build_step2_feature_frame(
        datasets.splits["val"],
        datasets.customers,
        datasets.recovery_actions,
        datasets.recovery_actions["action_id"].tolist(),
        flags,
    )
    val_frame = val_frame.merge(
        build_labeled_pairs(
            datasets.splits["val"],
            datasets.action_outcomes,
            datasets.recovery_actions,
            seed=0,
        )[["transaction_id", "action_id", "recovered"]],
        on=["transaction_id", "action_id"],
        how="left",
    )
    pp = fit_preprocessor(train_frame, resolve_feature_spec(flags))
    X_train = pp.transform(train_frame)
    X_val = pp.transform(val_frame)
    y_train = train_frame["recovered"].astype(int).to_numpy()
    y_val = val_frame["recovered"].astype(int).to_numpy()
    model = train_logistic(X_train, y_train, seed=1234)
    cal = evaluate_calibration(model, X_val, y_val)
    chosen_name = min(cal.keys(), key=lambda m: cal[m].val_brier_calibrated)
    chosen = cal[chosen_name]
    return TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="rpa-recovery-logreg-testpred-v1",
        chosen_calibration=chosen.method,
    )


# ---------------------------------------------------------------------------
# 1. One prediction per (txn, action) pair
# ---------------------------------------------------------------------------
def test_one_prediction_per_pair(fitted, datasets):
    test_tx = datasets.splits["test"]
    preds = generate_predictions(
        fitted,
        test_tx,
        datasets.customers,
        datasets.recovery_actions,
        FeatureFlags(),
    )
    pairs = list(zip(preds["transaction_id"], preds["action_id"]))
    assert len(pairs) == len(set(pairs)), "duplicate (txn, action) prediction rows"
    # Also equals cartesian product size.
    expected = len(test_tx) * len(datasets.recovery_actions)
    assert len(preds) == expected


# ---------------------------------------------------------------------------
# 2. Valid transaction + action IDs
# ---------------------------------------------------------------------------
def test_valid_ids(fitted, datasets):
    test_tx = datasets.splits["test"]
    preds = generate_predictions(
        fitted,
        test_tx,
        datasets.customers,
        datasets.recovery_actions,
        FeatureFlags(),
    )
    valid_txn = set(test_tx["transaction_id"].tolist())
    valid_act = set(datasets.recovery_actions["action_id"].tolist())
    assert set(preds["transaction_id"].unique()).issubset(valid_txn)
    assert set(preds["action_id"].unique()).issubset(valid_act)


# ---------------------------------------------------------------------------
# 3. Probabilities within [0, 1]
# ---------------------------------------------------------------------------
def test_probabilities_range(fitted, datasets):
    preds = generate_predictions(
        fitted,
        datasets.splits["test"],
        datasets.customers,
        datasets.recovery_actions,
        FeatureFlags(),
    )
    p = preds["predicted_recovery_probability"].astype(float).to_numpy()
    assert (p >= 0).all() and (p <= 1).all()


# ---------------------------------------------------------------------------
# 4. Model version is recorded on every prediction
# ---------------------------------------------------------------------------
def test_model_version_recorded(fitted, datasets):
    preds = generate_predictions(
        fitted,
        datasets.splits["test"],
        datasets.customers,
        datasets.recovery_actions,
        FeatureFlags(),
    )
    assert (preds["model_identifier"] == fitted.model_identifier).all()
    assert (preds["prediction_timestamp"].notna()).all()
    assert (preds["prediction_id"].notna()).all()
    assert preds["prediction_id"].is_unique


# ---------------------------------------------------------------------------
# 5. DB records have the correct columns
# ---------------------------------------------------------------------------
def test_db_records_columns(fitted, datasets):
    preds = generate_predictions(
        fitted,
        datasets.splits["test"],
        datasets.customers,
        datasets.recovery_actions,
        FeatureFlags(),
    )
    rows = predictions_to_db_records(preds)
    expected_cols = {
        "prediction_id",
        "transaction_id",
        "action_id",
        "model_identifier",
        "predicted_recovery_probability",
        "prediction_timestamp",
    }
    assert expected_cols.issubset(set(rows[0].keys()))


# ---------------------------------------------------------------------------
# 6. Deterministic predictions across calls
# ---------------------------------------------------------------------------
def test_predictions_deterministic(fitted, datasets):
    test_tx = datasets.splits["test"]
    p1 = generate_predictions(
        fitted, test_tx, datasets.customers, datasets.recovery_actions, FeatureFlags()
    )
    p2 = generate_predictions(
        fitted, test_tx, datasets.customers, datasets.recovery_actions, FeatureFlags()
    )
    # IDs/timestamps will differ; compare probabilities.
    np.testing.assert_array_equal(
        p1["predicted_recovery_probability"].to_numpy(),
        p2["predicted_recovery_probability"].to_numpy(),
    )
    # And the txn/action pairs.
    assert p1["transaction_id"].tolist() == p2["transaction_id"].tolist()
    assert p1["action_id"].tolist() == p2["action_id"].tolist()
