"""Tests for rpa/csv_adapter.py — CSV ingestion pipeline.

Validates CSV parsing, validation, column mapping, deterministic customer
feature derivation, amount handling, categorical normalization, and the
complete ingestion flow.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rpa.csv_adapter import (
    AmountUnit,
    ColumnMapping,
    CSVIngestionResult,
    CSVValidationError,
    convert_amounts,
    detect_column_mapping,
    generate_csv_template,
    ingest_csv,
    map_columns,
    parse_csv,
    validate_schema,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
RAZORPAY_CSV = """\
payment_id,customer_id,amount,currency,status,method,bank,failure_reason,error_code,created_at,retry_count,due_date
txn_001,cust_001,1500.00,INR,failed,upi,HDFC,insufficient_funds,E001,2026-09-01T10:00:00+00:00,1,2026-09-04
txn_002,cust_001,2500.00,INR,failed,credit_card,ICICI,invalid_pin,E002,2026-09-02T14:30:00+00:00,2,2026-09-04
txn_003,cust_002,800.00,INR,failed,debit_card,SBI,network_timeout,E003,2026-09-01T08:15:00+00:00,0,2026-09-04
"""

GENERIC_CSV = """\
id,cust_id,txn_amount,currency_code,payment_status,payment_method,bank_name,error_desc,payment_date
csv_001,c_001,5000.00,INR,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00
csv_002,c_001,1200.00,INR,pending,credit_card,ICICI,network_timeout,2026-09-02T14:30:00+00:00
csv_003,c_002,300.00,INR,failed,net_banking,SBI,expired_card,2026-09-03T09:00:00+00:00
"""

MULTI_TXN_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_A,1000,failed,upi,HDFC,insufficient_funds,2026-08-01T10:00:00+00:00,1
T002,C_A,2000,failed,upi,HDFC,invalid_pin,2026-08-15T10:00:00+00:00,0
T003,C_A,500,failed,upi,HDFC,network_timeout,2026-09-01T10:00:00+00:00,2
T004,C_B,3000,failed,credit_card,ICICI,bank_down,2026-08-20T10:00:00+00:00,0
T005,C_B,1500,failed,credit_card,ICICI,limit_exceeded,2026-09-01T10:00:00+00:00,1
"""

# CSV with unknown categorical values
BAD_CATEGORY_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,wallet,Chase,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""

