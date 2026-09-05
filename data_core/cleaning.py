"""Data cleaning pipeline for the RPA data foundation.

The cleaner runs **before** validation and **before** database insertion. It
operates on per-entity pandas DataFrames and applies explicit, documented
policies. Nothing that looks suspicious is silently "fixed" -- every
transformation is recorded in the :class:`CleaningReport` so reviewers can audit
exactly what changed.

Per-field policy vocabulary
---------------------------
Every field is classified as exactly one of:

* **required**  -- missing/invalid -> the record is rejected.
* **optional**  -- missing is allowed and preserved as null.
* **imputed**   -- missing is filled with a configured default (recorded).

Detected issues (all recorded, not silently dropped):
* missing values          -> per-field policy (reject / keep / impute)
* duplicate primary keys   -> keep first, reject the rest
* invalid categoricals    -> reject (required) or null (optional)
* out-of-range numerics    -> reject (required) or null (optional)
* date/temporal anomalies  -> impute ``days_overdue`` from dates (documented) or
                               reject genuinely impossible orderings
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .config import ValidationThresholds as VT
from .config import (
    AMOUNT_MAX,
    AMOUNT_MIN,
    BANKS_LIST,
    CURRENCIES,
    CUSTOMER_LTV_MAX,
    CUSTOMER_LTV_MIN,
    CUSTOMER_SEGMENTS,
    CUSTOMER_TENURE_MAX_DAYS,
    FAILURE_REASONS_LIST,
    PAYMENT_METHODS_LIST,
    RECOVERY_STATUSES,
    TRANSACTION_STATUSES,
    DEFAULT_REFERENCE_DATE,
)
from config import Action, Resource

_MISSING = object()


@dataclass
class FieldPolicy:
    """Policy for a single column within an entity table."""

    name: str
    required: bool = False
    optional: bool = False
    impute_value: Any = _MISSING
    dtype: str = "object"  # object | int | float | bool | datetime
    allowed_values: Optional[Sequence[str]] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None


def _category(values: Sequence[str]) -> List[str]:
    return [v for v in values if v is not None]


# ---------------------------------------------------------------------------
# Field-policy registry (one entry per entity table, keyed by table name)
# ---------------------------------------------------------------------------
def _policies() -> Dict[str, List[FieldPolicy]]:
    action_values = _category([a.value for a in Action])
    resource_types = _category([r.value for r in Resource])
    return {
        "customers": [
            FieldPolicy("customer_id", required=True, dtype="object"),
            FieldPolicy("customer_segment", required=True, allowed_values=CUSTOMER_SEGMENTS, dtype="object"),
            FieldPolicy("customer_ltv", required=True, min_val=CUSTOMER_LTV_MIN, max_val=CUSTOMER_LTV_MAX, dtype="float"),
            FieldPolicy("historical_success_rate", required=True, min_val=VT.RATE_MIN, max_val=VT.RATE_MAX, dtype="float"),
            FieldPolicy("historical_recovery_rate", required=True, min_val=VT.RATE_MIN, max_val=VT.RATE_MAX, dtype="float"),
            FieldPolicy("customer_behavior_score", required=True, dtype="float"),
            FieldPolicy("customer_tenure_days", required=True, min_val=VT.TENURE_MIN, max_val=CUSTOMER_TENURE_MAX_DAYS, dtype="int"),
            FieldPolicy("created_at", required=True, dtype="datetime"),
            FieldPolicy("updated_at", required=True, dtype="datetime"),
        ],
        "transactions": [
            FieldPolicy("transaction_id", required=True, dtype="object"),
            FieldPolicy("customer_id", required=True, dtype="object"),
            FieldPolicy("amount", required=True, min_val=AMOUNT_MIN, max_val=AMOUNT_MAX, dtype="float"),
            FieldPolicy("currency", required=True, allowed_values=CURRENCIES, dtype="object"),
            FieldPolicy("payment_method", required=True, allowed_values=PAYMENT_METHODS_LIST, dtype="object"),
            FieldPolicy("bank", required=True, allowed_values=BANKS_LIST, dtype="object"),
            FieldPolicy("failure_reason", required=True, allowed_values=FAILURE_REASONS_LIST, dtype="object"),
            FieldPolicy("transaction_status", required=True, allowed_values=TRANSACTION_STATUSES, dtype="object"),
            FieldPolicy("retry_count", required=True, min_val=VT.RETRY_MIN, max_val=VT.RETRY_MAX, dtype="int"),
            FieldPolicy("days_overdue", required=True, min_val=VT.DAYS_OVERDUE_MIN, max_val=VT.DAYS_OVERDUE_MAX, dtype="int"),
            FieldPolicy("due_date", required=True, dtype="datetime"),
            FieldPolicy("transaction_timestamp", required=True, dtype="datetime"),
            FieldPolicy("created_at", required=True, dtype="datetime"),
            FieldPolicy("updated_at", required=True, dtype="datetime"),
        ],
        "recovery_actions": [
            FieldPolicy("action_id", required=True, dtype="object"),
            FieldPolicy("action_type", required=True, allowed_values=action_values, dtype="object"),
            FieldPolicy("description", optional=True, dtype="object"),
            FieldPolicy("action_cost", required=True, min_val=0.0, dtype="float"),
            FieldPolicy("resource_requirements", optional=True, dtype="object"),
            FieldPolicy("enabled", required=True, dtype="bool"),
        ],
        "action_outcomes": [
            FieldPolicy("outcome_id", required=True, dtype="object"),
            FieldPolicy("transaction_id", required=True, dtype="object"),
            FieldPolicy("action_id", required=True, dtype="object"),
            FieldPolicy("attempted_at", required=True, dtype="datetime"),
            FieldPolicy("recovery_status", required=True, allowed_values=RECOVERY_STATUSES, dtype="object"),
            FieldPolicy("recovered_amount", required=True, min_val=VT.RECOVERED_MIN, dtype="float"),
            FieldPolicy("outcome_timestamp", required=True, dtype="datetime"),
            FieldPolicy("response_reason", optional=True, dtype="object"),
        ],
        "recovery_predictions": [
            FieldPolicy("prediction_id", required=True, dtype="object"),
            FieldPolicy("transaction_id", required=True, dtype="object"),
            FieldPolicy("action_id", required=True, dtype="object"),
            FieldPolicy("model_identifier", required=True, dtype="object"),
            FieldPolicy("predicted_recovery_probability", required=True, min_val=VT.PROB_MIN, max_val=VT.PROB_MAX, dtype="float"),
            FieldPolicy("prediction_timestamp", required=True, dtype="datetime"),
        ],
        "resource_constraints": [
            FieldPolicy("constraint_id", required=True, dtype="object"),
            FieldPolicy("resource_type", required=True, allowed_values=resource_types, dtype="object"),
            FieldPolicy("limit_value", required=True, min_val=0.0, dtype="float"),
            FieldPolicy("description", optional=True, dtype="object"),
        ],
        "recovery_decisions": [
            FieldPolicy("decision_id", required=True, dtype="object"),
            FieldPolicy("transaction_id", required=True, dtype="object"),
            FieldPolicy("selected_action_id", required=True, dtype="object"),
            FieldPolicy("decision_status", required=True, dtype="object"),
            FieldPolicy("decision_timestamp", required=True, dtype="datetime"),
            FieldPolicy("decision_source", required=True, dtype="object"),
            FieldPolicy("metadata", optional=True, dtype="object"),
        ],
        "audit_logs": [
            FieldPolicy("audit_id", required=True, dtype="object"),
            FieldPolicy("entity_type", required=True, dtype="object"),
            FieldPolicy("entity_id", required=True, dtype="object"),
            FieldPolicy("event_type", required=True, dtype="object"),
            FieldPolicy("event_metadata", optional=True, dtype="object"),
            FieldPolicy("timestamp", required=True, dtype="datetime"),
        ],
    }


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class EntityCleaningResult:
    table: str
    cleaned: pd.DataFrame
    rejected: pd.DataFrame
    duplicate_count: int = 0
    missing_value_counts: Dict[str, int] = field(default_factory=dict)
    invalid_value_counts: Dict[str, int] = field(default_factory=dict)
    transformations: List[Dict[str, Any]] = field(default_factory=list)
    n_raw: int = 0
    n_cleaned: int = 0
    n_rejected: int = 0


@dataclass
class CleaningReport:
    by_entity: Dict[str, EntityCleaningResult] = field(default_factory=dict)

    @property
    def total_raw(self) -> int:
        return sum(r.n_raw for r in self.by_entity.values())

    @property
    def total_cleaned(self) -> int:
        return sum(r.n_cleaned for r in self.by_entity.values())

    @property
    def total_rejected(self) -> int:
        return sum(r.n_rejected for r in self.by_entity.values())

    @property
    def total_duplicates(self) -> int:
        return sum(r.duplicate_count for r in self.by_entity.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_raw": self.total_raw,
            "total_cleaned": self.total_cleaned,
            "total_rejected": self.total_rejected,
            "total_duplicates": self.total_duplicates,
            "by_entity": {
                t: {
                    "raw": r.n_raw,
                    "cleaned": r.n_cleaned,
                    "rejected": r.n_rejected,
                    "duplicates_removed": r.duplicate_count,
                    "missing_value_counts": r.missing_value_counts,
                    "invalid_value_counts": r.invalid_value_counts,
                    "transformations": r.transformations,
                }
                for t, r in self.by_entity.items()
            },
        }


@dataclass
class CleanedDataset:
    frames: Dict[str, pd.DataFrame]
    report: CleaningReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_missing(col: pd.Series, policy: FieldPolicy) -> pd.Series:
    """Mask of missing values (NaN / None / "" / NaT), dtype-aware."""
    if pd.api.types.is_numeric_dtype(col):
        return col.isna()
    s = col
    if s.dtype == object:
        return s.isna() | (s.astype(object) == "")
    return s.isna()


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _coerce_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _apply_policy_column(
    df: pd.DataFrame,
    policy: FieldPolicy,
    missing_counts: Dict[str, int],
    invalid_counts: Dict[str, int],
    transformations: List[Dict[str, Any]],
) -> Tuple[pd.Series, pd.Series]:
    """Return (reject_mask, cleaned_series) aligned to ``df.index``."""
    if policy.name in df.columns:
        col = df[policy.name]
    else:
        col = pd.Series([pd.NA] * len(df), index=df.index)

    missing = _is_missing(col, policy)
    missing_counts[policy.name] = int(missing.sum())
    out = col.copy()
    invalid = pd.Series(False, index=df.index)

    if policy.dtype in ("int", "float"):
        out = _to_numeric(out)
        if policy.min_val is not None:
            invalid = invalid | (out.notna() & (out < policy.min_val))
        if policy.max_val is not None:
            invalid = invalid | (out.notna() & (out > policy.max_val))
        # Non-missing values that failed numeric coercion are invalid.
        coerced_failures = col.notna() & out.isna()
        invalid = invalid | coerced_failures
        if policy.dtype == "int":
            out = out.round()
    elif policy.dtype == "bool":
        mapped = col.astype(str).str.strip().str.lower().map(
            {"true": True, "1": True, "false": False, "0": False}
        )
        invalid = col.notna() & mapped.isna()
        out = mapped
    elif policy.dtype == "datetime":
        out = _coerce_datetime(col)
        invalid = col.notna() & out.isna()
    elif policy.allowed_values:
        allowed = set(policy.allowed_values)
        invalid = col.notna() & ~col.astype(object).isin(allowed)

    invalid_counts[policy.name] = int(invalid.sum())
    bad = missing | invalid

    if policy.required:
        reject = bad
    else:
        reject = pd.Series(False, index=df.index)
        out = out.where(~bad, other=pd.NA)

    if policy.impute_value is not _MISSING and missing.any():
        imputed = missing & out.isna()
        if int(imputed.sum()) > 0:
            transformations.append(
                {
                    "field": policy.name,
                    "rule": f"imputed_missing->{policy.impute_value!r}",
                    "count": int(imputed.sum()),
                }
            )
        out = out.where(~imputed, other=policy.impute_value)

    return reject, out


# ---------------------------------------------------------------------------
# Cleaning implementation
# ---------------------------------------------------------------------------
class CleaningPipeline:
    """Deterministic cleaner: raw frames -> cleaned frames + a report.

    ``reference_date`` is used only to keep ``days_overdue`` internally
    consistent (a documented imputation) and never to tune outcomes.
    """

    PK_BY_TABLE = {
        "customers": "customer_id",
        "transactions": "transaction_id",
        "recovery_actions": "action_id",
        "action_outcomes": "outcome_id",
        "recovery_predictions": "prediction_id",
        "resource_constraints": "constraint_id",
        "recovery_decisions": "decision_id",
        "audit_logs": "audit_id",
    }

    def __init__(self, reference_date: str = DEFAULT_REFERENCE_DATE) -> None:
        self.reference_date = pd.Timestamp(reference_date, tz="UTC")
        self.policies = _policies()

    def _clean_entity(self, table: str, df: pd.DataFrame) -> EntityCleaningResult:
        policies = self.policies[table]
        pk = self.PK_BY_TABLE[table]
        df = df.copy()
        if df.empty and pk not in df.columns:
            df = pd.DataFrame(columns=[p.name for p in policies])

        reject = pd.Series(False, index=df.index)
        missing_counts: Dict[str, int] = {}
        invalid_counts: Dict[str, int] = {}
        transformations: List[Dict[str, Any]] = []
        cleaned_cols: Dict[str, pd.Series] = {}

        # Duplicate primary keys: keep first, reject the rest.
        if pk in df.columns:
            dup_mask = df.duplicated(subset=[pk], keep="first")
            duplicate_count = int(dup_mask.sum())
            reject = reject | dup_mask
        else:
            duplicate_count = 0

        for p in policies:
            col_reject, col_cleaned = _apply_policy_column(
                df, p, missing_counts, invalid_counts, transformations
            )
            reject = reject | col_reject
            cleaned_cols[p.name] = col_cleaned

        cleaned = df.copy()
        for name, series in cleaned_cols.items():
            cleaned[name] = series

        # Days-overdue consistency (documented imputation from dates).
        if (
            table == "transactions"
            and "days_overdue" in cleaned.columns
            and "due_date" in cleaned.columns
        ):
            before = cleaned["days_overdue"]
            derived = (self.reference_date - cleaned["due_date"]).dt.days
            inconsistent = before.notna() & derived.notna() & (before != derived)
            n_inc = int(inconsistent.sum())
            if n_inc:
                cleaned.loc[inconsistent, "days_overdue"] = derived[inconsistent]
                transformations.append(
                    {
                        "field": "days_overdue",
                        "rule": "imputed_from_due_date_and_reference_date",
                        "count": n_inc,
                    }
                )

        # Temporal order: impossible date orderings are rejected.
        #  customers/transactions: updated_at >= created_at
        #  transactions:          transaction_timestamp <= due_date
        if table in ("transactions", "customers") and {
            "updated_at", "created_at"
        }.issubset(cleaned.columns):
            bad_order = (
                cleaned["updated_at"].notna()
                & cleaned["created_at"].notna()
                & (cleaned["updated_at"] < cleaned["created_at"])
            )
            reject = reject | bad_order
        if table == "transactions" and {
            "transaction_timestamp", "due_date"
        }.issubset(cleaned.columns):
            bad_due = (
                cleaned["transaction_timestamp"].notna()
                & cleaned["due_date"].notna()
                & (cleaned["transaction_timestamp"] > cleaned["due_date"])
            )
            reject = reject | bad_due

        kept_mask = ~reject
        kept = cleaned.loc[kept_mask, [p.name for p in policies if p.name in cleaned.columns]].copy()
        rejected = df.loc[reject].copy()

        n_raw = int(len(df))
        n_rejected = int(reject.sum())
        return EntityCleaningResult(
            table=table,
            cleaned=kept.reset_index(drop=True),
            rejected=rejected.reset_index(drop=True),
            duplicate_count=duplicate_count,
            missing_value_counts={k: v for k, v in missing_counts.items() if v},
            invalid_value_counts={k: v for k, v in invalid_counts.items() if v},
            transformations=transformations,
            n_raw=n_raw,
            n_cleaned=n_raw - n_rejected,
            n_rejected=n_rejected,
        )

    def clean(self, frames: Dict[str, pd.DataFrame]) -> CleanedDataset:
        results: Dict[str, EntityCleaningResult] = {}
        cleaned_frames: Dict[str, pd.DataFrame] = {}
        for table, df in frames.items():
            if table not in self.policies:
                continue
            res = self._clean_entity(table, df)
            results[table] = res
            cleaned_frames[table] = res.cleaned
        return CleanedDataset(frames=cleaned_frames, report=CleaningReport(by_entity=results))


__all__ = [
    "FieldPolicy",
    "EntityCleaningResult",
    "CleaningReport",
    "CleanedDataset",
    "CleaningPipeline",
    "policies",
]


def policies() -> Dict[str, List[FieldPolicy]]:
    """Module-level accessor returning the canonical field policy registry."""
    return _policies()
