"""Formal validation layer for the RPA data foundation.

Validation runs **after** cleaning and **before** database insertion of trusted
data. The approach is two-tiered:

1. **Per-record structural validation** with Pydantic v2 models. Pydantic was
   chosen because the data model is row/relational, Pydantic gives strict typing
   with bounded-numeric constraints and enum validation in almost no boilerplate,
   the models double as documentation, and per-record errors are trivial to unit
   test. Cross-record invariants that Pydantic cannot express are handled in the
   second tier.

2. **Cross-record integrity checks** (explicit, testable functions over the
   cleaned DataFrames): referential integrity, temporal integrity, uniqueness and
   the ``recovered_amount <= transaction.amount`` bound.

No model predictions are computed here -- ``predicted_recovery_probability`` is
only range-checked in ``[0, 1]``.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .config import (
    BANKS_LIST,
    CURRENCIES,
    CUSTOMER_SEGMENTS,
    FAILURE_REASONS_LIST,
    PAYMENT_METHODS_LIST,
    RECOVERY_STATUSES,
    RESOURCE_TYPES,
    TRANSACTION_STATUSES,
    Action,
)
from .models import (
    ActionOutcome,
    AuditLog,
    Customer,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPrediction,
    ResourceConstraint,
    Transaction,
)


def _make_enum(name: str, values: List[str]) -> type:
    """Build a str-Enum from a configuration value list (keeps validation in sync)."""
    mapping = {v: v for v in values}
    return enum.Enum(name, mapping)


PaymentMethod = _make_enum("PaymentMethod", PAYMENT_METHODS_LIST)
Bank = _make_enum("Bank", BANKS_LIST)
FailureReason = _make_enum("FailureReason", FAILURE_REASONS_LIST)
TransactionStatus = _make_enum("TransactionStatus", TRANSACTION_STATUSES)
RecoveryStatus = _make_enum("RecoveryStatus", RECOVERY_STATUSES)
Currency = _make_enum("Currency", CURRENCIES)
CustomerSegment = _make_enum("CustomerSegment", CUSTOMER_SEGMENTS)
ResourceType = _make_enum("ResourceType", RESOURCE_TYPES)
ActionType = _make_enum("ActionType", [a.value for a in Action])


class _Base(BaseModel):
    # Lax mode lets Pydantic coerce ISO datetimes / category strings into the
    # typed fields while `extra="forbid"` and the per-field Field(...) bounds
    # enforce the real domain rules. Strict numeric bounds (gt/ge/le) are still
    # applied; only cross-value string->enum coercion is relaxed here.
    model_config = ConfigDict(extra="forbid")


class CustomerModel(_Base):
    customer_id: str = Field(min_length=1)
    customer_segment: CustomerSegment
    customer_ltv: float = Field(ge=0.0)
    historical_success_rate: float = Field(ge=0.0, le=1.0)
    historical_recovery_rate: float = Field(ge=0.0, le=1.0)
    customer_behavior_score: float
    customer_tenure_days: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class TransactionModel(_Base):
    transaction_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    amount: float = Field(gt=0.0)
    currency: Currency
    payment_method: PaymentMethod
    bank: Bank
    failure_reason: FailureReason
    transaction_status: TransactionStatus
    retry_count: int = Field(ge=0)
    days_overdue: int = Field(ge=0)
    due_date: datetime
    transaction_timestamp: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryActionModel(_Base):
    action_id: str = Field(min_length=1)
    action_type: ActionType
    description: Optional[str] = None
    action_cost: float = Field(ge=0.0)
    resource_requirements: Optional[Dict[str, float]] = None
    enabled: bool


class ActionOutcomeModel(_Base):
    outcome_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    attempted_at: datetime
    recovery_status: RecoveryStatus
    recovered_amount: float = Field(ge=0.0)
    outcome_timestamp: datetime
    response_reason: Optional[str] = None


class RecoveryPredictionModel(_Base):
    prediction_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    predicted_recovery_probability: float = Field(ge=0.0, le=1.0)
    prediction_timestamp: datetime


class ResourceConstraintModel(_Base):
    constraint_id: str = Field(min_length=1)
    resource_type: ResourceType
    limit_value: float = Field(ge=0.0)
    description: Optional[str] = None


class RecoveryDecisionModel(_Base):
    decision_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    selected_action_id: str = Field(min_length=1)
    decision_status: str = Field(min_length=1)
    decision_timestamp: datetime
    decision_source: str = Field(min_length=1)
    metadata: Optional[Dict[str, Any]] = None


class AuditLogModel(_Base):
    audit_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime


# Map table -> (pydantic model, primary key column)
MODEL_REGISTRY: Dict[str, tuple[type, str]] = {
    "customers": (CustomerModel, "customer_id"),
    "transactions": (TransactionModel, "transaction_id"),
    "recovery_actions": (RecoveryActionModel, "action_id"),
    "action_outcomes": (ActionOutcomeModel, "outcome_id"),
    "recovery_predictions": (RecoveryPredictionModel, "prediction_id"),
    "resource_constraints": (ResourceConstraintModel, "constraint_id"),
    "recovery_decisions": (RecoveryDecisionModel, "decision_id"),
    "audit_logs": (AuditLogModel, "audit_id"),
}


@dataclass
class ValidationFailure:
    table: str
    row: int
    field: str
    message: str


@dataclass
class ValidationResult:
    accepted: Dict[str, pd.DataFrame] = field(default_factory=dict)
    rejected: Dict[str, pd.DataFrame] = field(default_factory=dict)
    failures: List[ValidationFailure] = field(default_factory=list)
    n_raw: int = 0
    n_accepted: int = 0
    n_rejected: int = 0

    @property
    def valid(self) -> bool:
        return self.n_rejected == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_raw": self.n_raw,
            "total_accepted": self.n_accepted,
            "total_rejected": self.n_rejected,
            "failure_counts_by_table": _failure_counts(self.failures),
            "failures": [
                {"table": f.table, "row": f.row, "field": f.field, "message": f.message}
                for f in self.failures
            ],
        }


def _failure_counts(failures: List[ValidationFailure]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for f in failures:
        counts[f.table] = counts.get(f.table, 0) + 1
    return counts


def _sanitize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize pandas missing sentinels (NA / NaN / NaT) to None.

    Pandas emits ``pd.NA``/``np.nan`` for nullable columns; Pydantic's
    ``Optional[...]`` only accepts ``None`` in lax mode, so we normalize here.
    Dict/list payloads (e.g. ``resource_requirements``) are passed through.
    """
    cleaned: Dict[str, Any] = {}
    for k, v in rec.items():
        if isinstance(v, (dict, list)):
            cleaned[k] = v
        elif v is pd.NaT or v is None:
            cleaned[k] = None
        elif isinstance(v, float) and math.isnan(v):
            cleaned[k] = None
        else:
            try:
                isna = bool(pd.isna(v))
            except (TypeError, ValueError):
                isna = False
            cleaned[k] = None if isna else v
    return cleaned


