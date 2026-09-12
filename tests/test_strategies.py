from __future__ import annotations

import numpy as np
import pytest

from actions import Resource
from config import Action
from data_generation import SyntheticDataGenerator
from strategies import (
    ev_greedy_strategy,
    fixed_rule_strategy,
    no_intervention_strategy,
    rpa_strategy,
    run_all_strategies,
)
from tests.conftest import capacity_for


@pytest.fixture()
def batch():
    gen = SyntheticDataGenerator(21)
    return gen.generate(40, "strat")


@pytest.fixture()
def probs(batch):
    p = {}
    rng = np.random.default_rng(1)
    base = np.clip(rng.beta(2, 6, size=len(batch)), 1e-3, 0.99)
    effects = {
        Action.NO_INTERVENTION: 0.0,
        Action.RETRY: 0.4,
        Action.PAYMENT_LINK: 0.5,
        Action.CUSTOMER_MESSAGE: 0.4,
        Action.INCENTIVE: 0.9,
        Action.HUMAN_ESCALATION: 1.2,
    }
    for a in Action:
        p[a] = np.clip(base + effects[a.value], 1e-3, 0.999)
    return p


def _assert_valid(allocation, capacity):
    assert len(allocation.actions) == len(allocation.expected_values)
    # exactly one action per txn
    assert len(allocation.actions) > 0
    # no capacity violations
    violations = allocation.check_violations()
    assert violations == []
    # resource_used must not exceed capacity
    used = allocation.resource_used
    for res, cap in capacity.items():
        if res == Resource.INCENTIVE_BUDGET:
            assert used["incentive"] <= cap + 1e-6, (allocation.name, used, cap)


def test_no_intervention_assigns_nothing(batch, probs):
    cap = capacity_for(incentive=1e9)
    alloc = no_intervention_strategy(batch, probs, cap)
    assert all(a == Action.NO_INTERVENTION for a in alloc.actions)
    _assert_valid(alloc, cap)


def test_fixed_rule_deterministic(batch, probs):
    cap = capacity_for(incentive=1000.0, human=3, messaging=100)
    a1 = fixed_rule_strategy(batch, probs, cap)
    a2 = fixed_rule_strategy(batch, probs, cap)
    assert a1.actions == a2.actions
    _assert_valid(a1, cap)


def test_greedy_respects_all_capacities(batch, probs):
    cap = capacity_for(incentive=200.0, human=2, messaging=8, retry=20)
    alloc = ev_greedy_strategy(batch, probs, cap)
    assert alloc.resource_used["incentive"] <= 200.0 + 1e-6
    assert alloc.resource_used["human"] <= 2 + 1e-6
    assert alloc.resource_used["messaging"] <= 8 + 1e-6
    assert alloc.resource_used["retry"] <= 20 + 1e-6
    _assert_valid(alloc, cap)


def test_greedy_zero_capacity_means_no_resource_actions(batch, probs):
    cap = capacity_for(incentive=0.0, human=0, messaging=0, retry=0)
    alloc = ev_greedy_strategy(batch, probs, cap)
    assert alloc.resource_used["incentive"] == 0.0
    assert alloc.resource_used["human"] == 0.0
    assert alloc.resource_used["messaging"] == 0.0
    assert alloc.resource_used["retry"] == 0.0


def test_greedy_single_transaction(batch, probs):
    single = batch[:1]
    p = {a: v[:1] for a, v in probs.items()}
    cap = capacity_for(incentive=1e9)
    alloc = ev_greedy_strategy(single, p, cap)
    assert len(alloc.actions) == 1


def test_greedy_large_batch():
    gen = SyntheticDataGenerator(22)
    big = gen.generate(500, "big")
    p = {a: np.clip(np.random.default_rng(0).random(500), 1e-3, 0.99) for a in Action}
    cap = capacity_for(incentive=5000.0, human=30, messaging=300)
    alloc = ev_greedy_strategy(big, p, cap)
    assert len(alloc.actions) == 500
    assert alloc.resource_used["human"] <= 30 + 1e-6
    assert alloc.resource_used["messaging"] <= 300 + 1e-6


