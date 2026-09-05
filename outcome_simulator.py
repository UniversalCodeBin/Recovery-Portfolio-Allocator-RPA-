"""Stochastic outcome realization.

After a strategy commits to an action per transaction, this module draws the
actual recovery outcome using the HIDDEN ground-truth probability conditional
on the committed action. Crucially, the SAME random seed is used for all
strategies on a given batch so that the comparison is fair (identical random
outcome realization where logically possible).
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Sequence, Tuple

import numpy as np

from config import GROUND_TRUTH
from data_generation import Transaction, logit_recovery_probability
from strategies import StrategyAllocation
from config import Action


def _derive_seed(batch_seed: int, tag: str) -> int:
    digest = hashlib.sha256(f"{batch_seed}:{tag}".encode()).hexdigest()
    return int(digest[:16], 16)


def simulate_outcomes(
    transactions: Sequence[Transaction],
    actions: Sequence[Action],
    batch_seed: int,
    tag: str = "core",
) -> np.ndarray:
    """Draw actual boolean recovery outcomes (0/1) per transaction.

    Uses hidden ground-truth probabilities conditional on the committed
    action. Seed is derived deterministically from (batch_seed, tag) so
    all strategies see the SAME outcome realization for a given batch.

    Fairness: the underlying uniform draw u ~ U(0,1) is generated ONCE per
    batch (per tag); every strategy then uses the SAME u_i vector against its
    own action-conditioned probabilities. This is the identical-random-
    realization guarantee.
    """
    probs = np.array([float(logit_recovery_probability([t], a)[0])
                      for t, a in zip(transactions, actions)])
    rng = np.random.default_rng(_derive_seed(batch_seed, tag))
    u = rng.random(len(transactions))
    return (u < probs).astype(int)


def generate_uniform_draws(
    n: int,
    batch_seed: int,
    tag: str = "core",
) -> np.ndarray:
    """Shared uniform draws for a batch. All strategies use these exact draws."""
    rng = np.random.default_rng(_derive_seed(batch_seed, tag))
    return rng.random(n)


def simulate_outcomes_from_draws(
    transactions: Sequence[Transaction],
    actions: Sequence[Action],
    uniform_draws: np.ndarray,
) -> np.ndarray:
    """Outcome from pre-generated shared uniform draws (identical realization)."""
    probs = np.array([float(logit_recovery_probability([t], a)[0])
                      for t, a in zip(transactions, actions)])
    return (uniform_draws < probs).astype(int)


def simulate_strategy_outcomes(
    strategies: Dict[str, StrategyAllocation],
    transactions: Sequence[Transaction],
    batch_seed: int,
) -> Dict[str, np.ndarray]:
    """Simulate outcomes for multiple strategies with a shared seed (fair).

    All strategies share the SAME uniform outcome realization u ~ U(0,1)^n.
    """
    u = generate_uniform_draws(len(transactions), batch_seed)
    outcomes: Dict[str, np.ndarray] = {}
    for name, allocation in strategies.items():
        outcomes[name] = simulate_outcomes_from_draws(
            transactions, allocation.actions, u
        )
    return outcomes