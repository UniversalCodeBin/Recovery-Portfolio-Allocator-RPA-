"""Synthetic data generation with a hidden ground-truth recovery model.

Creates reproducible transaction datasets whose recovery outcomes follow a
hidden logistic ground-truth model (see config.GroundTruthParams). These
parameters are NEVER exposed to the predictor or the strategies; they are used
only to (a) generate the observed outcome labels for model training and
(b) simulate actual recovery in outcomes at evaluation time.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from config import (
    Action,
    AMOUNT_LOG_MEAN,
    AMOUNT_LOG_SIGMA,
    BANKS,
    FAILURE_REASONS,
    GROUND_TRUTH,
    N_DEMO_POOL,
    PAYMENT_METHODS,
    PerActionConsumption,
    action_consumption,
)


@dataclass
class Transaction:
    """A single transaction to be considered for recovery allocation."""

    transaction_id: int
    amount: float
    payment_method: str
    bank: str
    failure_reason: str
    retry_count: int
    days_overdue: int
    customer_ltv: float
    historical_success_rate: float
    historical_recovery_rate: float
    customer_behavior_score: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _sig_log_income(rng: np.random.Generator, n: int) -> np.ndarray:
    """Logistic-style per-customer 'bankability' latent used to couple features."""
    return rng.normal(0.0, 1.0, size=n)


def _feature_dictionary() -> None:
    pass


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-x))


def logit_recovery_probability(
    transactions: Sequence[Transaction],
    action: Action,
    gt: GroundTruthParams = GROUND_TRUTH,
) -> np.ndarray:
    """Hidden ground-truth P(recovery) for a sequence of transactions.

    This is the function used to generate training targets AND to simulate
    real outcomes. It must be independent of the model/strategy code.
    """
    amount = np.array([t.amount for t in transactions])
    success = np.clip(np.array([t.historical_success_rate for t in transactions]), 1e-3, 0.999)
    overdue = np.array([t.days_overdue for t in transactions]) / 30.0
    ltv = np.array([t.customer_ltv for t in transactions])
    behavior = np.array([t.customer_behavior_score for t in transactions])
    retries = np.array([t.retry_count for t in transactions])

    # Standardize continuous-ish variables to comparable scales.
    log_amount = np.log(np.clip(amount, 1.0, None))

    logit = (
        gt.intercept
        + gt.beta_amount * (log_amount - AMOUNT_LOG_MEAN)
        + gt.beta_success * (success - 0.5)
        + gt.beta_overdue * overdue
        + gt.beta_ltv * (ltv - 1e5) / 1e5
        + gt.beta_behavior * behavior
        + gt.beta_retry_count * retries
        + gt.action_effect[action.value]
    )
    return _sigmoid(logit)


def _draw_categorical(rng: np.random.Generator, n: int, choices: List[str], weights: Optional[np.ndarray] = None) -> List[str]:
    return list(rng.choice(choices, size=n, p=weights))


class SyntheticDataGenerator:
    """Generates reproducible synthetic transaction datasets."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self._rng = np.random.default_rng(seed)

    def _seed_for(self, key: str) -> int:
        """Derive a deterministic integer sub-seed from a string key."""
        digest = hashlib.sha256(f"{self.seed}:{key}".encode()).hexdigest()
        return int(digest[:8], 16)

    def generate(self, n: int, prefix: str = "") -> List[Transaction]:
        """Generate `n` transactions with coupled, realistic features."""
        rng = np.random.default_rng(self._seed_for(prefix))

        # Latent customer 'bankability' couples success-rate, recovery-rate,
        # behavior and (weakly) LTV -- NOT independent draws.
        latent = _sig_log_income(rng, n)

        # Amount: lognormal, right-skewed, correlated weakly with LTV.
        amount = np.exp(rng.normal(AMOUNT_LOG_MEAN, AMOUNT_LOG_SIGMA, size=n))
        amount = np.clip(amount, 100.0, 100_000.0)

        # LTV correlated with latent (wealthier / stickier customers).
        ltv = 50_000 + 80_000 * _sigmoid(0.8 * latent) + rng.normal(0, 15_000, size=n)
        ltv = np.clip(ltv, 5_000, 1_000_000)

        # Historical success rate: high for good latent, beta-distributed noise.
        base_success = _sigmoid(2.0 * latent)
        success = np.clip(
            base_success + (rng.beta(2.0, 2.0, size=n) - 0.5) * 0.35,
            0.02,
            0.98,
        )

        # Historical recovery rate correlated with latent and success.
        recovery = np.clip(
            _sigmoid(1.2 * latent + 0.5 * (success - 0.5)) + (rng.beta(2.0, 2.0, size=n) - 0.5) * 0.2,
            0.0,
            0.95,
        )

        # Customer behavior score: higher = riskier (negatively linked to latent).
        behavior = -latent + rng.normal(0, 0.7, size=n)

        # Days overdue: skew; riskier customers overdue longer.
        days_overdue = np.clip(
            np.floor(rng.exponential(1.5, size=n) * (0.5 + 1.5 * _sigmoid(latent)) + (rng.random(size=n) < 0.2) * 15),
            0,
            120,
        ).astype(int)

        # Retry count: more retries for harder (lower success) customers.
        retry_count = np.clip(
            np.floor((rng.random(size=n) < 0.4) * (1 + rng.geometric(0.5, size=n) - 1)) +
            ((1.0 - success) > 0.4) * 1,
            0,
            4,
        ).astype(int)

        payment_method = _draw_categorical(
            rng, n, PAYMENT_METHODS, weights=np.array([0.45, 0.2, 0.2, 0.15])
        )
        bank = _draw_categorical(rng, n, BANKS)
        failure_reason = _draw_categorical(rng, n, FAILURE_REASONS)

        transactions: List[Transaction] = []
        for i in range(n):
            transactions.append(
                Transaction(
                    transaction_id=i,
                    amount=float(amount[i]),
                    payment_method=payment_method[i],
                    bank=bank[i],
                    failure_reason=failure_reason[i],
                    retry_count=int(retry_count[i]),
                    days_overdue=int(days_overdue[i]),
                    customer_ltv=float(ltv[i]),
                    historical_success_rate=float(success[i]),
                    historical_recovery_rate=float(recovery[i]),
                    customer_behavior_score=float(behavior[i]),
                )
            )
        return transactions


