"""Step 1 data-foundation tests.

Covers the 13 acceptance tests mandated for Step 1 plus an optional PostgreSQL
round-trip test (skipped automatically when no database is reachable).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from data_core.cleaning import CleaningPipeline
from data_core.generator import SyntheticDataGenerator
from data_core.splitting import (
    assert_no_leakage,
    split_transactions,
)
from data_core.validation import validate


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dataset():
    return SyntheticDataGenerator(42).generate(n_customers=60, target_total=600)


@pytest.fixture(scope="module")
def frames(dataset):
    return dataset.to_frames()


@pytest.fixture(scope="module")
def cleaned(frames):
    return CleaningPipeline().clean(frames).frames


@pytest.fixture(scope="module")
def validation(cleaned):
    return validate(cleaned)


# ---------------------------------------------------------------------------
# 1. Same seed produces same synthetic data
# ---------------------------------------------------------------------------
def test_synthetic_same_seed_identical():
    a = SyntheticDataGenerator(42).generate(n_customers=40, target_total=400)
    b = SyntheticDataGenerator(42).generate(n_customers=40, target_total=400)
    assert a.counts() == b.counts()
    # Deep equality on the first transaction of each entity list.
    for ea, eb in zip(a.transactions[:5], b.transactions[:5]):
        assert ea.to_dict() == eb.to_dict()
    for ca, cb in zip(a.customers[:5], b.customers[:5]):
        assert ca.to_dict() == cb.to_dict()
    assert a.recovery_actions == b.recovery_actions


# ---------------------------------------------------------------------------
# 2. Duplicate transactions are detected
# ---------------------------------------------------------------------------
def test_duplicate_transactions_detected(frames):
    cp = CleaningPipeline()
    tx = frames["transactions"]
    dup = pd.concat([tx, tx.iloc[[0]]], ignore_index=True)
    dup_frames = dict(frames)
    dup_frames["transactions"] = dup
    res = cp.clean(dup_frames)
    assert res.report.by_entity["transactions"].duplicate_count >= 1
    # cleaned must contain exactly len(tx) rows (dup removed).
    assert len(res.frames["transactions"]) == len(tx)


# ---------------------------------------------------------------------------
# 3. Invalid transaction amounts are rejected
# ---------------------------------------------------------------------------
def test_invalid_transaction_amounts_rejected(frames):
    cp = CleaningPipeline()
    tx = frames["transactions"].copy()
    bad = tx.iloc[[0]].copy()
    bad.loc[:, "amount"] = -5.0
    bad = pd.concat([tx, bad], ignore_index=True)
    df = dict(frames)
    df["transactions"] = bad
    cleaned = cp.clean(df).frames["transactions"]
    assert (cleaned["amount"] > 0).all()
    assert len(cleaned) == len(tx)


# ---------------------------------------------------------------------------
# 4. Invalid retry counts are rejected
# ---------------------------------------------------------------------------
def test_invalid_retry_counts_rejected(frames):
    cp = CleaningPipeline()
    tx = frames["transactions"].copy()
    bad = tx.iloc[[0]].copy()
    bad.loc[:, "retry_count"] = -3
    bad = pd.concat([tx, bad], ignore_index=True)
    df = dict(frames)
    df["transactions"] = bad
    cleaned = cp.clean(df).frames["transactions"]
    assert (cleaned["retry_count"] >= 0).all()
    assert len(cleaned) == len(tx)


# ---------------------------------------------------------------------------
# 5. Invalid recovery amounts are rejected
# ---------------------------------------------------------------------------
def test_invalid_recovery_amounts_rejected(frames, cleaned):
    ao = cleaned["action_outcomes"].copy()
    tx_amounts = cleaned["transactions"].set_index("transaction_id")["amount"]
    # Set a recovered amount larger than the transaction amount (impossible).
    idx = 0
    tid = ao.iloc[idx]["transaction_id"]
    ao.loc[idx, "recovered_amount"] = float(tx_amounts[tid] + 5000.0)
    df = dict(cleaned)
    df["action_outcomes"] = ao
    res = validate(df)
    assert res.n_rejected >= 1
    # And a negative recovered amount is a domain violation too.
    ao2 = cleaned["action_outcomes"].copy()
    ao2.loc[0, "recovered_amount"] = -1.0
    df2 = dict(cleaned)
    df2["action_outcomes"] = ao2
    res2 = validate(df2)
    assert res2.n_rejected >= 1


# ---------------------------------------------------------------------------
# 6. Invalid categorical values are rejected
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("column", ["payment_method", "bank", "failure_reason", "transaction_status"])
def test_invalid_categorical_values_rejected(frames, column):
    cp = CleaningPipeline()
    tx = frames["transactions"].copy()
    bad = tx.iloc[[0]].copy()
    bad.loc[:, column] = "definitely_not_a_valid_value"
    bad = pd.concat([tx, bad], ignore_index=True)
    df = dict(frames)
    df["transactions"] = bad
    cleaned = cp.clean(df).frames["transactions"]
    assert "definitely_not_a_valid_value" not in cleaned[column].astype(object).tolist()
    assert len(cleaned) == len(tx)


# ---------------------------------------------------------------------------
# 7. Missing required fields are rejected
# ---------------------------------------------------------------------------
def test_missing_required_fields_rejected(frames):
    cp = CleaningPipeline()
    tx = frames["transactions"].copy()
    bad = tx.iloc[[0]].copy()
    bad.loc[:, "amount"] = np.nan
    bad = pd.concat([tx, bad], ignore_index=True)
    df = dict(frames)
    df["transactions"] = bad
    cleaned = cp.clean(df).frames["transactions"]
    assert len(cleaned) == len(tx)


# ---------------------------------------------------------------------------
# 8. Foreign-key relationships are valid
# ---------------------------------------------------------------------------
def test_foreign_key_relationships_valid(cleaned):
    # Clean dataset: no FK violations.
    assert validate(cleaned).valid
    # Inject an outcome pointing at a non-existent transaction.
    ao = cleaned["action_outcomes"].copy()
    ao.loc[0, "transaction_id"] = "txn_DOES_NOT_EXIST"
    df = dict(cleaned)
    df["action_outcomes"] = ao
    res = validate(df)
    assert res.n_rejected >= 1
    assert any(f.table == "action_outcomes" and f.field == "transaction_id" for f in res.failures)


# ---------------------------------------------------------------------------
# 9. Date inconsistencies are detected
# ---------------------------------------------------------------------------
def test_date_inconsistencies_detected(cleaned):
    # updated_at before created_at -> rejected by cleaning.
    tx = cleaned["transactions"].copy()
    bad = tx.iloc[[0]].copy()
    bad.loc[:, "updated_at"] = pd.Timestamp("2000-01-01", tz="UTC")
    bad.loc[:, "created_at"] = pd.Timestamp("2026-01-01", tz="UTC")
    bad = pd.concat([tx, bad], ignore_index=True)
    df = dict(cleaned)
    df["transactions"] = bad
    cleaned_tx = CleaningPipeline().clean(df).frames["transactions"]
    assert len(cleaned_tx) == len(tx)  # bad row rejected

    # transaction_timestamp after due_date -> rejected (CHECK).
    bad2 = tx.iloc[[0]].copy()
    bad2.loc[:, "transaction_timestamp"] = pd.Timestamp("2026-12-31", tz="UTC")
    bad2.loc[:, "due_date"] = pd.Timestamp("2026-01-01", tz="UTC")
    bad2 = pd.concat([tx, bad2], ignore_index=True)
    df2 = dict(cleaned)
    df2["transactions"] = bad2
    cleaned_tx2 = CleaningPipeline().clean(df2).frames["transactions"]
    assert len(cleaned_tx2) == len(tx)


# ---------------------------------------------------------------------------
# 10. Clean valid records pass validation
# ---------------------------------------------------------------------------
def test_clean_valid_records_pass_validation(cleaned):
    res = validate(cleaned)
    assert res.valid
    assert res.n_rejected == 0
    assert res.n_accepted == sum(len(f) for f in cleaned.values())


# ---------------------------------------------------------------------------
# 11. Cleaning does not unexpectedly modify valid records
# ---------------------------------------------------------------------------
def test_cleaning_does_not_modify_valid_records(frames):
    cp = CleaningPipeline()
    res = cp.clean(frames)
    # No rejections, no duplicates, no transformations on fully-valid data.
    assert res.report.total_rejected == 0
    assert res.report.total_duplicates == 0
    assert all(not r.transformations for r in res.report.by_entity.values())
    # Amounts preserved exactly.
    raw_tx = frames["transactions"]
    cleaned_tx = res.frames["transactions"]
    assert len(cleaned_tx) == len(raw_tx)
    assert np.allclose(
        raw_tx["amount"].to_numpy(dtype=float),
        cleaned_tx["amount"].astype(float).to_numpy(),
    )


# ---------------------------------------------------------------------------
# 12. Dataset splitting is reproducible
# ---------------------------------------------------------------------------
def test_splitting_reproducible(frames):
    cust_df = frames["customers"]
    tx_df = frames["transactions"]
    s1 = split_transactions(tx_df, cust_df, seed=123)
    s2 = split_transactions(tx_df, cust_df, seed=123)
    for name in s1:
        assert list(s1[name]["transaction_id"]) == list(s2[name]["transaction_id"])
    # Different seed -> different partition.
    s3 = split_transactions(tx_df, cust_df, seed=999)
    assert list(s1["train"]["transaction_id"]) != list(s3["train"]["transaction_id"])


def test_make_assignment_disjoint_and_complete(cleaned):
    cust_df = cleaned["customers"]
    tx_df = cleaned["transactions"]
    splits = split_transactions(tx_df, cust_df)
    assert sum(len(v) for v in splits.values()) == len(tx_df)
    assert_no_leakage(splits)


# ---------------------------------------------------------------------------
# 13. No train/test leakage is introduced by the split logic
# ---------------------------------------------------------------------------
def test_no_train_test_leakage(cleaned):
    cust_df = cleaned["customers"]
    tx_df = cleaned["transactions"]
    splits = split_transactions(tx_df, cust_df, seed=123)
    assert_no_leakage(splits)  # raises if a customer/txn spans splits

    customer_to_splits: dict = {}
    for name, df in splits.items():
        for cid in df["customer_id"].unique():
            customer_to_splits.setdefault(cid, set()).add(name)
    leaking_customers = [c for c, s in customer_to_splits.items() if len(s) > 1]
    assert not leaking_customers

    # Demo split must be disjoint from train/val/test.
    demo_txns = set(splits["demo"]["transaction_id"])
    train_val_test = set()
    for n in ("train", "val", "test"):
        train_val_test |= set(splits[n]["transaction_id"])
    assert demo_txns.isdisjoint(train_val_test)
    # No transaction_id overlap between demo and modelling splits.
    assert not (demo_txns & train_val_test)


# ---------------------------------------------------------------------------
# Schema sanity (no database required)
# ---------------------------------------------------------------------------
def test_schema_covers_all_entities():
    from data_core.schema import SCHEMA_SQL
    entities = [
        "customers", "transactions", "recovery_actions", "action_outcomes",
        "recovery_predictions", "resource_constraints", "recovery_decisions",
        "audit_logs",
    ]
    for e in entities:
        assert f"CREATE TABLE {e}" in SCHEMA_SQL, f"schema missing table {e}"
        assert f"{e}_id" in SCHEMA_SQL or "PRIMARY KEY" in SCHEMA_SQL
    # Foreign keys wire the relational model together.
    assert "REFERENCES customers(customer_id)" in SCHEMA_SQL
    assert "REFERENCES transactions(transaction_id)" in SCHEMA_SQL
    assert "REFERENCES recovery_actions(action_id)" in SCHEMA_SQL


def test_outcome_before_transaction_is_rejected(cleaned):
    ao = cleaned["action_outcomes"].copy()
    # Force an outcome attempted 5 days BEFORE the originating transaction.
    txn_ts = cleaned["transactions"].set_index("transaction_id")["transaction_timestamp"]
    tid = ao.iloc[0]["transaction_id"]
    ts = pd.to_datetime(txn_ts[tid], utc=True)
    ao.loc[0, "attempted_at"] = (ts - pd.Timedelta(days=5)).isoformat()
    df = dict(cleaned)
    df["action_outcomes"] = ao
    res = validate(df)
    assert res.n_rejected >= 1
    assert any(f.table == "action_outcomes" and "before transaction" in f.message for f in res.failures)


# ---------------------------------------------------------------------------
# Optional: PostgreSQL round-trip (skipped without a reachable database)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pg_conn():
    if not os.environ.get("RPA_DB_HOST"):
        pytest.skip("PostgreSQL not configured (set RPA_DB_* env vars).")
    try:
        from data_core.db import connect
        return connect()
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable: {exc}")


def test_pg_round_trip_if_available(cleaned, pg_conn):
    from data_core.db import Database

    db = Database(schema=os.environ.get("RPA_DB_SCHEMA", "rpa"))
    db.create_schema(pg_conn, reset=True)
    counts = db.load_dataset(pg_conn, cleaned, reset=True)
    assert db.row_counts(pg_conn)["customers"] == counts["customers"]
    assert db.row_counts(pg_conn)["transactions"] == counts["transactions"]
    # FK enforced at the DB level: every outcome references an existing txn.
    schema = os.environ.get("RPA_DB_SCHEMA", "rpa")
    n = pg_conn.execute(
        f"SELECT COUNT(*) FROM {schema}.action_outcomes ao "
        f"JOIN {schema}.transactions t ON t.transaction_id = ao.transaction_id"
    ).fetchone()[0]
    assert n == counts["action_outcomes"]
    pg_conn.close()
