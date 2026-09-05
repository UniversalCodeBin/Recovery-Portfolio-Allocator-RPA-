from __future__ import annotations

import numpy as np
import pytest

from config import Action
from data_generation import SyntheticDataGenerator
from metrics import (
    BatchMetrics,
    aggregate_metrics,
    compute_batch_metrics,
    compare_lift,
)
from strategies import no_intervention_strategy, rpa_strategy, ev_greedy_strategy


@pytest.fixture()
def batch():
    return SyntheticDataGenerator(31).generate(30, "met")


@pytest.fixture()
def probs(batch):
    p = {}
    rng = np.random.default_rng(0)
    base = np.clip(rng.beta(3, 5, size=len(batch)), 1e-3, 0.99)
    for a in Action:
        p[a] = np.clip(base + 0.3, 1e-3, 0.999)
    return p


def make_alloc(batch, probs, strategy="no_intervention"):
    from actions import Resource
    cap = {Resource.INCENTIVE_BUDGET: 1e9, Resource.HUMAN_SLOTS: 1e9,
           Resource.MESSAGING: 1e9, Resource.RETRY: 1e9}
    if strategy == "no_intervention":
        return no_intervention_strategy(batch, probs, cap)
    if strategy == "rpa":
        return rpa_strategy(batch, probs, cap)
    return ev_greedy_strategy(batch, probs, cap)


def test_compute_batch_metrics_basic(batch, probs):
    alloc = make_alloc(batch, probs)
    outcomes = np.ones(len(batch), dtype=int)  # artificial: recover everything
    bm = compute_batch_metrics(batch, alloc, outcomes, 0.0)
    assert isinstance(bm, BatchMetrics)
    assert bm.total_revenue_at_risk == pytest.approx(sum(t.amount for t in batch))
    assert bm.actual_recovered == pytest.approx(sum(t.amount for t in batch))
    assert bm.recovery_rate == pytest.approx(1.0)
    assert bm.net_recovered == bm.actual_recovered  # no cost for no-op
    assert bm.n_violations == 0


def test_recovery_lift_percent(batch, probs):
    alloc = make_alloc(batch, probs)
    outcomes = np.ones(len(batch), dtype=int)
    no_op = sum(t.amount for t in batch)
    bm = compute_batch_metrics(batch, alloc, outcomes, no_op)
    assert bm.recovery_lift_percent == pytest.approx(0.0)


def test_zero_outcome_actuals(batch, probs):
    alloc = make_alloc(batch, probs, "rpa")
    outcomes = np.zeros(len(batch), dtype=int)
    bm = compute_batch_metrics(batch, alloc, outcomes, 1.0)
    assert bm.actual_recovered == 0.0
    assert bm.cost_per_recovered_rupee == -1.0


def test_transaction_counts(batch, probs):
    alloc = make_alloc(batch, probs, "rpa")
    outcomes = np.random.default_rng(0).integers(0, 2, len(batch))
    bm = compute_batch_metrics(batch, alloc, outcomes, 1.0)
    total = sum(bm.transaction_counts.values())
    assert total == len(batch)


def _mk(strategy, actual, net, rate=0.0):
    return BatchMetrics(
        strategy=strategy,
        total_revenue_at_risk=1000,
        expected_recovered=500,
        actual_recovered=actual,
        recovery_rate=rate,
        net_recovered=net,
        total_action_cost=50,
        recovery_lift_percent=10.0,
        cost_per_recovered_rupee=0.2,
        incentive_utilization=0.0,
        messaging_utilization=0.0,
        human_utilization=0.0,
        retry_utilization=0.0,
        transaction_counts={"no_intervention": 1},
        n_violations=0,
    )


def test_aggregate_metrics_stats():
    bms = [_mk("s", 400, 350), _mk("s", 600, 550)]
    agg = aggregate_metrics(bms)
    assert agg.n_runs == 2
    assert agg.actual_recovered["mean"] == pytest.approx(500.0)
    assert agg.actual_recovered["min"] == pytest.approx(400.0)
    assert agg.actual_recovered["max"] == pytest.approx(600.0)


def test_compare_lift_wins_losses():
    rpa = [_mk("rpa", 600, 500), _mk("rpa", 600, 500)]
    g = [_mk("g", 300, 250), _mk("g", 300, 250)]
    lift = compare_lift(rpa, g)
    assert lift["wins"] == 2
    assert lift["losses"] == 0
    assert lift["lift_mean"] == pytest.approx(100.0)  # (600-300)/300


def test_compare_lift_paired_mismatch_raises():
    with pytest.raises(ValueError):
        compare_lift([_mk("rpa", 600, 500)], [])