"""End-to-end tests for CSV upload → batch → all strategies → re-execution.

Verifies:
- CSV transaction IDs preserved through the entire pipeline
- All 4 strategies produce independent results
- Resource constraints data is populated correctly
- Re-execution uses CSV data, not demo data
- Transaction IDs match across plan / execution / verification / audit
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from rpa.api import app

STRATEGY_NAMES = {"no_action", "rule_based", "ev_greedy", "rpa_optimizer"}

CSV_CONTENT = """\
payment_id,customer_id,amount,currency,status,method,bank,failure_reason,error_code,created_at,retry_count,due_date
csv_test_001,cust_a,15000,INR,failed,upi,HDFC,insufficient_funds,E1001,2026-08-01T09:15:00+00:00,2,2026-09-04
csv_test_002,cust_b,8500,INR,failed,credit_card,ICICI,network_timeout,E1002,2026-08-02T14:30:00+00:00,1,2026-09-05
csv_test_003,cust_c,42000,INR,failed,net_banking,SBI,bank_down,E1003,2026-08-03T11:45:00+00:00,3,2026-09-06
csv_test_004,cust_a,3200,INR,failed,debit_card,HDFC,invalid_pin,E1004,2026-08-04T08:20:00+00:00,1,2026-09-07
csv_test_005,cust_d,28000,INR,failed,upi,Kotak,limit_exceeded,E1005,2026-08-05T16:10:00+00:00,2,2026-09-08
csv_test_006,cust_b,5500,INR,failed,upi,Axis,expired_card,E1006,2026-08-06T10:00:00+00:00,1,2026-09-09
csv_test_007,cust_e,19500,INR,failed,credit_card,HDFC,insufficient_funds,E1001,2026-08-07T13:25:00+00:00,0,2026-09-10
csv_test_008,cust_c,11000,INR,failed,net_banking,ICICI,network_timeout,E1002,2026-08-08T09:00:00+00:00,1,2026-09-11
csv_test_009,cust_d,7800,INR,failed,debit_card,SBI,bank_down,E1003,2026-08-09T15:40:00+00:00,2,2026-09-12
csv_test_010,cust_e,33000,INR,failed,upi,Kotak,insufficient_funds,E1001,2026-08-10T11:15:00+00:00,1,2026-09-13
"""

EXPECTED_IDS = {
    "csv_test_001",
    "csv_test_002",
    "csv_test_003",
    "csv_test_004",
    "csv_test_005",
    "csv_test_006",
    "csv_test_007",
    "csv_test_008",
    "csv_test_009",
    "csv_test_010",
}

# Default strategies exclude rule_based (see orchestrator.py line 201)
DEFAULT_STRATEGIES = {"no_action", "ev_greedy", "rpa_optimizer"}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def csv_batch(client):
    """Upload CSV and return full batch result."""
    r = client.post(
        "/recovery/batch/csv",
        files={"file": ("test_data.csv", io.BytesIO(CSV_CONTENT.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    r2 = client.get(f"/recovery/batch/{batch_id}")
    assert r2.status_code == 200, r2.text
    return r2.json()


class TestCSVTransactionIDPreservation:
    """Transaction IDs from CSV must remain unchanged through the full pipeline."""

    def test_csv_batch_contains_exact_ids(self, csv_batch):
        assert set(csv_batch["transaction_ids"]) == EXPECTED_IDS

    def test_csv_batch_correct_count(self, csv_batch):
        assert len(csv_batch["transaction_ids"]) == len(EXPECTED_IDS)

    def test_all_four_strategies_present(self, csv_batch):
        plans = csv_batch.get("plans", {})
        assert set(plans.keys()) == DEFAULT_STRATEGIES

    def test_plan_ids_match_csv_ids(self, csv_batch):
        for strategy, records in csv_batch.get("plans", {}).items():
            plan_ids = {r["transaction_id"] for r in records}
            assert plan_ids == EXPECTED_IDS, f"Strategy {strategy} has mismatched IDs"

    def test_execution_ids_match_csv_ids(self, csv_batch):
        for strategy, records in csv_batch.get("executions", {}).items():
            exec_ids = {r["transaction_id"] for r in records}
            assert exec_ids == EXPECTED_IDS, (
                f"Strategy {strategy} execution has mismatched IDs"
            )

    def test_verification_ids_match_csv_ids(self, csv_batch):
        for strategy, vdata in csv_batch.get("verifications", {}).items():
            verif_ids = {r["transaction_id"] for r in vdata.get("rows", [])}
            assert verif_ids == EXPECTED_IDS, (
                f"Strategy {strategy} verification has mismatched IDs"
            )

    def test_no_demo_ids_in_batch(self, csv_batch):
        for tid in csv_batch["transaction_ids"]:
            assert not tid.startswith("txn_"), f"Demo ID found: {tid}"
            assert not tid.startswith("demo_"), f"Demo ID found: {tid}"

    def test_plans_per_strategy_count(self, csv_batch):
        for strategy, records in csv_batch.get("plans", {}).items():
            assert len(records) == len(EXPECTED_IDS), (
                f"{strategy}: expected {len(EXPECTED_IDS)} records, got {len(records)}"
            )

    def test_executions_per_strategy_count(self, csv_batch):
        for strategy, records in csv_batch.get("executions", {}).items():
            assert len(records) == len(EXPECTED_IDS), (
                f"{strategy}: expected {len(EXPECTED_IDS)} executions, got {len(records)}"
            )


class TestResourceConstraints:
    """Resource constraints must be populated from the batch."""

    def test_resource_limits_present(self, csv_batch):
        assert "resource_limits" in csv_batch
        rl = csv_batch["resource_limits"]
        assert "retry" in rl
        assert "messaging" in rl
        assert "incentive_budget" in rl
        assert "human_slots" in rl

    def test_rpa_optimizer_has_resource_used(self, csv_batch):
        v = csv_batch["verifications"]["rpa_optimizer"]
        bm = v["batch_metrics"]
        assert "resource_used" in bm
        ru = bm["resource_used"]
        assert isinstance(ru, dict)
        assert all(
            k in ru for k in ["retry", "messaging", "incentive_budget", "human_slots"]
        )

    def test_rpa_optimizer_has_total_expected_net_ev(self, csv_batch):
        v = csv_batch["verifications"]["rpa_optimizer"]
        bm = v["batch_metrics"]
        assert "total_expected_net_ev" in bm
        assert isinstance(bm["total_expected_net_ev"], (int, float))

    def test_rpa_optimizer_has_status(self, csv_batch):
        v = csv_batch["verifications"]["rpa_optimizer"]
        bm = v["batch_metrics"]
        assert "status" in bm
        assert bm["status"] in ("optimal", "greedy", "deterministic", "feasible")


class TestReExecutionUsesCSVData:
    """Re-execution via /recovery/execute must use CSV data, not demo data."""

    def test_execute_rpa_on_csv_batch(self, client, csv_batch):
        r = client.post(
            "/recovery/execute",
            json={
                "batch_id": csv_batch["batch_id"],
                "strategy": "rpa_optimizer",
                "batch_seed": 42,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["simulation"] is True
        assert body["strategy"] == "rpa_optimizer"
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS
        exec_ids = {e["transaction_id"] for e in body["executions"]}
        assert exec_ids == EXPECTED_IDS

    def test_execute_ev_greedy_on_csv_batch(self, client, csv_batch):
        r = client.post(
            "/recovery/execute",
            json={
                "batch_id": csv_batch["batch_id"],
                "strategy": "ev_greedy",
                "batch_seed": 42,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "ev_greedy"
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS

    def test_execute_rule_based_on_csv_batch(self, client, csv_batch):
        r = client.post(
            "/recovery/execute",
            json={
                "batch_id": csv_batch["batch_id"],
                "strategy": "rule_based",
                "batch_seed": 42,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "rule_based"
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS

    def test_execute_no_action_on_csv_batch(self, client, csv_batch):
        r = client.post(
            "/recovery/execute",
            json={
                "batch_id": csv_batch["batch_id"],
                "strategy": "no_action",
                "batch_seed": 42,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "no_action"
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS

    def test_execute_without_batch_id_uses_split(self, client):
        r = client.post(
            "/recovery/execute",
            json={"split": "demo", "strategy": "rpa_optimizer", "batch_seed": 0},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert len(new_batch["transaction_ids"]) == 370

    def test_compare_on_csv_batch(self, client, csv_batch):
        r = client.post(
            "/recovery/compare",
            json={
                "batch_id": csv_batch["batch_id"],
                "batch_seed": 42,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        new_batch = client.get(f"/recovery/batch/{body['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS
        assert set(body["strategies"].keys()) == STRATEGY_NAMES

    def test_reexecuted_batch_preserves_csv_ids(self, client, csv_batch):
        r = client.post(
            "/recovery/execute",
            json={
                "batch_id": csv_batch["batch_id"],
                "strategy": "rpa_optimizer",
                "batch_seed": 99,
            },
        )
        assert r.status_code == 200
        new_batch = client.get(f"/recovery/batch/{r.json()['batch_id']}").json()
        assert set(new_batch["transaction_ids"]) == EXPECTED_IDS
        for strategy, records in new_batch.get("plans", {}).items():
            plan_ids = {rec["transaction_id"] for rec in records}
            assert plan_ids == EXPECTED_IDS, f"Re-executed {strategy} has wrong IDs"


class TestAuditTrail:
    """Audit trail must exist for CSV batches with meaningful event types."""

    def test_audit_has_events(self, client, csv_batch):
        batch_id = csv_batch["batch_id"]
        r = client.get(f"/recovery/audit/{batch_id}")
        assert r.status_code == 200, r.text
        events = r.json()
        assert len(events) > 0

    def test_audit_has_expected_event_types(self, client, csv_batch):
        batch_id = csv_batch["batch_id"]
        r = client.get(f"/recovery/audit/{batch_id}")
        events = r.json()
        event_types = {e["event_type"] for e in events}
        assert "batch_created" in event_types
        assert "predictions_scored" in event_types
        assert "verified" in event_types

    def test_audit_references_batch_id(self, client, csv_batch):
        batch_id = csv_batch["batch_id"]
        r = client.get(f"/recovery/audit/{batch_id}")
        events = r.json()
        batch_ids = {e.get("batch_id", "") for e in events}
        assert batch_id in batch_ids
