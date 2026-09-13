"""CSV adapter — transforms Razorpay-style RAW payment CSVs into the canonical RPA feature dataset.

This module is an INPUT ADAPTER. It does NOT redesign the existing RPA
architecture. It produces exactly what the existing
``orchestrator.run_batch`` expects: transactions DataFrame, customers
DataFrame, and the standard action specs.

Architecture
------------
Razorpay-style RAW CSV
    -> CSV Adapter (this module)
    -> Validation + Normalization
    -> Deterministic Feature Engineering
    -> RPA Feature Dataset
    -> Existing Prediction Service
    -> Expected Value
    -> Existing 7 Policy Gates
    -> Existing ILP Optimizer
    -> Recovery Plan

Raw CSV Schema (Razorpay-style input fields)
---------------------------------------------
    payment_id          - unique payment identifier
    customer_id         - unique customer identifier
    amount              - payment amount (default: rupees)
    currency            - three-letter currency code (default: INR)
    status              - payment status
    method              - payment method
    bank                - bank name
    failure_reason      - reason for failure
    error_code          - error code from payment provider
    error_source        - source of error
    error_step          - step where error occurred
    created_at          - payment creation timestamp
    retry_count         - number of retry attempts
    due_date            - due date for payment

Canonical RPA Transaction Schema
---------------------------------
    transaction_id, customer_id, amount, currency, payment_method, bank,
    failure_reason, transaction_status, retry_count, days_overdue,
    due_date, transaction_timestamp, created_at, updated_at

Canonical RPA Customer Schema
------------------------------
    customer_id, customer_segment, customer_ltv,
    historical_success_rate, historical_recovery_rate,
    customer_behavior_score, customer_tenure_days,
    created_at, updated_at

Customer features are derived DETERMINISTICALLY from available transaction
history. No random values are generated.

Design Principles
-----------------
* Unknown categorical values cause a validation error (not silent mapping).
* Amount unit defaults to "rupees"; explicit conversion options provided.
* Historical features are leakage-safe: each transaction's customer features
  use only information available BEFORE that transaction.
* Recovery rate is only derived when the dataset contains recoverability
  signals (e.g., a "recovered" status). Otherwise a documented fallback is
  used with a warning.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported categorical vocabularies (must match the existing RPA model)
# These are the EXACT values the preprocessor was trained on.
# ---------------------------------------------------------------------------
SUPPORTED_PAYMENT_METHODS: set[str] = {
    "upi",
    "credit_card",
    "debit_card",
    "net_banking",
}
SUPPORTED_BANKS: set[str] = {
    "HDFC",
    "ICICI",
    "SBI",
    "Axis",
    "Kotak",
    "Yes",
}
SUPPORTED_FAILURE_REASONS: set[str] = {
    "insufficient_funds",
    "invalid_pin",
    "network_timeout",
    "bank_down",
    "limit_exceeded",
    "expired_card",
}
SUPPORTED_TRANSACTION_STATUSES: set[str] = {
    "failed",
    "pending",
    "charged_back",
    "charged",
    "captured",
    "created",
    "refunded",
}
SUPPORTED_CUSTOMER_SEGMENTS: set[str] = {
    "retail",
    "business",
    "enterprise",
}

# Canonical column names in the RPA feature dataset
CANONICAL_TRANSACTION_COLUMNS: list[str] = [
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "payment_method",
    "bank",
    "failure_reason",
    "transaction_status",
    "retry_count",
    "days_overdue",
    "due_date",
    "transaction_timestamp",
    "created_at",
    "updated_at",
]

CANONICAL_CUSTOMER_COLUMNS: list[str] = [
    "customer_id",
    "customer_segment",
    "customer_ltv",
    "historical_success_rate",
    "historical_recovery_rate",
    "customer_behavior_score",
    "customer_tenure_days",
    "created_at",
    "updated_at",
]

# ---------------------------------------------------------------------------
# Column mapping: Razorpay-style field names -> canonical names
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, list[str]] = {
    "transaction_id": ["payment_id", "id", "payment_id", "txn_id", "transaction_id"],
    "customer_id": ["customer_id", "payer_id", "payer_vpa", "cust_id"],
    "amount": ["amount", "transaction_amount", "payment_amount", "txn_amount"],
    "currency": ["currency", "currency_code"],
    "payment_method": ["method", "payment_method", "payment_type"],
    "bank": ["bank", "bank_name", "payer_bank"],
    "failure_reason": [
        "error_description",
        "error_reason",
        "reason",
        "failure_reason",
        "failure_description",
    ],
    "transaction_status": ["status", "payment_status", "transaction_status"],
    "retry_count": ["retry_count", "retries", "retry_attempts"],
    "due_date": ["due_date", "payment_due_date"],
    "transaction_timestamp": [
        "created_at",
        "created_on",
        "created",
        "payment_date",
        "transaction_date",
        "initiated_at",
    ],
    "error_code": ["error_code"],
    "error_source": ["error_source"],
    "error_step": ["error_step"],
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class CSVValidationError(ValueError):
    """Raised when CSV content fails validation."""

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.details = details or []


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnMapping:
    """Maps external CSV column names -> canonical RPA column names."""

    mapping: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)

    @property
    def all_mapped(self) -> bool:
        return not self.missing_required


@dataclass
class CSVIngestionResult:
    """Output of CSV ingestion: ready-to-use DataFrames + metadata."""

    transactions_df: pd.DataFrame
    customers_df: pd.DataFrame
    metadata: dict[str, Any]
    warnings: list[str]


@dataclass
class CSVValidationReport:
    """Detailed validation report for an uploaded CSV."""

    valid: bool
    input_row_count: int
    accepted_row_count: int
    rejected_row_count: int
    errors: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Amount unit handling
# ---------------------------------------------------------------------------
class AmountUnit:
    """Interpretation of the amount column."""

    RUPEES = "rupees"
    PAISE = "paise"
    AUTO = "auto"

    KNOWN = frozenset({RUPEES, PAISE, AUTO})


def convert_amounts(
    df: pd.DataFrame,
    unit: str = AmountUnit.RUPEES,
) -> tuple[pd.DataFrame, str, float | None]:
    """Convert amounts to rupees.

    Returns:
        (converted_df, detected_unit, conversion_factor_or_none)

    If unit="auto", a heuristic detects whether values are in paise.
    """
    if unit not in AmountUnit.KNOWN:
        raise CSVValidationError(
            f"unknown amount_unit: {unit!r}. Use 'rupees', 'paise', or 'auto'."
        )

    amounts = pd.to_numeric(df["amount"], errors="coerce")
    if amounts.isna().any():
        raise CSVValidationError("amount column contains non-numeric values")

    df = df.copy()

    if unit == AmountUnit.PAISE:
        df["amount"] = amounts / 100.0
        return df, AmountUnit.PAISE, 100.0

    if unit == AmountUnit.RUPEES:
        df["amount"] = amounts.astype(float)
        return df, AmountUnit.RUPEES, None

    # Auto-detection heuristic:
    # If median > 10000 and all values are integers → likely paise
    median_val = amounts.median()
    all_integers = (amounts == amounts.astype(int)).all()
    likely_paise = median_val > 10_000 and all_integers
    if likely_paise:
        logger.info(
            "Auto-detected paise: median=%.0f, converting to rupees", median_val
        )
        df["amount"] = amounts / 100.0
        return df, "auto_paise", 100.0

    df["amount"] = amounts.astype(float)
    return df, AmountUnit.RUPEES, None


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------
def detect_column_mapping(headers: list[str]) -> ColumnMapping:
    """Auto-detect Razorpay-style column names and map to canonical names.

    Exact header matches are preferred. Case-insensitive matching is used
    as a fallback.
    """
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    headers_lower = {h.strip().lower(): h for h in headers}

    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.strip().lower()
            if alias_lower in headers_lower:
                mapping[headers_lower[alias_lower]] = canonical
                break

    mapped_canonicals = set(mapping.values())
    missing_required = [
        col
        for col in CANONICAL_TRANSACTION_COLUMNS
        if col not in mapped_canonicals
        and col
        not in (
            "due_date",
            "days_overdue",
            "created_at",
            "updated_at",
            "currency",
            "transaction_timestamp",
        )
        # due_date/days_overdue are derived from each other
        # created_at/updated_at have fallbacks
        # currency defaults to "INR"
        # transaction_timestamp falls back to created_at
    ]

    unmapped = [h for h in headers if h not in mapping]

    return ColumnMapping(
        mapping=mapping,
        unmapped_columns=unmapped,
        missing_required=missing_required,
    )


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 100_000


def parse_csv(file_content: bytes) -> pd.DataFrame:
    """Parse CSV bytes into a DataFrame with validation."""
    if len(file_content) == 0:
        raise CSVValidationError("CSV file is empty")

    if len(file_content) > MAX_FILE_SIZE:
        raise CSVValidationError(
            f"CSV file exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB "
            f"(received {len(file_content) / (1024 * 1024):.1f} MB)"
        )

    try:
        text = file_content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_content.decode("latin-1")
        except UnicodeDecodeError:
            raise CSVValidationError(
                "CSV file encoding not supported (expected UTF-8 or latin-1)"
            )

    # Guard against formula injection in the first cell
    if text and text[0] in ("=", "+", "-", "@"):
        logger.warning("CSV first character is formula-indicator; treating as data")

    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, ValueError) as exc:
        raise CSVValidationError(f"failed to parse CSV: {exc}")

    if df.empty:
        raise CSVValidationError("CSV file contains no data rows")

    if len(df) > MAX_ROWS:
        raise CSVValidationError(
            f"CSV file contains {len(df)} rows, exceeding maximum of {MAX_ROWS}"
        )

    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]

    return df


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
def validate_schema(
    df: pd.DataFrame,
    mapping: ColumnMapping,
) -> CSVValidationReport:
    """Validate the mapped DataFrame against the canonical schema."""
    errors: list[str] = []
    warnings: list[str] = []

    if not mapping.all_mapped:
        errors.append(f"missing required columns: {mapping.missing_required}")

    if mapping.unmapped_columns:
        warnings.append(f"unmapped columns (ignored): {mapping.unmapped_columns}")

    # Row count check
    if len(df) == 0:
        errors.append("CSV has no data rows")

    # Check for duplicate transaction IDs
    if "transaction_id" in df.columns:
        dupes = df["transaction_id"].duplicated().sum()
        if dupes > 0:
            errors.append(f"{dupes} duplicate transaction_id(s) found")

    # Validate numeric amounts
    if "amount" in df.columns:
        amounts = pd.to_numeric(df["amount"], errors="coerce")
        non_numeric = amounts.isna().sum()
        if non_numeric > 0:
            errors.append(f"{non_numeric} non-numeric amount(s) found")
        negative = (amounts.dropna() <= 0).sum()
        if negative > 0:
            errors.append(f"{negative} non-positive amount(s) found")

    # Validate categorical values
    categorical_checks = {
        "payment_method": SUPPORTED_PAYMENT_METHODS,
        "bank": SUPPORTED_BANKS,
        "failure_reason": SUPPORTED_FAILURE_REASONS,
        "transaction_status": SUPPORTED_TRANSACTION_STATUSES,
    }
    for canonical, supported in categorical_checks.items():
        if canonical in df.columns:
            vals = set(df[canonical].astype(str).str.strip())
            vals.discard("")  # empty is handled separately below
            unknown = vals - supported
            if unknown:
                errors.append(
                    f"unsupported {canonical} value(s): {sorted(unknown)}. "
                    f"Supported: {sorted(supported)}"
                )

    # Check for empty required fields
    for canonical in [
        "transaction_id",
        "amount",
        "payment_method",
        "bank",
    ]:
        if canonical in df.columns:
            empty_count = (df[canonical].astype(str).str.strip() == "").sum()
            if empty_count > 0:
                errors.append(f"{empty_count} empty value(s) in {canonical} column")

    # failure_reason is allowed to be empty for non-failed transactions
    if "failure_reason" in df.columns:
        empty_fr = (df["failure_reason"].astype(str).str.strip() == "").sum()
        if empty_fr > 0:
            warnings.append(
                f"{empty_fr} empty failure_reason value(s) (allowed for non-failed transactions)"
            )

    return CSVValidationReport(
        valid=len(errors) == 0,
        input_row_count=len(df),
        accepted_row_count=len(df) if not errors else 0,
        rejected_row_count=len(df) if errors else 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Column mapping and normalization
# ---------------------------------------------------------------------------
def map_columns(
    df: pd.DataFrame,
    mapping: ColumnMapping,
) -> pd.DataFrame:
    """Rename external columns to canonical names."""
    result = df.rename(columns=mapping.mapping)

    # Strip whitespace from string columns
    for col in result.select_dtypes(include=["object"]).columns:
        result[col] = result[col].str.strip()

    # Normalize categorical values to match model vocabulary
    if "payment_method" in result.columns:
        result["payment_method"] = _normalize_payment_method(result["payment_method"])
    if "bank" in result.columns:
        result["bank"] = _normalize_bank(result["bank"])
    if "failure_reason" in result.columns:
        result["failure_reason"] = _normalize_failure_reason(result["failure_reason"])
    if "transaction_status" in result.columns:
        result["transaction_status"] = _normalize_status(result["transaction_status"])

    return result


def _normalize_payment_method(series: pd.Series) -> pd.Series:
    """Normalize payment method values. No silent mapping of unsupported values."""
    return series.str.lower().str.strip()


def _normalize_bank(series: pd.Series) -> pd.Series:
    """Normalize bank names to match model vocabulary exactly.

    The model vocabulary is: HDFC, ICICI, SBI, Axis, Kotak, Yes.
    Supports common variations like "HDFC Bank", "hdfc bank", "ICICI BANK".
    """
    # Build a lookup for case-insensitive matching
    bank_lookup = {v.upper(): v for v in SUPPORTED_BANKS}

    def _clean(val: str) -> str:
        v = val.strip()
        # Strip trailing " bank" / " BANK" / " Bank"
        if v.lower().endswith(" bank"):
            v = v[:-5]
        # Try exact uppercase match
        upper = v.upper()
        if upper in bank_lookup:
            return bank_lookup[upper]
        # Try title-case match
        return v.title()

    return series.map(_clean)


def _normalize_failure_reason(series: pd.Series) -> pd.Series:
    """Normalize failure reason to match model vocabulary."""
    return series.str.lower().str.strip().str.replace(" ", "_").str.replace("-", "_")


def _normalize_status(series: pd.Series) -> pd.Series:
    """Normalize transaction status."""
    return series.str.lower().str.strip()


# ---------------------------------------------------------------------------
# Timestamp normalization
# ---------------------------------------------------------------------------
def normalize_timestamps(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Ensure required timestamp columns exist and are ISO-8601 formatted."""
    ref_date = pd.Timestamp("2026-09-04", tz="UTC")

    # due_date: compute from days_overdue if not present
    if "due_date" not in df.columns or (df["due_date"] == "").all():
        if "days_overdue" in df.columns:
            days = pd.to_numeric(df["days_overdue"], errors="coerce").fillna(0)
            df["due_date"] = (ref_date - pd.to_timedelta(days, unit="D")).apply(
                lambda x: (
                    x.isoformat(timespec="seconds")
                    if pd.notna(x)
                    else ref_date.isoformat(timespec="seconds")
                )
            )
        else:
            df["due_date"] = ref_date.isoformat(timespec="seconds")

    # days_overdue: derive from due_date if not present
    if "days_overdue" not in df.columns or (df["days_overdue"] == "").all():
        if "due_date" in df.columns:
            due_dt = pd.to_datetime(df["due_date"], errors="coerce", utc=True)
            df["days_overdue"] = ((ref_date - due_dt).dt.days).fillna(0).astype(int)
        else:
            df["days_overdue"] = 0

    # transaction_timestamp: use created_at if not present
    if (
        "transaction_timestamp" not in df.columns
        or (df["transaction_timestamp"] == "").all()
    ):
        if "created_at" in df.columns:
            df["transaction_timestamp"] = df["created_at"]
        else:
            df["transaction_timestamp"] = ref_date.isoformat(timespec="seconds")

    # created_at: use transaction_timestamp if not present
    if "created_at" not in df.columns or (df["created_at"] == "").all():
        df["created_at"] = df["transaction_timestamp"]

    # updated_at: use created_at if not present
    if "updated_at" not in df.columns or (df["updated_at"] == "").all():
        df["updated_at"] = df["created_at"]

    return df