def split_dataset(
    transactions: List[Transaction],
    n_train: int,
    n_val: int,
    n_test: int,
    seed: int = 1,
) -> Tuple[List[Transaction], List[Transaction], List[Transaction]]:
    """Deterministic split into train/val/test with NO overlap (no leakage)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(transactions)).tolist()
    train_idx = idx[:n_train]
    val_idx = idx[n_train : n_train + n_val]
    test_idx = idx[n_train + n_val : n_train + n_val + n_test]
    return (
        [transactions[i] for i in train_idx],
        [transactions[i] for i in val_idx],
        [transactions[i] for i in test_idx],
    )


def build_demo_pool(seed: int, n: int = N_DEMO_POOL) -> List[Transaction]:
    """Fixed held-out demo pool (never used in model training)."""
    gen = SyntheticDataGenerator(seed)
    return gen.generate(n, prefix="demo_pool")


def sample_batch(
    pool: List[Transaction],
    batch_size: int,
    batch_seed: int,
) -> List[Transaction]:
    """Sample a batch (without replacement) from the held-out pool.

    Sampling is deterministic given (pool, batch_seed). The pool is fixed and
    disjoint from training/validation/test, so no leakage.
    """
    pool = sorted(pool, key=lambda t: t.transaction_id)
    rng = np.random.default_rng(batch_seed)
    idx = rng.choice(len(pool), size=min(batch_size, len(pool)), replace=False).tolist()
    return [pool[i] for i in idx]


def resource_demand(transactions: Sequence[Transaction], action: Action) -> PerActionConsumption:
    """Aggregate resource demand if `action` were applied to all transactions (unused base)."""
    cons = action_consumption(action)
    n = len(transactions)
    return PerActionConsumption(
        retry=cons.retry * n,
        messaging=cons.messaging * n,
        incentive=cons.incentive * n,
        human=cons.human * n,
    )


def recoverable_units(
    action: Action, txn: Transaction
) -> PerActionConsumption:
    """Per-transaction + per-action resource consumption (for constraint checks)."""
    return action_consumption(action)

