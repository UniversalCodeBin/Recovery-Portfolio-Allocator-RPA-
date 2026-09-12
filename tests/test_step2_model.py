"""Step 2 model tests.

Validates:
* probabilities lie in [0, 1],
* the model can score every candidate action,
* predictions are deterministic under a fixed seed,
* calibration improves (or at minimum does not harm) Brier score on val,
* the trained model + preprocessor can be saved and reloaded and produce
  identical predictions.
"""

from __future__ import annotations

import numpy as np
import pytest

from ml.calibration import (
    evaluate_calibration,
    fit_isotonic_calibrator,
    fit_sigmoid_calibrator,
    predict_with_calibrator,
)
from ml.config import FeatureFlags
from ml.data_io import (
    assert_customer_split_isolation,
    build_labeled_pairs,
    load_step2_data,
)
from ml.features import build_step2_feature_frame
from ml.features.pipeline import resolve_feature_spec
from ml.model import TrainedLogisticModel, train_logistic
from ml.preprocessing import fit_preprocessor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def datasets():
    ds = load_step2_data()
    assert_customer_split_isolation(ds.splits)
    return ds


@pytest.fixture(scope="module")
def train_frame(datasets):
    flags = FeatureFlags()
    feat = build_step2_feature_frame(
        datasets.splits["train"],
        datasets.customers,
        datasets.recovery_actions,
        datasets.recovery_actions["action_id"].tolist(),
        flags,
    )
    labels = build_labeled_pairs(
        datasets.splits["train"],
        datasets.action_outcomes,
        datasets.recovery_actions,
        seed=0,
    )
    feat = feat.merge(
        labels[["transaction_id", "action_id", "recovered"]],
        on=["transaction_id", "action_id"],
        how="left",
    )
    return feat


@pytest.fixture(scope="module")
def val_frame(datasets):
    flags = FeatureFlags()
    feat = build_step2_feature_frame(
        datasets.splits["val"],
        datasets.customers,
        datasets.recovery_actions,
        datasets.recovery_actions["action_id"].tolist(),
        flags,
    )
    labels = build_labeled_pairs(
        datasets.splits["val"],
        datasets.action_outcomes,
        datasets.recovery_actions,
        seed=0,
    )
    feat = feat.merge(
        labels[["transaction_id", "action_id", "recovered"]],
        on=["transaction_id", "action_id"],
        how="left",
    )
    return feat


@pytest.fixture(scope="module")
def fitted(train_frame, val_frame):
    pp = fit_preprocessor(train_frame, resolve_feature_spec(FeatureFlags()))
    X_train = pp.transform(train_frame)
    X_val = pp.transform(val_frame)
    y_train = train_frame["recovered"].astype(int).to_numpy()
    y_val = val_frame["recovered"].astype(int).to_numpy()
    model = train_logistic(X_train, y_train, seed=1234)
    cal = evaluate_calibration(model, X_val, y_val)
    chosen_name = min(cal.keys(), key=lambda m: cal[m].val_brier_calibrated)
    return (
        pp,
        model,
        cal[chosen_name],
        train_frame,
        val_frame,
        X_train,
        X_val,
        y_train,
        y_val,
    )


# ---------------------------------------------------------------------------
# 1. Probabilities in [0, 1]
# ---------------------------------------------------------------------------
def test_probabilities_in_unit_interval(fitted):
    pp, model, chosen, _train_frame, val_frame, *_ = fitted
    trained = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="test-v1",
        chosen_calibration=chosen.method,
    )
    p = trained.predict_proba(val_frame)
    assert (p >= 0).all() and (p <= 1).all()


# ---------------------------------------------------------------------------
# 2. Model can score every candidate action
# ---------------------------------------------------------------------------
def test_scores_every_action(fitted, datasets):
    pp, model, chosen, _train_frame, val_frame, *_ = fitted
    trained = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="test-v1",
        chosen_calibration=chosen.method,
    )
    p = trained.predict_proba(val_frame)
    # Per-action: every action appears.
    actions_seen = set(val_frame["action_id"].unique().tolist())
    assert actions_seen == set(datasets.recovery_actions["action_id"].tolist())
    # And we got one prediction per row.
    assert len(p) == len(val_frame)


# ---------------------------------------------------------------------------
# 3. Deterministic under a fixed seed
# ---------------------------------------------------------------------------
def test_deterministic_predictions(fitted):
    pp, model, chosen, _train_frame, val_frame, *_ = fitted
    trained1 = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="test-v1",
        chosen_calibration=chosen.method,
    )
    trained2 = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="test-v1",
        chosen_calibration=chosen.method,
    )
    p1 = trained1.predict_proba(val_frame)
    p2 = trained2.predict_proba(val_frame)
    np.testing.assert_array_equal(p1, p2)


# ---------------------------------------------------------------------------
# 4. Calibration: chosen method has Brier <= raw on val
# ---------------------------------------------------------------------------
def test_calibration_does_not_harm_brier(fitted):
    _, model, chosen, _, _, _, X_val, _, y_val = fitted
    p_raw = model.predict_proba(X_val)[:, 1]
    p_cal = predict_with_calibrator(chosen.calibrator, p_raw, chosen.method)
    brier_raw = float(np.mean((p_raw - y_val) ** 2))
    brier_cal = float(np.mean((p_cal - y_val) ** 2))
    # The chosen calibrator is the best-of-three on val, so it should not
    # be worse than the raw probabilities.
    assert brier_cal <= brier_raw + 1e-9


# ---------------------------------------------------------------------------
# 5. Model artifact can be saved + reloaded
# ---------------------------------------------------------------------------
def test_model_save_reload(fitted, tmp_path):
    from ml.versioning import artifact_paths

    pp, model, chosen, _train_frame, val_frame, *_ = fitted
    trained = TrainedLogisticModel(
        model=model,
        preprocessor=pp,
        calibrator=chosen.calibrator,
        model_identifier="rpa-recovery-logreg-test-v1",
        chosen_calibration=chosen.method,
    )
    paths = artifact_paths("rpa-recovery-logreg-test-v1", base_dir=tmp_path)
    trained.save(paths)

    loaded = TrainedLogisticModel.load(paths["model_dir"])
    p1 = trained.predict_proba(val_frame)
    p2 = loaded.predict_proba(val_frame)
    np.testing.assert_allclose(p1, p2, atol=1e-9)


# ---------------------------------------------------------------------------
# 6. Calibration helpers smoke test
# ---------------------------------------------------------------------------
def test_calibration_helpers(fitted):
    _, model, _, _, _, _, X_val, _, y_val = fitted
    sig = fit_sigmoid_calibrator(model, X_val, y_val)
    iso = fit_isotonic_calibrator(model, X_val, y_val)
    p_raw = model.predict_proba(X_val)[:, 1]
    p_sig = predict_with_calibrator(sig, p_raw, "sigmoid")
    p_iso = predict_with_calibrator(iso, p_raw, "isotonic")
    assert (p_sig >= 0).all() and (p_sig <= 1).all()
    assert (p_iso >= 0).all() and (p_iso <= 1).all()