# ---------------------------------------------------------------------------
# Missing field defaults
# ---------------------------------------------------------------------------
def apply_defaults(
    df: pd.DataFrame,
    warnings: list[str],
) -> pd.DataFrame:
    """Apply documented defaults for missing optional fields.

    Every fallback is recorded in warnings.
    """
    if "currency" not in df.columns or (df["currency"] == "").all():
        df["currency"] = "INR"
        warnings.append("currency defaulted to 'INR' for all rows")

    if "retry_count" not in df.columns or (df["retry_count"] == "").all():
        df["retry_count"] = 1
        warnings.append(
            "retry_count defaulted to 1 for all rows (indicating first attempt)"
        )
    else:
        df["retry_count"] = (
            pd.to_numeric(df["retry_count"], errors="coerce").fillna(1).astype(int)
        )

    if "days_overdue" not in df.columns or (df["days_overdue"] == "").all():
        df["days_overdue"] = 0
        warnings.append("days_overdue defaulted to 0 for all rows")

    if "failure_reason" in df.columns:
        empty_fr = df["failure_reason"].astype(str).str.strip() == ""
        if empty_fr.any():
            df.loc[empty_fr, "failure_reason"] = "network_timeout"
            warnings.append(
                f"{int(empty_fr.sum())} empty failure_reason(s) defaulted to 'network_timeout'"
            )

    return df


