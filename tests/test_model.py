from __future__ import annotations

import numpy as np
import pytest

from config import PROB_EPS, Action
from data_generation import SyntheticDataGenerator
from model import ActionAwareLogistic


@pytest.fixture()
def model_and_data():
    gen = SyntheticDataGenerator(11)
    tr = gen.generate(150, "mtr")
    va = gen.generate(60, "mval")
    te = gen.generate(60, "mte")
    m = ActionAwareLogistic()
    m.fit(tr, va)
    return m, te


def test_predictions_in_unit_interval(model_and_data):
    m, te = model_and_data
    probs = m.predict_proba(te)
    for p in probs.values():
        assert p.shape == (len(te),)
        assert np.all(p >= PROB_EPS)
        assert np.all(p <= 1.0 - PROB_EPS)


def test_frozen_predictions_identical_calls(model_and_data):
    m, te = model_and_data
    p1 = m.predict_proba(te)
    p2 = m.predict_proba(te)
    for action in p1:
        np.testing.assert_allclose(p1[action], p2[action])


def test_predict_requires_fit():
    m = ActionAwareLogistic()
    with pytest.raises(RuntimeError):
        m.predict_proba([])


def test_model_has_discrimination(model_and_data):
    m, te = model_and_data
    # Human escalation should have higher average predicted prob than no-op.
    probs = m.predict_proba(te)
    assert probs[Action.HUMAN_ESCALATION].mean() > probs[Action.NO_INTERVENTION].mean()
    assert probs[Action.INCENTIVE].mean() > probs[Action.NO_INTERVENTION].mean()


def test_all_actions_served(model_and_data):
    m, te = model_and_data
    probs = m.predict_proba(te)
    assert set(probs.keys()) == set(Action)