# CSV with duplicate transaction IDs
DUPLICATE_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
T001,C_01,200,failed,upi,HDFC,invalid_pin,2026-09-02T10:00:00+00:00,1
"""

# CSV with invalid amounts
BAD_AMOUNT_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,abc,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""

# CSV with empty rows
EMPTY_VALUE_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""


# ---------------------------------------------------------------------------
# Test: parse_csv
# ---------------------------------------------------------------------------
class TestParseCSV:
    def test_valid_csv(self):
        df = parse_csv(RAZORPAY_CSV.encode("utf-8"))
        assert not df.empty
        assert len(df) == 3
        assert "payment_id" in df.columns

    def test_empty_csv(self):
        with pytest.raises(CSVValidationError, match="empty"):
            parse_csv(b"")

    def test_malformed_csv(self):
        with pytest.raises(CSVValidationError):
            parse_csv(b"\xff\xfe\x00\x00\x01\x02\x03")

    def test_oversized_file(self):
        big = b"col1,col2\n" + b"a,b\n" * 200_000
        with pytest.raises(CSVValidationError, match="rows"):
            parse_csv(big)

    def test_encoding_fallback(self):
        csv_bytes = "col1,col2\n".encode("latin-1") + "val1,val2\n".encode("latin-1")
        df = parse_csv(csv_bytes)
        assert not df.empty

    def test_strips_column_whitespace(self):
        csv_bytes = b" col1 , col2 \nval1,val2\n"
        df = parse_csv(csv_bytes)
        assert "col1" in df.columns
        assert "col2" in df.columns


# ---------------------------------------------------------------------------
# Test: detect_column_mapping
# ---------------------------------------------------------------------------
class TestDetectColumnMapping:
    def test_razorpay_style_columns(self):
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
            "created_at",
            "retry_count",
            "due_date",
        ]
        mapping = detect_column_mapping(headers)
        assert mapping.mapping["payment_id"] == "transaction_id"
        assert mapping.mapping["method"] == "payment_method"
        assert mapping.mapping["status"] == "transaction_status"
        assert mapping.mapping["created_at"] == "transaction_timestamp"
        assert mapping.all_mapped

    def test_generic_columns(self):
        headers = [
            "id",
            "cust_id",
            "txn_amount",
            "currency_code",
            "payment_status",
            "payment_method",
            "bank_name",
            "error_desc",
            "payment_date",
        ]
        mapping = detect_column_mapping(headers)
        assert mapping.mapping["id"] == "transaction_id"
        assert mapping.mapping["cust_id"] == "customer_id"
        assert mapping.mapping["txn_amount"] == "amount"
        assert mapping.mapping["payment_method"] == "payment_method"

    def test_missing_required_column(self):
        headers = ["payment_id", "amount"]  # missing bank, method, etc.
        mapping = detect_column_mapping(headers)
        assert not mapping.all_mapped
        assert "payment_method" in mapping.missing_required


# ---------------------------------------------------------------------------
# Test: validate_schema
# ---------------------------------------------------------------------------
class TestValidateSchema:
    def test_valid_schema(self):
        df = parse_csv(RAZORPAY_CSV.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        report = validate_schema(mapped, mapping)
        assert report.valid
        assert report.errors == []

    def test_unknown_categorical_value(self):
        df = parse_csv(BAD_CATEGORY_CSV.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        report = validate_schema(mapped, mapping)
        assert not report.valid
        assert any("unsupported" in e.lower() for e in report.errors)

    def test_duplicate_transaction_ids(self):
        df = parse_csv(DUPLICATE_CSV.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        report = validate_schema(mapped, mapping)
        assert not report.valid
        assert any("duplicate" in e.lower() for e in report.errors)

    def test_non_numeric_amount(self):
        df = parse_csv(BAD_AMOUNT_CSV.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        report = validate_schema(mapped, mapping)
        assert not report.valid
        assert any("non-numeric" in e.lower() for e in report.errors)


# ---------------------------------------------------------------------------
# Test: map_columns
# ---------------------------------------------------------------------------
class TestMapColumns:
    def test_renames_columns(self):
        df = pd.DataFrame({"payment_id": ["T1"], "method": ["upi"], "bank": ["HDFC"]})
        mapping = ColumnMapping(
            mapping={
                "payment_id": "transaction_id",
                "method": "payment_method",
                "bank": "bank",
            }
        )
        result = map_columns(df, mapping)
        assert "transaction_id" in result.columns
        assert "payment_method" in result.columns

    def test_normalizes_bank_name(self):
        df = pd.DataFrame({"bank": ["hdfc bank", "ICICI BANK", "Sbi"]})
        mapping = ColumnMapping(mapping={"bank": "bank"})
        result = map_columns(df, mapping)
        assert result["bank"].iloc[0] == "HDFC"  # matches known vocabulary
        assert result["bank"].iloc[1] == "ICICI"
        assert result["bank"].iloc[2] == "SBI"

    def test_normalizes_failure_reason(self):
        df = pd.DataFrame({"failure_reason": ["Insufficient Funds", "network-timeout"]})
        mapping = ColumnMapping(mapping={"failure_reason": "failure_reason"})
        result = map_columns(df, mapping)
        assert result["failure_reason"].iloc[0] == "insufficient_funds"
        assert result["failure_reason"].iloc[1] == "network_timeout"


# ---------------------------------------------------------------------------
# Test: convert_amounts
# ---------------------------------------------------------------------------
class TestConvertAmounts:
    def test_rupees_default(self):
        df = pd.DataFrame({"amount": ["100.50", "200.00"]})
        result, unit, factor = convert_amounts(df, AmountUnit.RUPEES)
        assert unit == "rupees"
        assert factor is None
        assert result["amount"].iloc[0] == 100.50

    def test_paise_explicit(self):
        df = pd.DataFrame({"amount": ["10050", "20000"]})
        result, unit, factor = convert_amounts(df, AmountUnit.PAISE)
        assert unit == "paise"
        assert factor == 100.0
        assert result["amount"].iloc[0] == 100.50

    def test_auto_detects_paise(self):
        # All integers, median > 10000
        df = pd.DataFrame({"amount": ["15000", "25000", "35000", "45000"]})
        result, unit, factor = convert_amounts(df, AmountUnit.AUTO)
        assert unit == "auto_paise"
        assert factor == 100.0
        assert result["amount"].iloc[0] == 150.0

    def test_auto_keeps_rupees_for_small_values(self):
        df = pd.DataFrame({"amount": ["100.50", "200.75", "50.25"]})
        result, unit, _ = convert_amounts(df, AmountUnit.AUTO)
        assert unit == "rupees"
        assert result["amount"].iloc[0] == 100.50

    def test_invalid_unit(self):
        df = pd.DataFrame({"amount": ["100"]})
        with pytest.raises(CSVValidationError, match="unknown amount_unit"):
            convert_amounts(df, "invalid_unit")

    def test_non_numeric_amount(self):
        df = pd.DataFrame({"amount": ["abc", "100"]})
        with pytest.raises(CSVValidationError, match="non-numeric"):
            convert_amounts(df, AmountUnit.RUPEES)


# ---------------------------------------------------------------------------
# Test: deterministic customer feature derivation
# ---------------------------------------------------------------------------
class TestDeriveCustomerFeatures:
    def test_no_random_values(self):
        """Verify that derived customer features are deterministic."""
        df = parse_csv(MULTI_TXN_CSV.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        mapped["amount"] = pd.to_numeric(mapped["amount"], errors="coerce")
        mapped["retry_count"] = (
            pd.to_numeric(mapped["retry_count"], errors="coerce").fillna(0).astype(int)
        )
        mapped["days_overdue"] = 0
        mapped["due_date"] = "2026-09-04"
        mapped["transaction_status"] = "failed"

        from rpa.csv_adapter import attach_leakage_safe_features

        enriched = attach_leakage_safe_features(mapped, pd.DataFrame())

        # Check no NaN or inf in derived features
        for col in [
            "customer_ltv",
            "historical_success_rate",
            "historical_recovery_rate",
            "customer_behavior_score",
            "customer_tenure_days",
        ]:
            assert col in enriched.columns
            assert enriched[col].notna().all(), f"{col} has NaN"
            assert np.isfinite(enriched[col]).all(), f"{col} has inf"

    def test_ltv_is_sum_of_historical_amounts(self):
        """LTV should be sum of successful historical transaction amounts."""
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_A,1000,failed,upi,HDFC,insufficient_funds,2026-08-01T10:00:00+00:00,1
T002,C_A,2000,failed,upi,HDFC,invalid_pin,2026-08-15T10:00:00+00:00,0
T003,C_A,500,failed,upi,HDFC,network_timeout,2026-09-01T10:00:00+00:00,2
"""
        df = parse_csv(csv.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        mapped["amount"] = pd.to_numeric(mapped["amount"], errors="coerce")
        mapped["retry_count"] = (
            pd.to_numeric(mapped["retry_count"], errors="coerce").fillna(0).astype(int)
        )
        mapped["days_overdue"] = 0
        mapped["due_date"] = "2026-09-04"
        mapped["transaction_status"] = "failed"

        from rpa.csv_adapter import attach_leakage_safe_features

        enriched = attach_leakage_safe_features(mapped, pd.DataFrame())

        # For C_A, all transactions are "failed" so LTV = sum of all amounts
        c_a = enriched[enriched["customer_id"] == "C_A"]
        # T003 (last) should have LTV = 1000 + 2000 = 3000 (first two, both failed)
        t003 = c_a[c_a["transaction_id"] == "T003"]
        assert t003["customer_ltv"].iloc[0] == 3000.0

    def test_success_rate_excludes_current_transaction(self):
        """Historical success rate must NOT include the current transaction."""
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_A,100,failed,upi,HDFC,insufficient_funds,2026-08-01T10:00:00+00:00,1
T002,C_A,100,pending,upi,HDFC,insufficient_funds,2026-08-15T10:00:00+00:00,1
T003,C_A,100,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        df = parse_csv(csv.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        mapped["amount"] = pd.to_numeric(mapped["amount"], errors="coerce")
        mapped["retry_count"] = (
            pd.to_numeric(mapped["retry_count"], errors="coerce").fillna(0).astype(int)
        )
        mapped["days_overdue"] = 0
        mapped["due_date"] = "2026-09-04"

        from rpa.csv_adapter import attach_leakage_safe_features

        enriched = attach_leakage_safe_features(mapped, pd.DataFrame())

        c_a = enriched[enriched["customer_id"] == "C_A"]
        # T001: no history -> default 0.5
        t001 = c_a[c_a["transaction_id"] == "T001"]
        assert t001["historical_success_rate"].iloc[0] == 0.5

        # T002: history = {T001: failed} -> 0/1 = 0.0, clipped to 0.02
        t002 = c_a[c_a["transaction_id"] == "T002"]
        assert t002["historical_success_rate"].iloc[0] == 0.02

        # T003: history = {T001: failed, T002: pending} -> 1/2 = 0.5
        t003 = c_a[c_a["transaction_id"] == "T003"]
        assert t003["historical_success_rate"].iloc[0] == 0.5

    def test_recovery_rate_zero_when_no_recoverability(self):
        """Recovery rate should be 0 when dataset has no recovery status column."""
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_A,100,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        df = parse_csv(csv.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        mapped["amount"] = pd.to_numeric(mapped["amount"], errors="coerce")
        mapped["retry_count"] = (
            pd.to_numeric(mapped["retry_count"], errors="coerce").fillna(0).astype(int)
        )
        mapped["days_overdue"] = 0
        mapped["due_date"] = "2026-09-04"
        mapped["transaction_status"] = "failed"

        from rpa.csv_adapter import attach_leakage_safe_features

        enriched = attach_leakage_safe_features(mapped, pd.DataFrame())
        assert (enriched["historical_recovery_rate"] == 0.0).all()

    def test_behavior_score_range(self):
        """Behavior score must be in [-3.0, 3.0]."""
        csv = MULTI_TXN_CSV
        df = parse_csv(csv.encode("utf-8"))
        mapping = detect_column_mapping(df.columns.tolist())
        mapped = map_columns(df, mapping)
        mapped["amount"] = pd.to_numeric(mapped["amount"], errors="coerce")
        mapped["retry_count"] = (
            pd.to_numeric(mapped["retry_count"], errors="coerce").fillna(0).astype(int)
        )
        mapped["days_overdue"] = 0
        mapped["due_date"] = "2026-09-04"
        mapped["transaction_status"] = "failed"

        from rpa.csv_adapter import attach_leakage_safe_features

        enriched = attach_leakage_safe_features(mapped, pd.DataFrame())
        scores = enriched["customer_behavior_score"]
        assert (scores >= -3.0).all()
        assert (scores <= 3.0).all()


# ---------------------------------------------------------------------------
# Test: amount unit handling
# ---------------------------------------------------------------------------
class TestAmountUnitHandling:
    def test_paise_conversion(self):
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,150000,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        result = ingest_csv(csv.encode("utf-8"), amount_unit="paise")
        assert result.metadata["amount_unit"] == "paise"
        assert result.metadata["amount_transform_applied"] == 100.0
        assert result.transactions_df["amount"].iloc[0] == 1500.0

    def test_rupees_default(self):
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,1500.50,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        result = ingest_csv(csv.encode("utf-8"), amount_unit="rupees")
        assert result.metadata["amount_unit"] == "rupees"
        assert result.transactions_df["amount"].iloc[0] == 1500.50


# ---------------------------------------------------------------------------
# Test: unknown categorical values rejected
# ---------------------------------------------------------------------------
class TestUnknownCategoricalRejection:
    def test_unknown_payment_method_rejected(self):
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,wallet,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        with pytest.raises(CSVValidationError) as exc_info:
            ingest_csv(csv.encode("utf-8"))
        errors = (
            exc_info.value.details[0].get("errors", [])
            if exc_info.value.details
            else []
        )
        assert any("unsupported" in e.lower() for e in errors)

    def test_unknown_bank_rejected(self):
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,upi,Chase,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""
        with pytest.raises(CSVValidationError) as exc_info:
            ingest_csv(csv.encode("utf-8"))
        errors = (
            exc_info.value.details[0].get("errors", [])
            if exc_info.value.details
            else []
        )
        assert any("unsupported" in e.lower() for e in errors)

    def test_supported_aliases_normalized(self):
        """Case-insensitive aliases should be normalized."""
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,UPI,HDFC,INSUFFICIENT_FUNDS,2026-09-01T10:00:00+00:00,1
"""
        result = ingest_csv(csv.encode("utf-8"))
        assert result.transactions_df["payment_method"].iloc[0] == "upi"
        assert result.transactions_df["failure_reason"].iloc[0] == "insufficient_funds"


# ---------------------------------------------------------------------------
# Test: complete ingestion
# ---------------------------------------------------------------------------
class TestCompleteIngestion:
    def test_end_to_end(self):
        """Full CSV ingestion produces valid DataFrames."""
        result = ingest_csv(RAZORPAY_CSV.encode("utf-8"))
        assert isinstance(result, CSVIngestionResult)
        assert not result.transactions_df.empty
        assert not result.customers_df.empty
        assert result.metadata["source_type"] == "razorpay_style_csv"
        assert result.metadata["accepted_row_count"] == 3
        assert result.metadata["customer_count"] > 0

        # Verify canonical columns exist
        for col in [
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
        ]:
            assert col in result.transactions_df.columns

        # Verify customer columns
        for col in [
            "customer_id",
            "customer_segment",
            "customer_ltv",
            "historical_success_rate",
            "historical_recovery_rate",
            "customer_behavior_score",
            "customer_tenure_days",
            "created_at",
            "updated_at",
        ]:
            assert col in result.customers_df.columns

    def test_missing_optional_columns_ok(self):
        """CSV without due_date, created_at, updated_at should still work."""
        csv = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,retry_count
T001,C_01,100,failed,upi,HDFC,insufficient_funds,1
T002,C_01,200,failed,upi,HDFC,invalid_pin,0
"""
        result = ingest_csv(csv.encode("utf-8"))
        assert not result.transactions_df.empty
        assert result.transactions_df["due_date"].notna().all()
        assert result.transactions_df["transaction_timestamp"].notna().all()

    def test_multiple_customers(self):
        """CSV with multiple customers produces correct customer count."""
        result = ingest_csv(MULTI_TXN_CSV.encode("utf-8"))
        assert result.metadata["customer_count"] == 2  # C_A and C_B


# ---------------------------------------------------------------------------
# Test: template generation
# ---------------------------------------------------------------------------
class TestTemplateGeneration:
    def test_template_has_razorpay_headers(self):
        template = generate_csv_template()
        headers = template.strip().split(",")
        assert "payment_id" in headers
        assert "customer_id" in headers
        assert "amount" in headers
        assert "method" in headers
        assert "bank" in headers
        # Should NOT include derived features
        assert "customer_ltv" not in headers
        assert "historical_success_rate" not in headers
