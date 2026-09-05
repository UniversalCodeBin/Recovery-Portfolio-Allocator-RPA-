"""Canonical data models for the RPA data foundation.

Each dataclass mirrors a row in the normalized PostgreSQL schema (see
``data_core/schema.py`` and ``database/schema/``). These are the *trusted*
record types that flow through the cleaning -> validation -> store pipeline.
All fields are typed and carry an explicit policy documented in
``data_core/config.py``: required, optional or imputed.

Conversions:
* ``to_dict`` / ``from_dict`` round-trip a record to/from a plain dict
  (handy for parquet columns and for pydantic validation).
* ``DataFrame.from_records``-compatible dicts are produced via
  ``table_name()`` class attributes used by the storage helpers.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@dataclass
class Customer:
    customer_id: str
    customer_segment: str
    customer_ltv: float
    historical_success_rate: float
    historical_recovery_rate: float
    customer_behavior_score: float
    customer_tenure_days: int
    created_at: str
    updated_at: str

    TABLE: str = "customers"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
@dataclass
class Transaction:
    transaction_id: str
    customer_id: str
    amount: float
    currency: str
    payment_method: str
    bank: str
    failure_reason: str
    transaction_status: str
    retry_count: int
    days_overdue: int
    due_date: str
    transaction_timestamp: str
    created_at: str
    updated_at: str

    TABLE: str = "transactions"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Recovery actions (configuration data, not hard-coded strings)
# ---------------------------------------------------------------------------
@dataclass
class RecoveryAction:
    action_id: str
    action_type: str
    description: str
    action_cost: float
    resource_requirements: Dict[str, float] = field(default_factory=dict)
    enabled: bool = True

    TABLE: str = "recovery_actions"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Action outcomes (what actually happened after an action was attempted)
# ---------------------------------------------------------------------------
@dataclass
class ActionOutcome:
    outcome_id: str
    transaction_id: str
    action_id: str
    attempted_at: str
    recovery_status: str
    recovered_amount: float
    outcome_timestamp: str
    response_reason: Optional[str] = None

    TABLE: str = "action_outcomes"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Recovery predictions (Step 2 fills this at training time; empty in Step 1)
# ---------------------------------------------------------------------------
@dataclass
class RecoveryPrediction:
    prediction_id: str
    transaction_id: str
    action_id: str
    model_identifier: str
    predicted_recovery_probability: float
    prediction_timestamp: str

    TABLE: str = "recovery_predictions"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Resource constraints (configuration data)
# ---------------------------------------------------------------------------
@dataclass
class ResourceConstraint:
    constraint_id: str
    resource_type: str
    limit_value: float
    description: str = ""

    TABLE: str = "resource_constraints"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Recovery decisions (Step 3 fills this; empty in Step 1)
# ---------------------------------------------------------------------------
@dataclass
class RecoveryDecision:
    decision_id: str
    transaction_id: str
    selected_action_id: str
    decision_status: str
    decision_timestamp: str
    decision_source: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    TABLE: str = "recovery_decisions"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------
@dataclass
class AuditLog:
    audit_id: str
    entity_type: str
    entity_id: str
    event_type: str
    event_metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)

    TABLE: str = "audit_logs"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeneratedDataset:
    """Container holding one full generated raw dataset (all entities)."""

    customers: list[Customer] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    recovery_actions: list[RecoveryAction] = field(default_factory=list)
    resource_constraints: list[ResourceConstraint] = field(default_factory=list)
    action_outcomes: list[ActionOutcome] = field(default_factory=list)
    recovery_predictions: list[RecoveryPrediction] = field(default_factory=list)
    recovery_decisions: list[RecoveryDecision] = field(default_factory=list)
    audit_logs: list[AuditLog] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        return {k: len(v) for k, v in asdict(self).items()}

    def to_frames(self) -> Dict[str, "Any"]:
        import pandas as pd

        return {
            tbl: pd.DataFrame([r.to_dict() for r in rows])
            for tbl, rows in [
                ("customers", self.customers),
                ("transactions", self.transactions),
                ("recovery_actions", self.recovery_actions),
                ("resource_constraints", self.resource_constraints),
                ("action_outcomes", self.action_outcomes),
                ("recovery_predictions", self.recovery_predictions),
                ("recovery_decisions", self.recovery_decisions),
                ("audit_logs", self.audit_logs),
            ]
            if rows
        }


# Re-export id helpers for the generator / tests.
__all__ = [
    "Customer",
    "Transaction",
    "RecoveryAction",
    "ActionOutcome",
    "RecoveryPrediction",
    "ResourceConstraint",
    "RecoveryDecision",
    "AuditLog",
    "GeneratedDataset",
]