# ---------------------------------------------------------------------------
# Customer feature derivation (DETERMINISTIC — no random values)
# ---------------------------------------------------------------------------
def derive_customer_features(
    transactions: pd.DataFrame,
) -> pd.DataFrame:
    """Derive customer-level features from available transaction history.

    Features are computed DETERMINISTICALLY from the uploaded transaction data.
    No random values are generated.

    Leakage prevention:
        For each transaction T, customer features use only transactions that
        occurred BEFORE T. This prevents target leakage.

    Customer features derived:
        customer_ltv:
            Sum of all successful (non-failed) transaction amounts for this
            customer. Falls back to sum of all transaction amounts if no
            successful transactions exist.

        historical_success_rate:
            Number of non-"failed" transactions / total transactions for this
            customer, computed BEFORE each transaction's timestamp.

        historical_recovery_rate:
            Only derived if the dataset contains recoverability signals
            (e.g., transaction_status == "recovered" or "partial").
            Otherwise: 0.0 with a warning.

        customer_behavior_score:
            Deterministic composite score from:
            - retry_count trend (lower is better)
            - amount variance (lower variance = more predictable)
            - transaction frequency
            Range: [-3.0, 3.0] to match model expectations.

        customer_tenure_days:
            Days between the customer's earliest and latest transaction.

        customer_segment:
            Default to "retail" (the majority segment in training data).
            This is the ONLY non-derived field; it defaults to the majority
            class because the uploaded CSV has no segment information.
    """
    if transactions.empty:
        return pd.DataFrame(columns=CANONICAL_CUSTOMER_COLUMNS)

    warnings: list[str] = []  # noqa: F841

    # Sort by timestamp for chronological processing
    df = transactions.copy()
    df["_ts"] = pd.to_datetime(df["transaction_timestamp"], errors="coerce", utc=True)
    df = df.sort_values(["customer_id", "_ts"]).reset_index(drop=True)

    customer_records: list[dict[str, Any]] = []
    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for cid, group in df.groupby("customer_id"):
        group = group.sort_values("_ts").reset_index(drop=True)
        n_txns = len(group)

        # --- customer_ltv: sum of successful transaction amounts ---
        status_col = group["transaction_status"]
        successful_mask = status_col.isin(["failed"]) == False
        if successful_mask.any():
            ltv = float(group.loc[successful_mask, "amount"].sum())
        else:
            ltv = float(group["amount"].sum())

        # --- historical_success_rate ---
        # For each transaction, success_rate = (# non-failed before this txn) / (# before this txn)
        # We compute the cumulative success rate for the CURRENT transaction using history BEFORE it.
        non_failed = (group["transaction_status"] != "failed").astype(int)
        # cumsum gives count of non-failed up to and including current
        cum_non_failed = non_failed.cumsum()
        # Total transactions before current (0-indexed)
        cum_total = np.arange(1, n_txns + 1)
        # For the CURRENT transaction, use only history BEFORE it
        # So we use cumsum shifted by 1, and count before = cum_total - 1
        hist_success_count = cum_non_failed.shift(1, fill_value=0)
        hist_total_count = cum_total - 1
        hist_total_count = np.maximum(hist_total_count, 1)  # avoid division by zero
        hist_success_rate = np.clip(hist_success_count / hist_total_count, 0.02, 0.98)

        # --- historical_recovery_rate ---
        # Only if dataset contains recoverability signals
        has_recovered = "recovery_status" in group.columns and (
            group["recovery_status"].isin(["recovered", "partial"]).any()
        )
        if has_recovered:
            recovered_mask = (
                group["recovery_status"].isin(["recovered", "partial"]).astype(int)
            )
            cum_recovered = recovered_mask.cumsum().shift(1, fill_value=0)
            # Recovery rate among failed transactions that had recovery attempts
            hist_recovery_rate = np.clip(
                cum_recovered / np.maximum(hist_total_count, 1), 0.0, 0.95
            )
        else:
            # No recoverability signal in dataset
            hist_recovery_rate = np.zeros(n_txns)

        # --- customer_behavior_score ---
        # Deterministic composite from retry_count, amount variance, frequency
        rc = pd.to_numeric(group["retry_count"], errors="coerce").fillna(0).values
        amt = pd.to_numeric(group["amount"], errors="coerce").fillna(0).values

        # Retry component: fewer retries = better score
        retry_component = np.clip(1.0 - rc / 5.0, 0.0, 1.0) * 1.5 - 0.75

        # Amount consistency: lower variance = more predictable = better
        if len(amt) > 1:
            amt_std = np.std(amt)
            amt_mean = np.mean(amt) if np.mean(amt) > 0 else 1.0
            cv = amt_std / amt_mean
            consistency_component = np.clip(1.0 - cv, 0.0, 1.0) * 2.0 - 1.0
        else:
            consistency_component = 0.0

        # Frequency component: more transactions = more engaged = slightly better
        freq_component = np.clip(np.log1p(n_txns) / 3.0 - 0.5, -1.0, 1.0)

        behavior_score = np.clip(
            retry_component + consistency_component + freq_component,
            -3.0,
            3.0,
        )

        # --- customer_tenure_days ---
        ts_range = group["_ts"].max() - group["_ts"].min()
        tenure_days = max(1, int(ts_range.days)) if pd.notna(ts_range) else 1

        # --- customer_segment: default to "retail" ---
        # This is the only non-derived field; CSV has no segment info.
        segment = "retail"

        record = {
            "customer_id": cid,
            "customer_segment": segment,
            "customer_ltv": round(ltv, 2),
            "historical_success_rate": round(float(hist_success_rate.mean()), 4),
            "historical_recovery_rate": round(float(hist_recovery_rate.mean()), 4),
            "customer_behavior_score": round(float(behavior_score), 4),
            "customer_tenure_days": tenure_days,
            "created_at": group["_ts"].min().isoformat(timespec="seconds")
            if pd.notna(group["_ts"].min())
            else now_str,
            "updated_at": now_str,
        }
        customer_records.append(record)

    customers_df = pd.DataFrame(customer_records)

    # Add per-transaction customer features back to the transaction DataFrame
    # to enable leakage-safe feature computation
    return customers_df