# ---------------------------------------------------------------------------
# Cross-record integrity checks
# ---------------------------------------------------------------------------
def _check_uniqueness(frame: pd.DataFrame, pk: str, table: str) -> List[ValidationFailure]:
    dup = frame.duplicated(subset=[pk], keep=False)
    failures: List[ValidationFailure] = []
    for idx in frame.index[dup]:
        failures.append(
            ValidationFailure(table, int(idx), pk, "primary key not unique")
        )
    return failures


def _check_temporal(frame: pd.DataFrame, table: str) -> List[ValidationFailure]:
    failures: List[ValidationFailure] = []
    if table in ("transactions", "customers") and {"updated_at", "created_at"}.issubset(frame.columns):
        mask = pd.to_datetime(frame["updated_at"]) < pd.to_datetime(frame["created_at"])
        for idx in frame.index[mask]:
            failures.append(
                ValidationFailure(table, int(idx), "updated_at", "updated_at before created_at")
            )
    if table == "action_outcomes" and {"attempted_at", "outcome_timestamp"}.issubset(frame.columns):
        mask = pd.to_datetime(frame["outcome_timestamp"]) < pd.to_datetime(frame["attempted_at"])
        for idx in frame.index[mask]:
            failures.append(
                ValidationFailure(table, int(idx), "attempted_at", "outcome before attempt")
            )
    if table == "transactions":
        ts = pd.to_datetime(frame["transaction_timestamp"], errors="coerce", utc=True)
        due = pd.to_datetime(frame["due_date"], errors="coerce", utc=True)
        bad = ts.notna() & due.notna() & (ts > due)
        for idx in frame.index[bad]:
            failures.append(
                ValidationFailure(table, int(idx), "transaction_timestamp", "transaction_timestamp after due_date")
            )
    return failures