def test_rpa_respects_capacities(batch, probs):
    cap = capacity_for(incentive=200.0, human=2, messaging=8)
    alloc = rpa_strategy(batch, probs, cap)
    assert alloc.solve_status == "optimal"
    assert alloc.resource_used["incentive"] <= 200.0 + 1e-6
    assert alloc.resource_used["human"] <= 2 + 1e-6
    assert alloc.resource_used["messaging"] <= 8 + 1e-6
    _assert_valid(alloc, cap)


def test_rpa_one_action_per_txn(batch, probs):
    cap = capacity_for(incentive=1e9)
    alloc = rpa_strategy(batch, probs, cap)
    assert len(alloc.actions) == len(batch)


def test_rpa_ticks_human_and_messaging_binding(batch, probs):
    """With messaging+human scarce, RPA must not exceed either."""
    cap = capacity_for(incentive=1e9, human=3, messaging=6)
    alloc = rpa_strategy(batch, probs, cap)
    assert alloc.resource_used["messaging"] <= 6 + 1e-6


def test_relaxed_rpa_matches_greedy(batch, probs):
    """When no constraints bind, RPA = greedy = unconstrained EV optimum."""
    cap = capacity_for(incentive=1e9, human=1000, messaging=1000, retry=1000)
    g = ev_greedy_strategy(batch, probs, cap)
    r = rpa_strategy(batch, probs, cap)
    assert g.actions == r.actions
    np.testing.assert_allclose(g.expected_values, r.expected_values, atol=1e-6)


def test_all_strategies_same_inputs(batch, probs):
    """run_all_strategies returns exactly 4 and all have identical lengths."""
    cap = capacity_for(incentive=200.0, human=2, messaging=8)
    out = run_all_strategies(batch, probs, cap)
    assert set(out.keys()) == {"no_intervention", "fixed_rule", "ev_greedy", "rpa"}
    for alloc in out.values():
        assert len(alloc.actions) == len(batch)


def test_fixed_rule_documentation_thresholds():
    """Sanity: the rule escalates high-amount, low-success, overdue txns."""
    gen = SyntheticDataGenerator(23)
    batch = [
        gen.generate(1, "a")[0],
    ]
    # force high amount, low success, high overdue
    t = batch[0]
    t.amount = 200_000.0
    t.historical_success_rate = 0.1
    t.days_overdue = 60
    p = {a: np.full(1, 0.5) for a in Action}
    alloc = fixed_rule_strategy(batch, p, capacity_for(incentive=1e9, human=10))
    assert alloc.actions[0] == Action.HUMAN_ESCALATION


def _mutated_batch(batch, amount_val):
    out = []
    for t in batch:
        t2 = t.to_dict()
        t2["amount"] = amount_val
        from data_generation import Transaction

        out.append(Transaction(**t2))
    return out


def test_greedy_rpa_all_high_value():
    """All high-value transactions: expensive actions become worth it."""
    gen = SyntheticDataGenerator(24)
    batch = _mutated_batch(gen.generate(30, "hi"), 90_000.0)
    p = {a: np.clip(np.random.default_rng(0).random(30), 1e-3, 0.9) for a in Action}
    for cap in (
        capacity_for(incentive=5000.0, human=5),
        capacity_for(incentive=1e9, human=100),
    ):
        g = ev_greedy_strategy(batch, p, cap)
        r = rpa_strategy(batch, p, cap)
        assert len(g.actions) == 30 and len(r.actions) == 30
        _assert_valid(g, cap)
        _assert_valid(r, cap)


def test_greedy_rpa_all_low_value():
    """All low-value transactions: aggressive actions rarely worth the cost."""
    gen = SyntheticDataGenerator(25)
    batch = _mutated_batch(gen.generate(30, "lo"), 200.0)
    p = {a: np.clip(np.random.default_rng(0).random(30), 1e-3, 0.9) for a in Action}
    cap = capacity_for(incentive=5000.0, human=5)
    g = ev_greedy_strategy(batch, p, cap)
    r = rpa_strategy(batch, p, cap)
    assert len(g.actions) == 30 and len(r.actions) == 30
    _assert_valid(g, cap)
    _assert_valid(r, cap)