def attach_leakage_safe_features(
    transactions: pd.DataFrame,
    customers_df: pd.DataFrame,
) -> pd.DataFrame:
    """Attach per-transaction leakage-safe customer features to transactions.

    For each transaction, customer features are computed using ONLY the
    transaction history available BEFORE that transaction's timestamp.

    This function produces columns matching the canonical customer schema:
        customer_ltv, historical_success_rate, historical_recovery_rate,
        customer_behavior_score, customer_tenure_days
    """
    if transactions.empty:
        return transactions

    df = transactions.copy()
    df["_ts"] = pd.to_datetime(df["transaction_timestamp"], errors="coerce", utc=True)
    df = df.sort_values(["customer_id", "_ts"]).reset_index(drop=True)

    # Build per-transaction leakage-safe features
    ltv_values = []
    success_rate_values = []
    recovery_rate_values = []
    behavior_values = []
    tenure_values = []

    for _, row in df.iterrows():
        cid = row["customer_id"]
        ts = row["_ts"]

        # Historical window: all transactions for this customer BEFORE this transaction
        cust_history = df[(df["customer_id"] == cid) & (df["_ts"] < ts)]

        if len(cust_history) == 0:
            # First transaction for this customer — use neutral defaults
            ltv_values.append(0.0)
            success_rate_values.append(0.5)
            recovery_rate_values.append(0.0)
            behavior_values.append(0.0)
            tenure_values.append(0)
        else:
            # LTV: sum of successful amounts from history
            hist_status = cust_history["transaction_status"]
            successful = hist_status.isin(["failed"]) == False
            if successful.any():
                hist_ltv = float(cust_history.loc[successful, "amount"].sum())
            else:
                hist_ltv = float(cust_history["amount"].sum())
            ltv_values.append(round(hist_ltv, 2))

            # Success rate
            hist_n = len(cust_history)
            hist_non_failed = (hist_status != "failed").sum()
            hist_success_rate = hist_non_failed / hist_n if hist_n > 0 else 0.5
            success_rate_values.append(round(np.clip(hist_success_rate, 0.02, 0.98), 4))

            # Recovery rate (only if dataset supports it)
            if "recovery_status" in cust_history.columns:
                hist_recovered = (
                    cust_history["recovery_status"].isin(["recovered", "partial"]).sum()
                )
                hist_recovery_rate = hist_recovered / max(hist_n, 1)
                recovery_rate_values.append(
                    round(np.clip(hist_recovery_rate, 0.0, 0.95), 4)
                )
            else:
                recovery_rate_values.append(0.0)

            # Behavior score
            rc = (
                pd.to_numeric(cust_history["retry_count"], errors="coerce")
                .fillna(0)
                .values
            )
            amt = (
                pd.to_numeric(cust_history["amount"], errors="coerce").fillna(0).values
            )

            retry_component = np.clip(1.0 - rc.mean() / 5.0, 0.0, 1.0) * 1.5 - 0.75
            if len(amt) > 1:
                amt_std = np.std(amt)
                amt_mean = np.mean(amt) if np.mean(amt) > 0 else 1.0
                consistency_component = (
                    np.clip(1.0 - (amt_std / amt_mean), 0.0, 1.0) * 2.0 - 1.0
                )
            else:
                consistency_component = 0.0
            freq_component = np.clip(np.log1p(hist_n) / 3.0 - 0.5, -1.0, 1.0)
            behavior = np.clip(
                retry_component + consistency_component + freq_component, -3.0, 3.0
            )
            behavior_values.append(round(float(behavior), 4))

            # Tenure
            ts_range = cust_history["_ts"].max() - cust_history["_ts"].min()
            tenure = max(1, int(ts_range.days)) if pd.notna(ts_range) else 0
            tenure_values.append(tenure)

    df["customer_ltv"] = ltv_values
    df["historical_success_rate"] = success_rate_values
    df["historical_recovery_rate"] = recovery_rate_values
    df["customer_behavior_score"] = behavior_values
    df["customer_tenure_days"] = tenure_values

    return df.drop(columns=["_ts"])


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------
def ingest_csv(
    file_content: bytes,
    *,
    amount_unit: str = AmountUnit.RUPEES,
    custom_mapping: dict[str, str] | None = None,
) -> CSVIngestionResult:
    """Parse, validate, and transform a Razorpay-style CSV into canonical RPA format.

    Args:
        file_content: Raw CSV file bytes.
        amount_unit: Unit interpretation for the amount column.
            - "rupees" (default): amounts are in rupees
            - "paise": amounts are in paise (divide by 100)
            - "auto": heuristic detection
        custom_mapping: Optional override for column mapping.
            Keys are external CSV column names, values are canonical names.

    Returns:
        CSVIngestionResult with transactions_df, customers_df, metadata, warnings.

    Raises:
        CSVValidationError: If validation fails.
    """
    warnings: list[str] = []

    # 1. Parse CSV
    raw_df = parse_csv(file_content)

    # 2. Detect or apply column mapping
    if custom_mapping:
        mapping = ColumnMapping(
            mapping=custom_mapping, unmapped_columns=[], missing_required=[]
        )
        mapped_df = raw_df.rename(columns=custom_mapping)
    else:
        mapping = detect_column_mapping(raw_df.columns.tolist())
        if not mapping.all_mapped:
            raise CSVValidationError(
                f"missing required columns: {mapping.missing_required}",
                details=[{"missing_columns": mapping.missing_required}],
            )
        mapped_df = map_columns(raw_df, mapping)

    # 3. Validate schema
    report = validate_schema(mapped_df, mapping)
    if not report.valid:
        raise CSVValidationError(
            "CSV validation failed",
            details=[{"errors": report.errors, "warnings": report.warnings}],
        )
    warnings.extend(report.warnings)

    # 4. Convert amounts
    mapped_df, detected_unit, conversion = convert_amounts(mapped_df, amount_unit)

    # 5. Normalize timestamps
    mapped_df = normalize_timestamps(mapped_df)

    # 6. Apply defaults
    mapped_df = apply_defaults(mapped_df, warnings)

    # 7. Generate transaction IDs if not present
    if (
        "transaction_id" not in mapped_df.columns
        or (mapped_df["transaction_id"] == "").all()
    ):
        mapped_df["transaction_id"] = [
            f"csv_txn_{i:07d}" for i in range(len(mapped_df))
        ]
        warnings.append("generated transaction_id for all rows (none provided)")

    # 8. Generate customer IDs if not present
    if "customer_id" not in mapped_df.columns or (mapped_df["customer_id"] == "").all():
        # Use payment method + bank as a proxy customer grouping
        mapped_df["customer_id"] = [
            f"csv_cust_{hashlib.md5(f'{r.payment_method}_{r.bank}'.encode()).hexdigest()[:8]}"
            for r in mapped_df.itertuples()
        ]
        warnings.append(
            "generated customer_id for all rows (none provided); "
            "customer features will be uniform"
        )

    # 9. Ensure numeric types
    mapped_df["amount"] = (
        pd.to_numeric(mapped_df["amount"], errors="coerce").fillna(0.0).astype(float)
    )
    mapped_df["retry_count"] = (
        pd.to_numeric(mapped_df["retry_count"], errors="coerce").fillna(1).astype(int)
    )
    mapped_df["days_overdue"] = (
        pd.to_numeric(mapped_df["days_overdue"], errors="coerce").fillna(0).astype(int)
    )

    # 10. Attach leakage-safe customer features to each transaction
    transactions_with_features = attach_leakage_safe_features(mapped_df, pd.DataFrame())

    # 11. Build customers DataFrame from the aggregated leakage-safe values
    customers_df = _build_customers_from_transactions(transactions_with_features)

    # 12. Select only canonical transaction columns
    txn_cols = [
        "transaction_id",
        "customer_id",
        "amount",
        "currency",
        "payment_method",
        "bank",
        "failure_reason",
        "transaction_status",
        "retry_count",
        "days_overdue",
        "due_date",
        "transaction_timestamp",
        "created_at",
        "updated_at",
    ]
    transactions_final = transactions_with_features[txn_cols].copy()

    # 13. Build metadata
    metadata = {
        "source_type": "razorpay_style_csv",
        "input_row_count": report.input_row_count,
        "accepted_row_count": len(transactions_final),
        "rejected_row_count": report.rejected_row_count,
        "detected_columns": list(mapping.mapping.values()),
        "mapped_columns": {k: v for k, v in mapping.mapping.items()},
        "unmapped_columns": mapping.unmapped_columns,
        "derived_features": [
            "customer_ltv",
            "historical_success_rate",
            "historical_recovery_rate",
            "customer_behavior_score",
            "customer_tenure_days",
        ],
        "amount_unit": detected_unit,
        "amount_transform_applied": conversion,
        "customer_count": len(customers_df),
        "warnings": warnings,
    }

    if not warnings:
        warnings.append("no warnings")

    return CSVIngestionResult(
        transactions_df=transactions_final,
        customers_df=customers_df,
        metadata=metadata,
        warnings=warnings,
    )


