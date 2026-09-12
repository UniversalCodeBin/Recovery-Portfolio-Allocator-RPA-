from __future__ import annotations

import numpy as np

from config import Action
from data_generation import (
    SyntheticDataGenerator,
    build_demo_pool,
    logit_recovery_probability,
    sample_batch,
    split_dataset,
)


def test_generation_reproducible_same_seed():
    a = SyntheticDataGenerator(99).generate(30, "x")
    b = SyntheticDataGenerator(99).generate(30, "x")
    for ta, tb in zip(a, b):
        assert ta.to_dict() == tb.to_dict()


def test_generation_different_seed_different():
    a = SyntheticDataGenerator(1).generate(30, "x")
    b = SyntheticDataGenerator(2).generate(30, "x")
    assert a[0].to_dict() != b[0].to_dict()


def test_schema_and_ranges():
    txns = SyntheticDataGenerator(5).generate(50, "schema")
    for t in txns:
        assert t.amount >= 0 and t.amount <= 100_000
        assert t.historical_success_rate >= 0.0 and t.historical_success_rate <= 1.0
        assert t.historical_recovery_rate >= 0.0 and t.historical_recovery_rate <= 1.0
        assert t.retry_count >= 0
        assert t.days_overdue >= 0
        assert t.payment_method in {"upi", "credit_card", "debit_card", "net_banking"}
        assert t.bank
        assert t.failure_reason


def test_no_nan():
    txns = SyntheticDataGenerator(5).generate(50, "nan")
    for t in txns:
        for v in t.to_dict().values():
            assert not isinstance(v, float) or not np.isnan(v) or np.isfinite(v)


def test_split_no_leakage():
    pool = SyntheticDataGenerator(5).generate(120, "split")
    tr, va, te = split_dataset(pool, 50, 30, 40, seed=9)
    ids = [t.transaction_id for t in tr + va + te]
    assert len(set(ids)) == 120
    # No id appears twice across the splits.
    assert len(ids) == len(set(ids))


def test_split_deterministic():
    pool = SyntheticDataGenerator(5).generate(120, "split2")
    tr1, _, _ = split_dataset(pool, 50, 30, 40, seed=9)
    tr2, _, _ = split_dataset(pool, 50, 30, 40, seed=9)
    assert [t.transaction_id for t in tr1] == [t.transaction_id for t in tr2]


def test_hidden_probabilities_in_unit_interval_and_action_monotonic():
    txns = SyntheticDataGenerator(4).generate(40, "probs")
    base = logit_recovery_probability(txns, Action.NO_INTERVENTION)
    esc = logit_recovery_probability(txns, Action.HUMAN_ESCALATION)
    inc = logit_recovery_probability(txns, Action.INCENTIVE)
    assert np.all(base >= 0.0) and np.all(base <= 1.0)
    # Human escalation has the highest action effect => should dominate.
    assert np.all(esc >= base)
    assert np.all(inc >= base)
    assert np.all(esc >= inc)


def test_demo_pool_fixed_and_batches_derived():
    p1 = build_demo_pool(42)
    p2 = build_demo_pool(42)
    assert len(p1) > 0
    assert [t.transaction_id for t in p1] == [t.transaction_id for t in p2]
    b1 = sample_batch(p1, 40, 3)
    b2 = sample_batch(p2, 40, 3)
    assert [t.transaction_id for t in b1] == [t.transaction_id for t in b2]
    assert len(b1) == 40


def test_batch_without_replacement():
    pool = build_demo_pool(42)
    b = sample_batch(pool, 50, 11)
    ids = [t.transaction_id for t in b]
    assert len(ids) == len(set(ids))


def test_batch_size_limited_to_pool():
    pool = build_demo_pool(42)
    b = sample_batch(pool, 100_000, 1)
    assert len(b) == len(pool)