def _check_temporal_cross_record(frames: Dict[str, pd.DataFrame]) -> List[ValidationFailure]:
    """Cross-record temporal checks requiring a join across entities.

    Currently: an action outcome's ``attempted_at`` must not precede the
    originating transaction's ``transaction_timestamp`` (an outcome cannot
    happen before the payment).
    """
    failures: List[ValidationFailure] = []
    if "action_outcomes" not in frames or "transactions" not in frames:
        return failures
    txn_ts = frames["transactions"].set_index("transaction_id")["transaction_timestamp"]
    ao = frames["action_outcomes"]
    joined = ao.join(txn_ts.rename("txn_timestamp"), on="transaction_id", how="left")
    attempted = pd.to_datetime(joined["attempted_at"], errors="coerce", utc=True)
    txn = pd.to_datetime(joined["txn_timestamp"], errors="coerce", utc=True)
    bad = attempted.notna() & txn.notna() & (attempted < txn)
    for idx in joined.index[bad]:
        failures.append(
            ValidationFailure("action_outcomes", int(idx), "attempted_at", "outcome attempt before transaction")
        )
    return failures

def _check_referential_integrity(frames: Dict[str, pd.DataFrame]) -> List[ValidationFailure]:
    failures: List[ValidationFailure] = []
    # transactions.customer_id -> customers.customer_id
    if "transactions" in frames and "customers" in frames:
        valid_cust = set(frames["customers"]["customer_id"])
        tx = frames["transactions"]
        bad = tx[~tx["customer_id"].isin(valid_cust)]
        for idx in bad.index:
            failures.append(ValidationFailure("transactions", int(idx), "customer_id", "customer does not exist"))
    # action_outcomes.transaction_id -> transactions.transaction_id
    if "action_outcomes" in frames and "transactions" in frames:
        valid_txn = set(frames["transactions"]["transaction_id"])
        valid_act = set(frames["recovery_actions"]["action_id"]) if "recovery_actions" in frames else set()
        ao = frames["action_outcomes"]
        for idx in ao[~ao["transaction_id"].isin(valid_txn)].index:
            failures.append(ValidationFailure("action_outcomes", int(idx), "transaction_id", "transaction does not exist"))
        if valid_act:
            for idx in ao[~ao["action_id"].isin(valid_act)].index:
                failures.append(ValidationFailure("action_outcomes", int(idx), "action_id", "action does not exist"))
    # recovery_predictions.transaction_id / action_id
    if "recovery_predictions" in frames:
        valid_txn = set(frames["transactions"]["transaction_id"]) if "transactions" in frames else set()
        valid_act = set(frames["recovery_actions"]["action_id"]) if "recovery_actions" in frames else set()
        rp = frames["recovery_predictions"]
        if valid_txn:
            for idx in rp[~rp["transaction_id"].isin(valid_txn)].index:
                failures.append(ValidationFailure("recovery_predictions", int(idx), "transaction_id", "transaction does not exist"))
        if valid_act:
            for idx in rp[~rp["action_id"].isin(valid_act)].index:
                failures.append(ValidationFailure("recovery_predictions", int(idx), "action_id", "action does not exist"))
    # recovery_decisions.selected_action_id -> recovery_actions.action_id
    if "recovery_decisions" in frames:
        valid_txn = set(frames["transactions"]["transaction_id"]) if "transactions" in frames else set()
        valid_act = set(frames["recovery_actions"]["action_id"]) if "recovery_actions" in frames else set()
        rd = frames["recovery_decisions"]
        for idx in rd[~rd["selected_action_id"].isin(valid_act)].index:
            failures.append(ValidationFailure("recovery_decisions", int(idx), "selected_action_id", "action does not exist"))
        for idx in rd[~rd["transaction_id"].isin(valid_txn)].index:
            failures.append(ValidationFailure("recovery_decisions", int(idx), "transaction_id", "transaction does not exist"))
    return failures


