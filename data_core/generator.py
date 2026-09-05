"""Reproducible, neutral synthetic-data ingestion source for Step 1.

Generates a *relational* synthetic dataset (customers with multiple transactions,
recovery-action metadata, historical action outcomes) whose field relationships
are realistic rather than independent:

* transaction amounts are lognormal and correlate with customer LTV
* payment methods / failure reasons / banks use realistic weights
* each customer carries consistent historical metrics used across its txns
* ``days_overdue`` is derived from ``due_date`` and the reference date
* dates are internally consistent ( txn -> due -> attempt -> outcome )
* outcomes are realized from a simple, *neutral* logistic baseline -- NOT the
  experiment's hidden ground-truth model, and NOT tuned to favour any allocator

Recovery actions and resource constraints are emitted as *data* (via the
registry) rather than hard-coded strings, so the action vocabulary is
configurable in one place. ``recovery_predictions`` and ``recovery_decisions``
are intentionally left empty: they belong to Step 2 and Step 3 respectively.

The generator is deterministic for a fixed seed (same seed -> same dataset).
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

from config import Action

from .config import (
    AMOUNT_MAX,
    AMOUNT_MIN,
    AMOUNT_LOG_MEAN,
    AMOUNT_LOG_SIGMA,
    BANKS_LIST,
    CURRENCIES,
    CUSTOMER_LTV_MAX,
    CUSTOMER_LTV_MIN,
    CUSTOMER_SEGMENTS,
    CUSTOMER_TENURE_MAX_DAYS,
    CUSTOMER_TENURE_MIN_DAYS,
    DATA_GENERATION_SEED,
    DEFAULT_REFERENCE_DATE,
    DEMO_POOL_SEED,
    FAILURE_REASONS_LIST,
    N_CUSTOMERS,
    OUTCOME_MODEL,
    PAYMENT_METHODS_LIST,
    RECOVERY_STATUSES,
    SPLIT_SEED,
    TRANSACTION_STATUSES,
    TRANSACTION_STATUS_WEIGHTS,
)
from .models import (
    ActionOutcome,
    AuditLog,
    Customer,
    GeneratedDataset,
    RecoveryDecision,
    RecoveryPrediction,
    Transaction,
)
from .registry import build_recovery_actions, default_resource_constraints

# Precomputed neutral base recovery probability per action_type (lookup by value).
OUTCOME_BASE: dict[str, float] = {
    a.value: OUTCOME_MODEL.base_recovery[a] for a in Action
}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-x))


def _sigmoidf(x: float) -> float:
    return float(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x)))))


def _derive_seed(seed: int, key: str, salt: int = 0) -> int:
    digest = hashlib.sha256(f"{seed}:{salt}:{key}".encode()).hexdigest()
    return int(digest[:8], 16)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_date_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Sub-generators
# ---------------------------------------------------------------------------
class SyntheticDataGenerator:
    """Generates a reproducible relational synthetic recovery dataset."""

    def __init__(self, seed: int = DATA_GENERATION_SEED) -> None:
        self.seed = int(seed)

    def _rng(self, key: str, salt: int = 0) -> np.random.Generator:
        return np.random.default_rng(_derive_seed(self.seed, key, salt))

    # -- customers --------------------------------------------------------
    def _generate_customers(self, n: int) -> List[Customer]:
        rng_c = self._rng("customers")
        rng_latent = self._rng("latent")
        # Latent 'bankability': couples success/recovery/behavior/ltv.
        latent = rng_latent.normal(0.0, 1.0, size=n)

        segments = rng_c.choice(
            CUSTOMER_SEGMENTS, size=n,
            p=[0.70, 0.22, 0.08],
        ).tolist()

        # LTV: enterprise > business > retail, coupled with latent.
        seg_mult = np.vectorize({"retail": 1.0, "business": 3.0, "enterprise": 6.0}.get)(
            np.array(segments)
        )
        ltv = (
            CUSTOMER_LTV_MIN
            + (CUSTOMER_LTV_MAX - CUSTOMER_LTV_MIN)
            * _sigmoid(0.9 * latent + 0.35 * np.log(seg_mult))
            + rng_c.normal(0.0, 12_000.0, size=n)
        )
        ltv = np.clip(ltv, CUSTOMER_LTV_MIN, CUSTOMER_LTV_MAX)

        base_success = _sigmoid(2.2 * latent + 0.6 * np.log(seg_mult))
        success = np.clip(
            base_success + (rng_c.beta(2.0, 2.0, size=n) - 0.5) * 0.35,
            0.02, 0.98,
        )

        recovery = np.clip(
            _sigmoid(1.3 * latent + 0.5 * (success - 0.5) + 0.4 * np.log(seg_mult))
            + (rng_c.beta(2.0, 2.0, size=n) - 0.5) * 0.2,
            0.0, 0.95,
        )

        behavior = -latent + rng_c.normal(0.0, 0.7, size=n)
        behavior = np.clip(behavior, -3.0, 3.0)

        tenure = np.clip(
            np.floor(rng_c.integers(30, 365 * 5, size=n)),  # at least 30 days
            CUSTOMER_TENURE_MIN_DAYS, CUSTOMER_TENURE_MAX_DAYS,
        ).astype(int)

        ref = pd.Timestamp(DEFAULT_REFERENCE_DATE, tz="UTC")
        offsets = pd.to_timedelta(rng_c.integers(1, 365 * 5, size=n), unit="D")
        created = (ref - offsets).to_pydatetime()
        # customer updated_at == created (these are static profiles).
        updated = created

        customers: List[Customer] = []
        for i in range(n):
            cid = f"cust_{i:06d}"
            customers.append(
                Customer(
                    customer_id=cid,
                    customer_segment=str(segments[i]),
                    customer_ltv=float(ltv[i]),
                    historical_success_rate=float(success[i]),
                    historical_recovery_rate=float(recovery[i]),
                    customer_behavior_score=float(behavior[i]),
                    customer_tenure_days=int(tenure[i]),
                    created_at=_iso(created[i]),
                    updated_at=_iso(updated[i]),
                )
            )
        return customers

    # -- transactions -----------------------------------------------------
    def _generate_transactions(
        self,
        customers: List[Customer],
        target_total: int,
    ) -> List[Transaction]:
        rng_amt = self._rng("amount")
        rng_pm = self._rng("payment_method")
        rng_bank = self._rng("bank")
        rng_fr = self._rng("failure_reason")
        rng_status = self._rng("status")
        rng_txn = self._rng("txn_count")
        rng_overdue = self._rng("overdue")
        rng_retry = self._rng("retry")
        rng_ts = self._rng("txn_timestamp")

        n_cust = len(customers)
        # Poisson transactions per customer, scaled so the total ~ target_total.
        lam = max(1.0, target_total / max(1, n_cust) - 1.0)
        counts = rng_txn.poisson(lam, size=n_cust)
        # Guarantee every customer has at least one transaction.
        counts = np.where(counts < 1, 1, counts)

        amounts = np.exp(rng_amt.normal(AMOUNT_LOG_MEAN, AMOUNT_LOG_SIGMA, size=int(counts.sum())))
        amounts = np.clip(amounts, AMOUNT_MIN, AMOUNT_MAX)

        pm = np.array(PAYMENT_METHODS_LIST)[rng_pm.integers(0, len(PAYMENT_METHODS_LIST), size=len(amounts))]
        banks = np.array(BANKS_LIST)[rng_bank.integers(0, len(BANKS_LIST), size=len(amounts))]
        # Weighted failure reasons.
        fr_w = np.array([0.30, 0.15, 0.25, 0.10, 0.10, 0.10])
        fr_w = fr_w / fr_w.sum()
        reasons = np.array(FAILURE_REASONS_LIST)[rng_fr.choice(len(FAILURE_REASONS_LIST), size=len(amounts), p=fr_w)]

        statuses = np.array(TRANSACTION_STATUSES)[
            rng_status.choice(len(TRANSACTION_STATUSES), size=len(amounts), p=TRANSACTION_STATUS_WEIGHTS)
        ]

        ref = pd.Timestamp(DEFAULT_REFERENCE_DATE, tz="UTC")

        # Per-transaction risk factor (drives days_overdue + retries) derived
        # from customer history: riskier customers are overdue longer.
        success_arr = np.array([c.historical_success_rate for c in customers])
        behavior_arr = np.array([c.customer_behavior_score for c in customers])
        # Map customer -> per-transaction via counts.
        cust_idx = np.repeat(np.arange(n_cust), counts)
        cust_success = success_arr[cust_idx]
        cust_behavior = behavior_arr[cust_idx]
        risk = np.clip((1.0 - cust_success) + 0.25 * np.clip(cust_behavior, 0, 3), 0, 2.5)
        # days_overdue: exponential base + risk-driven extra days, floored to 0.
        days_overdue_arr = np.clip(
            np.floor(rng_overdue.exponential(2.0, size=len(amounts)) + 12.0 * risk),
            0, 171,
        ).astype(int)

        # Per-transaction transaction_timestamp (before due date, before ref).
        ts_offsets = rng_ts.integers(1, 31, size=len(amounts))  # days before due

        idx = 0
        transactions: List[Transaction] = []
        for ci, cust in enumerate(customers):
            for _ in range(int(counts[ci])):
                tid = f"txn_{idx:07d}"
                amt = float(amounts[idx])
                # Amount weakly correlated with customer LTV (richer pay more).
                ltv_factor = 1.0 + 0.15 * (cust.customer_ltv - 50_000.0) / 950_000.0
                amt = float(min(AMOUNT_MAX, max(AMOUNT_MIN, amt * ltv_factor)))

                # Date consistency: due_date = ref - days_overdue  (<= ref, so
                # days_overdue >= 0); transaction_timestamp = due_date - offset
                # (so txn < due). days_overdue == (ref - due_date).days by construction.
                do_days = int(days_overdue_arr[idx])
                due_date = ref - pd.Timedelta(days=do_days)
                txn_ts = due_date - pd.Timedelta(days=int(ts_offsets[idx]), hours=2)

                # Retry count: riskier customers have more retries.
                retry_mean = 0.8 + 2.5 * (1.0 - cust.historical_success_rate)
                rc = int(min(5, rng_retry.poisson(retry_mean)))
                if rc < 0:
                    rc = 0

                created_t = txn_ts + pd.Timedelta(seconds=15)
                updated_t = created_t

                transactions.append(
                    Transaction(
                        transaction_id=tid,
                        customer_id=cust.customer_id,
                        amount=amt,
                        currency=CURRENCIES[0],
                        payment_method=str(pm[idx]),
                        bank=str(banks[idx]),
                        failure_reason=str(reasons[idx]),
                        transaction_status=str(statuses[idx]),
                        retry_count=rc,
                        days_overdue=do_days,
                        due_date=_iso(due_date.to_pydatetime()),
                        transaction_timestamp=_iso(created_t.to_pydatetime()),
                        created_at=_iso(created_t.to_pydatetime()),
                        updated_at=_iso(updated_t.to_pydatetime()),
                    )
                )
                idx += 1
        return transactions

    # -- action outcomes --------------------------------------------------
    def _generate_action_outcomes(
        self,
        customers: List[Customer],
        transactions: List[Transaction],
    ) -> List[ActionOutcome]:
        """Realize outcomes for a realistic *subset* of transactions.

        Not every failed transaction has a realized outcome row -- in practice
        only transactions that received a historical recovery attempt do. We
        sample a subset and realize a neutral-recovery outcome for each.
        """
        rng = self._rng("outcomes")
        actions = build_recovery_actions()
        cust_by_id = {c.customer_id: c for c in customers}

        outcomes: List[ActionOutcome] = []
        oid = 0
        for txn in transactions:
            cust = cust_by_id[txn.customer_id]
            # ~40% of failed transactions have a historical attempt on record.
            if rng.random() >= 0.4:
                continue
            action = actions[int(rng.integers(0, len(actions)))]
            base = OUTCOME_BASE[action.action_type]
            logit = (
                math.log(base / (1.0 - base))
                + OUTCOME_MODEL.beta_success * (cust.historical_success_rate - 0.5)
                + OUTCOME_MODEL.beta_overdue * (txn.days_overdue / 30.0)
                + OUTCOME_MODEL.beta_ltv * (cust.customer_ltv - 1e5) / 1e5
                + OUTCOME_MODEL.beta_behavior * cust.customer_behavior_score
                + OUTCOME_MODEL.beta_retry * txn.retry_count
            )
            p = _sigmoidf(logit)
            recovered_flag = bool(rng.random() < p)

            if recovered_flag:
                status = "recovered"
                recovered_amount = float(txn.amount * rng.uniform(0.80, 1.00))
                response_reason = None
            elif rng.random() < 0.5:
                status = "partial"
                frac = float(rng.uniform(
                    OUTCOME_MODEL.partial_recovery_low,
                    OUTCOME_MODEL.partial_recovery_high,
                ))
                recovered_amount = float(txn.amount * frac)
                response_reason = "partially_paid"
            else:
                status = "failed"
                recovered_amount = 0.0
                response_reason = str(rng.choice(["bank_declined", "customer_not_responded", "card_invalid"]))

            ts = datetime.fromisoformat(txn.transaction_timestamp)
            # Attempt must fall within [txn_timestamp, reference date]; bound the
            # offset so attempts (and outcomes) never land in the "future".
            ref_ts = _parse_date_ts(DEFAULT_REFERENCE_DATE)
            max_hours = max(1.0, (ref_ts - ts).total_seconds() / 3600.0 - 1.0)
            attempt_hours = float(rng.uniform(1.0, min(24.0, max_hours)))
            attempted_at = _iso(ts + timedelta(hours=attempt_hours))
            outcome_ts = _iso(min(ts + timedelta(hours=attempt_hours + 1.0), ref_ts))
            oid += 1
            outcomes.append(
                ActionOutcome(
                    outcome_id=f"out_{oid:06d}",
                    transaction_id=txn.transaction_id,
                    action_id=action.action_id,
                    attempted_at=attempted_at,
                    recovery_status=status,
                    recovered_amount=recovered_amount,
                    outcome_timestamp=outcome_ts,
                    response_reason=response_reason,
                )
            )
        return outcomes

    # -- audit ------------------------------------------------------------
    def _generate_audit(self) -> List[AuditLog]:
        from .config import AUDIT_TIMESTAMP
        return [
            AuditLog(
                audit_id="aud_000000",
                entity_type="dataset",
                entity_id="synthetic_raw",
                event_type="raw_data_generated",
                event_metadata={"seed": self.seed, "reference_date": DEFAULT_REFERENCE_DATE},
                timestamp=AUDIT_TIMESTAMP,
            )
        ]

    # -- public API -------------------------------------------------------
    def generate(
        self,
        n_customers: int = N_CUSTOMERS,
        target_total: int = 2000,
    ) -> GeneratedDataset:
        """Generate the full relational synthetic dataset (deterministic)."""
        customers = self._generate_customers(n_customers)
        transactions = self._generate_transactions(customers, target_total)
        outcomes = self._generate_action_outcomes(customers, transactions)
        actions = build_recovery_actions()
        constraints = default_resource_constraints()
        return GeneratedDataset(
            customers=customers,
            transactions=transactions,
            recovery_actions=actions,
            resource_constraints=constraints,
            action_outcomes=outcomes,
            recovery_predictions=[],
            recovery_decisions=[],
            audit_logs=self._generate_audit(),
        )