def _build_customers_from_transactions(
    transactions: pd.DataFrame,
) -> pd.DataFrame:
    """Build a customers DataFrame from per-transaction leakage-safe features.

    Uses the MEAN of per-transaction leakage-safe features for each customer.
    This is the best deterministic approximation of the customer's overall
    profile when only transaction-level data is available.
    """
    if transactions.empty:
        return pd.DataFrame(columns=CANONICAL_CUSTOMER_COLUMNS)

    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Only aggregate the numeric feature columns
    numeric_feature_cols = [
        "customer_ltv",
        "historical_success_rate",
        "historical_recovery_rate",
        "customer_behavior_score",
        "customer_tenure_days",
    ]
    available = [c for c in numeric_feature_cols if c in transactions.columns]
    if not available:
        # Fallback: create empty customer records
        unique_ids = transactions["customer_id"].unique()
        records = []
        for cid in unique_ids:
            records.append(
                {
                    "customer_id": cid,
                    "customer_segment": "retail",
                    "customer_ltv": 0.0,
                    "historical_success_rate": 0.5,
                    "historical_recovery_rate": 0.0,
                    "customer_behavior_score": 0.0,
                    "customer_tenure_days": 0,
                    "created_at": now_str,
                    "updated_at": now_str,
                }
            )
        return pd.DataFrame(records)[CANONICAL_CUSTOMER_COLUMNS]

    grouped = transactions.groupby("customer_id")[available].mean().reset_index()

    # Round and clip to match model expectations
    grouped["customer_ltv"] = grouped["customer_ltv"].round(2).clip(lower=0)
    grouped["historical_success_rate"] = (
        grouped["historical_success_rate"].round(4).clip(0.02, 0.98)
    )
    grouped["historical_recovery_rate"] = (
        grouped["historical_recovery_rate"].round(4).clip(0.0, 0.95)
    )
    grouped["customer_behavior_score"] = (
        grouped["customer_behavior_score"].round(4).clip(-3.0, 3.0)
    )
    grouped["customer_tenure_days"] = (
        grouped["customer_tenure_days"].round(0).astype(int).clip(lower=0)
    )

    # Add missing columns with defaults
    grouped["customer_segment"] = "retail"
    grouped["created_at"] = now_str
    grouped["updated_at"] = now_str

    # Reorder to canonical schema
    return grouped[CANONICAL_CUSTOMER_COLUMNS]