def _check_recovered_le_amount(frames: Dict[str, pd.DataFrame]) -> List[ValidationFailure]:
    """recovered_amount must not exceed the originating transaction's amount."""
    failures: List[ValidationFailure] = []
    if "action_outcomes" not in frames or "transactions" not in frames:
        return failures
    tx_amounts = frames["transactions"].set_index("transaction_id")["amount"].rename("txn_amount")
    ao = frames["action_outcomes"]
    joined = ao.join(tx_amounts, on="transaction_id", how="left")
    bad = joined[joined["recovered_amount"] > joined["txn_amount"]]
    for idx in bad.index:
        failures.append(
            ValidationFailure("action_outcomes", int(idx), "recovered_amount", "recovered_amount > transaction amount")
        )
    return failures


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def validate(cleaned: Dict[str, pd.DataFrame]) -> ValidationResult:
    """Validate cleaned frames and return accepted/rejected frames + failures."""
    result = ValidationResult()
    result.n_raw = sum(len(v) for v in cleaned.values())
    accepted: Dict[str, pd.DataFrame] = {}
    rejected: Dict[str, pd.DataFrame] = {}

    # Tier 1: per-record structural validation.
    structural_failures_by_row: Dict[str, set] = {}
    for table, frame in cleaned.items():
        if frame.empty:
            accepted[table] = frame
            continue
        model_cls, pk = MODEL_REGISTRY[table]
        before_accept: List[int] = []
        # Capture which rows fail structurally.
        acc_idx: List[int] = []
        failures: List[ValidationFailure] = []
        for i, rec in enumerate(frame.to_dict(orient="records")):
            try:
                model_cls.model_validate(_sanitize_record(rec))
                acc_idx.append(int(frame.index[i]))
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err["loc"])
                    failures.append(
                        ValidationFailure(table, int(frame.index[i]), loc, err["msg"])
                    )
                structural_failures_by_row.setdefault(table, set()).add(int(frame.index[i]))
        accepted[table] = frame.loc[acc_idx]
        rejected[table] = frame.loc[frame.index.difference(frame.loc[acc_idx].index)]
        result.failures.extend(failures)

    # Tier 2: cross-record checks on the structurally-valid subset.
    cross_failures: List[ValidationFailure] = []
    for table, frame in accepted.items():
        if frame.empty:
            continue
        model_cls, pk = MODEL_REGISTRY[table]
        cross_failures.extend(_check_uniqueness(frame, pk, table))
        cross_failures.extend(_check_temporal(frame, table))
    cross_failures.extend(_check_temporal_cross_record(accepted))
    cross_failures.extend(_check_referential_integrity(accepted))
    cross_failures.extend(_check_recovered_le_amount(accepted))

    # Records failing cross-record checks are also moved to rejected.
    cross_fail_rows: Dict[str, set] = {}
    for f in cross_failures:
        cross_fail_rows.setdefault(f.table, set()).add(f.row)

    for table, frame in accepted.items():
        bad_rows = cross_fail_rows.get(table, set())
        if bad_rows:
            mask = frame.index.isin(bad_rows)
            rejected[table] = pd.concat([rejected.get(table, frame.iloc[0:0]), frame[mask]])
            accepted[table] = frame[~mask]

    result.failures.extend(cross_failures)

    for table, frame in accepted.items():
        result.n_accepted += len(frame)
    for table, frame in rejected.items():
        result.n_rejected += len(frame)

    result.accepted = accepted
    result.rejected = rejected
    return result


__all__ = [
    "CustomerModel",
    "TransactionModel",
    "RecoveryActionModel",
    "ActionOutcomeModel",
    "RecoveryPredictionModel",
    "ResourceConstraintModel",
    "RecoveryDecisionModel",
    "AuditLogModel",
    "ValidationFailure",
    "ValidationResult",
    "validate",
]
