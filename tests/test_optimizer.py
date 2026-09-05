from __future__ import annotations

import numpy as np
import pytest

from config import Action
from optimizer import brute_force_solve, solve_ilp

ACT = [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
       Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION]


def _ev(amounts: np.ndarray, action: Action) -> np.ndarray:
    """Hand-made EV per action for tests."""
    p = {
        Action.NO_INTERVENTION: 0.05,
        Action.RETRY: 0.12,
        Action.PAYMENT_LINK: 0.18,
        Action.CUSTOMER_MESSAGE: 0.15,
        Action.INCENTIVE: 0.35,
        Action.HUMAN_ESCALATION: 0.5,
    }
    cost = {
        Action.NO_INTERVENTION: 0.0,
        Action.RETRY: 1.0,
        Action.PAYMENT_LINK: 2.0,
        Action.CUSTOMER_MESSAGE: 0.5,
        Action.INCENTIVE: 25.0,
        Action.HUMAN_ESCALATION: 40.0,
    }
    return amounts * p[action] - cost[action]


def build_ev_matrix(n: int, rng: np.random.Generator) -> np.ndarray:
    amounts = rng.uniform(1000, 9000, size=n)
    return np.column_stack([_ev(amounts, a) for a in ACT])


def test_solve_feasible_and_optimal_no_capacity():
    rng = np.random.default_rng(0)
    ev = build_ev_matrix(5, rng)
    res = solve_ilp(ev, ACT, {"retry": None, "messaging": None,
                              "incentive": None, "human": None})
    assert res.optimal
    assert set(np.unique(res.assignment)) <= set(range(len(ACT)))
    # Objective equals brute force.
    obj_bf, assign_bf = brute_force_solve(ev, ACT, {"retry": None, "messaging": None,
                                                    "incentive": None, "human": None})
    assert res.objective == pytest.approx(obj_bf, abs=1e-6)


def test_one_action_per_transaction():
    rng = np.random.default_rng(1)
    ev = build_ev_matrix(7, rng)
    res = solve_ilp(ev, ACT, {"retry": None, "messaging": None,
                              "incentive": None, "human": None})
    assert len(res.assignment) == 7


def test_incentive_budget_respected():
    rng = np.random.default_rng(2)
    ev = build_ev_matrix(6, rng)
    cap = {"retry": None, "messaging": None, "incentive": 50.0, "human": None}
    res = solve_ilp(ev, ACT, cap)
    assert res.resources_used["incentive"] <= 50.0 + 1e-9
    assert res.resources_used["incentive"] in (0.0, 50.0)


def test_human_slots_respected():
    rng = np.random.default_rng(3)
    ev = build_ev_matrix(6, rng)
    cap = {"retry": None, "messaging": None, "incentive": None, "human": 2.0}
    res = solve_ilp(ev, ACT, cap)
    assert res.resources_used["human"] <= 2.0 + 1e-9


def test_matches_brute_force_under_multi_constraints():
    rng = np.random.default_rng(4)
    ev = build_ev_matrix(5, rng)
    cap = {"retry": None, "messaging": 3.0, "incentive": 100.0, "human": 1.0}
    res = solve_ilp(ev, ACT, cap)
    obj_bf, _ = brute_force_solve(ev, ACT, cap)
    assert res.optimal
    assert res.objective == pytest.approx(obj_bf, abs=1e-6)


def test_zero_capacity_prevents_resource_actions():
    rng = np.random.default_rng(5)
    ev = build_ev_matrix(4, rng)
    cap = {"retry": None, "messaging": 0.0, "incentive": 0.0, "human": 0.0}
    res = solve_ilp(ev, ACT, cap)
    assert res.resources_used["incentive"] == 0.0
    assert res.resources_used["human"] == 0.0
    assert res.resources_used["messaging"] == 0.0


def test_retry_capacity_respected():
    rng = np.random.default_rng(6)
    ev = build_ev_matrix(5, rng)
    cap = {"retry": 1.0, "messaging": None, "incentive": None, "human": None}
    res = solve_ilp(ev, ACT, cap)
    assert res.resources_used["retry"] <= 1.0 + 1e-9


def test_gaps_reflect_budget_consumption():
    rng = np.random.default_rng(7)
    ev = build_ev_matrix(4, rng)
    cap = {"retry": None, "messaging": None, "incentive": 100.0, "human": None}
    res = solve_ilp(ev, ACT, cap)
    assert res.gaps["incentive"] == pytest.approx(res.resources_used["incentive"] / 100.0)


def test_infeasible_shapes_raise():
    ev = np.zeros((3, 4))
    with pytest.raises(ValueError):
        solve_ilp(ev, ACT, {"retry": None, "messaging": None,
                            "incentive": None, "human": None})


def test_edge_case_no_transactions():
    ev = np.zeros((0, len(ACT)))
    res = solve_ilp(ev, ACT, {"retry": None, "messaging": None,
                              "incentive": None, "human": None})
    assert len(res.assignment) == 0


def test_extreme_single_txn_no_resource():
    """Single transaction, extreme binding should still produce valid output."""
    amounts = np.array([6000.0])
    ev = np.column_stack([_ev(amounts, a) for a in ACT])
    cap = {"retry": 0.0, "messaging": 0.0, "incentive": 0.0, "human": 0.0}
    res = solve_ilp(ev, ACT, cap)
    assert len(res.assignment) == 1
    assert res.resources_used["incentive"] == 0.0
    assert res.resources_used["human"] == 0.0