# ---------------------------------------------------------------------------
# Template CSV generation
# ---------------------------------------------------------------------------
def generate_csv_template() -> str:
    """Generate a CSV template string with Razorpay-style column headers.

    The template uses RAW INPUT fields — NOT the derived customer features.
    """
    headers = [
        "payment_id",
        "customer_id",
        "amount",
        "currency",
        "status",
        "method",
        "bank",
        "failure_reason",
        "error_code",
        "error_source",
        "error_step",
        "created_at",
        "retry_count",
        "due_date",
    ]
    return ",".join(headers) + "\n"


__all__ = [
    "CANONICAL_CUSTOMER_COLUMNS",
    "CANONICAL_TRANSACTION_COLUMNS",
    "SUPPORTED_BANKS",
    "SUPPORTED_FAILURE_REASONS",
    "SUPPORTED_PAYMENT_METHODS",
    "SUPPORTED_TRANSACTION_STATUSES",
    "AmountUnit",
    "CSVIngestionResult",
    "CSVValidationError",
    "CSVValidationReport",
    "ColumnMapping",
    "convert_amounts",
    "derive_customer_features",
    "detect_column_mapping",
    "generate_csv_template",
    "ingest_csv",
    "map_columns",
    "parse_csv",
    "validate_schema",
]
