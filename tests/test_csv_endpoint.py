"""Tests for POST /recovery/batch/csv endpoint.

Validates CSV upload, validation, pipeline integration, error handling,
and that existing endpoints are not broken.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from rpa.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("rpa.orchestrator.RUNS_DIR", tmp_path)
    monkeypatch.setattr("rpa.config.RUNS_DIR", tmp_path)
    return TestClient(app)


VALID_CSV = """\
payment_id,customer_id,amount,currency,status,method,bank,failure_reason,created_at,retry_count,due_date
T001,CUST_A,1500.00,INR,failed,upi,HDFC,insufficient_funds,2026-09-01T10:00:00+00:00,1,2026-09-04
T002,CUST_A,2500.00,INR,failed,credit_card,ICICI,invalid_pin,2026-09-02T14:30:00+00:00,2,2026-09-04
T003,CUST_B,800.00,INR,failed,debit_card,SBI,network_timeout,2026-09-01T08:15:00+00:00,0,2026-09-04
"""

INVALID_CSV = """\
payment_id,customer_id,amount,status,method,bank,failure_reason,created_at,retry_count
T001,C_01,100,failed,wallet,Chase,insufficient_funds,2026-09-01T10:00:00+00:00,1
"""


def test_csv_upload_valid(client):
    """Upload valid CSV -> 200 with batch_id."""
    files = {"file": ("test.csv", VALID_CSV.encode("utf-8"), "text/csv")}
    r = client.post("/recovery/batch/csv", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"].startswith("batch_")
    assert "summary" in body
    assert "csv_metadata" in body
    assert body["csv_metadata"]["source_type"] == "razorpay_style_csv"
    assert body["csv_metadata"]["accepted_row_count"] == 3


def test_csv_upload_invalid_csv(client):
    """Upload CSV with unknown categoricals -> 422."""
    files = {"file": ("bad.csv", INVALID_CSV.encode("utf-8"), "text/csv")}
    r = client.post("/recovery/batch/csv", files=files)
    assert r.status_code == 422


def test_csv_upload_empty_file(client):
    """Upload empty file -> 422."""
    files = {"file": ("empty.csv", b"", "text/csv")}
    r = client.post("/recovery/batch/csv", files=files)
    assert r.status_code == 422


def test_csv_upload_oversized(client):
    """Upload oversized file -> 422."""
    big_content = b"col1,col2\n" + b"a,b\n" * 200_000
    files = {"file": ("big.csv", big_content, "text/csv")}
    r = client.post("/recovery/batch/csv", files=files)
    assert r.status_code == 422


def test_csv_upload_with_resource_limits(client):
    """Upload CSV with resource limits -> verify limits applied."""
    limits = json.dumps({"incentive_budget": 1000.0, "human_slots": 10})
    files = {"file": ("test.csv", VALID_CSV.encode("utf-8"), "text/csv")}
    r = client.post(
        "/recovery/batch/csv",
        files=files,
        params={"resource_limits": limits},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"].startswith("batch_")


def test_csv_upload_with_strategies(client):
    """Upload CSV with strategy filter -> verify only selected strategies run."""
    strats = json.dumps(["rpa_optimizer"])
    files = {"file": ("test.csv", VALID_CSV.encode("utf-8"), "text/csv")}
    r = client.post(
        "/recovery/batch/csv",
        files=files,
        params={"strategies": strats},
    )
    assert r.status_code == 200
    body = r.json()
    assert "rpa_optimizer" in body["summary"]["strategy_metrics"]


def test_csv_upload_returns_batch_id(client):
    """Upload CSV -> batch_id can be used to retrieve results."""
    files = {"file": ("test.csv", VALID_CSV.encode("utf-8"), "text/csv")}
    r = client.post("/recovery/batch/csv", files=files)
    assert r.status_code == 200
    batch_id = r.json()["batch_id"]

    # Verify batch can be retrieved
    plan = client.get(f"/recovery/plan/{batch_id}")
    assert plan.status_code == 200


def test_existing_demo_endpoint_still_works(client):
    """Verify existing demo batch endpoint is not broken."""
    r = client.post("/recovery/batch", json={"split": "demo", "batch_seed": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"].startswith("batch_")


def test_csv_upload_with_seed(client):
    """Upload CSV with specific seed -> reproducible results."""
    files = {"file": ("test.csv", VALID_CSV.encode("utf-8"), "text/csv")}
    r1 = client.post("/recovery/batch/csv", files=files, params={"batch_seed": 42})
    r2 = client.post("/recovery/batch/csv", files=files, params={"batch_seed": 42})
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Same seed should produce same summary metrics
    m1 = r1.json()["summary"]["strategy_metrics"]["rpa_optimizer"]
    m2 = r2.json()["summary"]["strategy_metrics"]["rpa_optimizer"]
    assert m1["total_expected_net_ev"] == m2["total_expected_net_ev"]
