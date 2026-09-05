from __future__ import annotations

import numpy as np
import pytest

from config import Action
from expected_value import (
    best_action_by_ev,
    ev_ratio_matrix,
    expected_net_recovery,
    expected_value_matrix,
)
from actions import ResourceVector


def test_expected_net_recovery_basic():
    # amount * p - cost
    assert expected_net_recovery(1000.0, 0.5, 10.0) == pytest.approx(490.0)
    assert expected_net_recovery(0.0, 0.5, 10.0) == pytest.approx(-10.0)


def test_expected_net_recovery_clamps_p():
    assert expected_net_recovery(1000.0, 1.5, 0.0) == pytest.approx(1000.0)
    assert expected_net_recovery(1000.0, -0.2, 0.0) == pytest.approx(0.0)


def test_ev_matrix_shape_and_values():
    amounts = [1000.0, 2000.0]
    actions = [Action.NO_INTERVENTION, Action.INCENTIVE]
    prob = {
        Action.NO_INTERVENTION: np.array([0.1, 0.1]),
        Action.INCENTIVE: np.array([0.8, 0.8]),
    }
    ev = expected_value_matrix(amounts, prob, actions)
    assert ev.shape == (2, 2)
    # EV of no intervention = amount*0.1 - 0
    assert ev[0, 0] == pytest.approx(100.0)
    # EV of incentive = amount*0.8 - 25
    assert ev[0, 1] == pytest.approx(800.0 - 25.0)


def test_best_action_by_ev():
    amounts = [1000.0, 2000.0, 3000.0]
    actions = [Action.NO_INTERVENTION, Action.RETRY, Action.HUMAN_ESCALATION]
    prob = {
        Action.NO_INTERVENTION: np.array([0.1, 0.1, 0.1]),
        Action.RETRY: np.array([0.15, 0.6, 0.7]),
        Action.HUMAN_ESCALATION: np.array([0.5, 0.7, 0.2]),
    }
    idx = best_action_by_ev(amounts, prob, actions)
    assert idx[2] == 1  # retry best for third txn


def test_ev_ratio_matrix_no_resource_actions_use_ev():
    amounts = [1000.0]
    actions = [Action.NO_INTERVENTION, Action.RETRY]
    prob = {
        Action.NO_INTERVENTION: np.array([0.1]),
        Action.RETRY: np.array([0.2]),
    }
    m = ev_ratio_matrix(amounts, prob, actions)
    assert m.shape == (1, 2)
    # No-op ratio equals EV (magnitude scaled to 1)
    assert m[0, 0] == pytest.approx(1000 * 0.1)


def test_deterministic_matrices():
    amounts = [100.0, 200.0, 300.0]
    actions = [Action.NO_INTERVENTION, Action.CUSTOMER_MESSAGE]
    prob = {
        a: np.random.default_rng(0).random(3) for a in actions
    }
    m1 = expected_value_matrix(amounts, prob, actions)
    m2 = expected_value_matrix(amounts, prob, actions)
    np.testing.assert_allclose(m1, m2)