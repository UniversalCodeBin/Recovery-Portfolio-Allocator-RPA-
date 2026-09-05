"""Expected value computation for (transaction, action) pairs.

EV_action(i) = amount_i * P(recovery | i, action) - cost_action

This module depends only on frozen predictions, transaction amounts and
action economics -- it holds no strategy logic.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np

from actions import ResourceVector, action_cost, action_resource_vector
from config import Action, PROB_EPS


def expected_net_recovery(
    amount: float,
    p_recovery: float,
    cost: float,
) -> float:
    """EV = amount * p - cost. Pure function (unit-testable)."""
    p = min(max(p_recovery, 0.0), 1.0)
    return float(amount * p - cost)


def expected_value_matrix(
    amounts: Sequence[float],
    probabilities: Dict[Action, np.ndarray],
    actions: Sequence[Action],
) -> np.ndarray:
    """EV matrix of shape (n_transactions, len(actions)).

    probabilities[action] is an array of length n_transactions.
    The returned matrix's column i (aligned to `actions` order) holds
    EV(action) for each transaction.
    """
    n = len(amounts)
    m = len(actions)
    out = np.zeros((n, m), dtype=float)
    for j, action in enumerate(actions):
        p = np.asarray(probabilities[action], dtype=float)
        p = np.clip(p, PROB_EPS, 1.0 - PROB_EPS)
        cost = action_cost(action)
        out[:, j] = np.asarray(amounts, dtype=float) * p - cost
    return out


def best_action_by_ev(
    amounts: Sequence[float],
    probabilities: Dict[Action, np.ndarray],
    actions: Sequence[Action],
) -> np.ndarray:
    """Indices (into `actions`) of the highest-EV action per transaction."""
    ev = expected_value_matrix(amounts, probabilities, actions)
    return np.argmax(ev, axis=1)


def ev_per_ratio_metric(
    amount: float,
    p_recovery: float,
    cost: float,
    resource: ResourceVector,
    resource_weight: float = 1.0,
) -> float:
    """EV per unit of resource cost, used by the greedy baseline.

    For no-resource actions we fall back to EV (resource magnitude 0).
    """
    ev = amount * p_recovery - cost
    magnitude = max(resource.total_units(), 1e-12)
    return float(ev / (magnitude * resource_weight))


def ev_ratio_matrix(
    amounts: Sequence[float],
    probabilities: Dict[Action, np.ndarray],
    actions: Sequence[Action],
) -> np.ndarray:
    """Matrix of greedy scores (EV / resource-magnitude) per txn-action.

    Actions that consume no resources get score = EV (resource magnitude ~ 1).
    """
    n = len(amounts)
    m = len(actions)
    out = np.zeros((n, m), dtype=float)
    amounts_arr = np.asarray(amounts, dtype=float)
    for j, action in enumerate(actions):
        p = np.clip(np.asarray(probabilities[action], dtype=float), PROB_EPS, 1.0 - PROB_EPS)
        cost = action_cost(action)
        ev = amounts_arr * p - cost
        rv = action_resource_vector(action)
        magnitude = rv.total_units()
        scale = magnitude if magnitude > 0 else 1.0
        out[:, j] = ev / scale
    return out