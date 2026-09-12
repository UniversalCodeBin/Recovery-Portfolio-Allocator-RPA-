from __future__ import annotations

import numpy as np

from config import Action
from data_generation import SyntheticDataGenerator
from outcome_simulator import (
    generate_uniform_draws,
    simulate_outcomes,
    simulate_outcomes_from_draws,
)


def test_outcome_reproducible_same_seed():
    gen = SyntheticDataGenerator(50)
    txn = gen.generate(20, "oc")
    acts = [Action.NO_INTERVENTION] * 20
    o1 = simulate_outcomes(txn, acts, batch_seed=7)
    o2 = simulate_outcomes(txn, acts, batch_seed=7)
    assert (o1 == o2).all()


def test_outcome_differs_across_seeds():
    gen = SyntheticDataGenerator(50)
    txn = gen.generate(20, "oc2")
    acts = [Action.INCENTIVE] * 20
    o1 = simulate_outcomes(txn, acts, batch_seed=7)
    o2 = simulate_outcomes(txn, acts, batch_seed=8)
    assert not (o1 == o2).all()


def test_outcomes_binary():
    gen = SyntheticDataGenerator(1)
    txn = gen.generate(30, "binary")
    acts = [Action.RETRY] * 30
    o = simulate_outcomes(txn, acts, batch_seed=3)
    assert set(np.unique(o)) <= {0, 1}


def test_higher_prob_action_recovers_more_in_expectation():
    """Same draws, human escalation should recover >= no-op (expected)."""
    gen = SyntheticDataGenerator(2)
    txn = gen.generate(200, "mono")
    u = generate_uniform_draws(len(txn), batch_seed=4)
    o_noop = simulate_outcomes_from_draws(txn, [Action.NO_INTERVENTION] * len(txn), u)
    o_esc = simulate_outcomes_from_draws(txn, [Action.HUMAN_ESCALATION] * len(txn), u)
    assert o_esc.sum() > o_noop.sum()


def test_shared_draws_identical_realization():
    """Two strategies on identical actions must produce identical outcomes."""
    gen = SyntheticDataGenerator(3)
    txn = gen.generate(50, "shared")
    u = generate_uniform_draws(50, batch_seed=9)
    a1 = [Action.PAYMENT_LINK] * 50
    a2 = [Action.PAYMENT_LINK] * 50
    o1 = simulate_outcomes_from_draws(txn, a1, u)
    o2 = simulate_outcomes_from_draws(txn, a2, u)
    assert (o1 == o2).all()
