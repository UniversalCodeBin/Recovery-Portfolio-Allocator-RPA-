"""Step 3 FastAPI endpoint tests (MVP backend for Step 4 frontend).

Exercises every endpoint with realistic requests and asserts the failure
modes (400 unknown strategy, 404 unknown batch/split). All execution endpoints
are verified to be SIMULATION-ONLY (``simulation`` flag set on responses).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rpa.api import app
from rpa.loading import load_actions, load_transactions
from rpa.strategies import STRATEGY_NAMES


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("rpa.orchestrator.RUNS_DIR", tmp_path)
    monkeypatch.setattr("rpa.config.RUNS_DIR", tmp_path)
    return TestClient(app)


@pytest.fixture(scope="module")
def demo():
    return load_transactions("demo")


@pytest.fixture(scope="module")
def actions():
    return load_actions()


def _subset_ids(demo, n=6):
    return demo.head(n)["transaction_id"].tolist()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "rpa-backend"
    assert body["simulation_only"] is True


def test_versions(client):
    r = client.get("/versions")
    assert r.status_code == 200
    body = r.json()
    for key in ("model", "policy", "optimizer", "ev_engine", "simulator", "verification"):
        assert key in body
        assert body[key]


def test_model_metadata(client):
    r = client.get("/model/metadata")
    assert r.status_code == 200
    body = r.json()
    assert body["model_identifier"] == "rpa-recovery-logreg-full-v1"
    assert body["n_features"] > 0
    assert body["feature_count"] == body["n_features"]
    assert body["precomputed_predictions_available"] is True


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------
def test_run_batch(client, demo):
    ids = _subset_ids(demo)
    r = client.post("/recovery/batch", json={"split": "demo", "batch_seed": 0,
                                             "transaction_ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"].startswith("batch_")
    strategies = body["summary"]["strategy_metrics"]
    assert set(strategies) == {"no_action", "ev_greedy", "rpa_optimizer"}
    for name, metrics in strategies.items():
        assert metrics["total_expected_net_ev"] >= 0
        assert metrics["all_verified"] is True
        assert metrics["simulation"] is True


def test_run_batch_bad_split(client):
    r = client.post("/recovery/batch", json={"split": "nope"})
    assert r.status_code == 404


def test_run_batch_all_strategies(client, demo):
    ids = _subset_ids(demo)
    r = client.post("/recovery/batch", json={"split": "demo", "strategies": list(STRATEGY_NAMES),
                                             "transaction_ids": ids})
    assert r.status_code == 200
    assert set(r.json()["summary"]["strategy_metrics"]) == set(STRATEGY_NAMES)


def test_preview(client, demo, actions):
    ids = _subset_ids(demo)
    r = client.post("/recovery/preview", json={"split": "demo", "transaction_ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert body["n_transactions"] == len(ids)
    assert body["n_actions"] == len(actions)
    assert len(body["rows"]) == len(ids) * len(actions)
    assert len(body["verdicts"]) == len(ids) * len(actions)
    assert all(v["decision"] in ("ALLOW", "BLOCK") for v in body["verdicts"])


def test_run_strategy_ev_greedy(client, demo):
    r = client.post("/recovery/strategy/ev_greedy", json={"split": "demo", "batch_seed": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"] == "ev_greedy"
    assert body["simulation"] is True
    n_txn = len(demo)
    assert len(body["plan"]) == n_txn
    assert len(body["execution"]) == n_txn
    assert body["verification"]["n_planned"] == n_txn
    assert body["verification"]["all_verified"] is True


def test_run_strategy_rule_based(client):
    r = client.post("/recovery/strategy/rule_based", json={"split": "demo"})
    assert r.status_code == 200
    assert r.json()["strategy"] == "rule_based"


def test_run_strategy_unknown_returns_400(client):
    r = client.post("/recovery/strategy/not_a_strategy", json={"split": "demo"})
    assert r.status_code == 400


def test_compare_fair_comparison(client, demo):
    ids = _subset_ids(demo)
    r = client.post("/recovery/compare", json={"split": "demo", "batch_seed": 2,
                                               "transaction_ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"] is True
    assert set(body["strategies"]) == set(STRATEGY_NAMES)
    # Fairness: identical batch_seed and identical n_transactions across all.
    n = {m["n_transactions"] for m in body["strategies"].values()}
    assert n == {len(ids)}


def test_execute_simulation_only(client, demo):
    r = client.post("/recovery/execute", json={"split": "demo", "strategy": "rpa_optimizer",
                                               "batch_seed": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"] is True
    assert body["batch_metrics"]["simulation"] is True
    assert body["batch_metrics"]["n_transactions"] == len(demo)
    assert len(body["executions"]) == len(demo)


def test_execute_unknown_strategy_returns_400(client):
    r = client.post("/recovery/execute", json={"split": "demo", "strategy": "nope"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Read endpoints (use a batch created in-test)
# ---------------------------------------------------------------------------
def test_plan_metrics_audit_roundtrip(client, demo):
    ids = _subset_ids(demo)
    created = client.post("/recovery/batch", json={"split": "demo", "transaction_ids": ids,
                                                   "strategies": ["no_action", "rpa_optimizer"]})
    assert created.status_code == 200
    batch_id = created.json()["batch_id"]

    plan = client.get(f"/recovery/plan/{batch_id}")
    assert plan.status_code == 200
    assert set(plan.json()["plans"]) == {"no_action", "rpa_optimizer"}
    assert len(plan.json()["plans"]["rpa_optimizer"]) == len(ids)

    metrics = client.get(f"/recovery/metrics/{batch_id}")
    assert metrics.status_code == 200
    assert metrics.json()["status"] == "completed"
    assert {"no_action", "rpa_optimizer"} <= set(metrics.json()["verifications"])

    audit = client.get(f"/recovery/audit/{batch_id}")
    assert audit.status_code == 200
    events = audit.json()
    assert isinstance(events, list)
    comps = {e["component"] for e in events}
    assert {"batch", "ev", "policy", "optimizer", "execution", "verification"} <= comps
    # Every event references the batch.
    assert all(e["batch_id"] == batch_id for e in events)


def test_unknown_batch_returns_404(client):
    assert client.get("/recovery/plan/batch_does_not_exist").status_code == 404
    assert client.get("/recovery/metrics/batch_does_not_exist").status_code == 404
    assert client.get("/recovery/audit/batch_does_not_exist").status_code == 404
    assert client.get("/recovery/batch/batch_does_not_exist").status_code == 404
    assert client.get("/recovery/explain/batch_does_not_exist/txn_1").status_code == 404


def test_cors_headers(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_get_actions(client):
    r = client.get("/recovery/actions")
    assert r.status_code == 200
    data = r.json()
    assert "actions" in data
    assert len(data["actions"]) >= 5
    assert "default_resource_limits" in data
    assert "available_splits" in data
    assert "demo" in data["available_splits"]


def test_get_batch_and_explanation(client, demo):
    ids = _subset_ids(demo, n=4)
    created = client.post(
        "/recovery/batch",
        json={"split": "demo", "transaction_ids": ids, "strategies": ["rpa_optimizer"]},
    )
    assert created.status_code == 200
    batch_id = created.json()["batch_id"]

    # 1. Full batch retrieval
    batch_res = client.get(f"/recovery/batch/{batch_id}")
    assert batch_res.status_code == 200
    b_data = batch_res.json()
    assert b_data["batch_id"] == batch_id
    assert "plans" in b_data
    assert "verifications" in b_data
    assert "ev_table" in b_data
    assert "verdicts" in b_data

    # 2. Batches list
    batches_res = client.get("/recovery/batches")
    assert batches_res.status_code == 200
    b_list = batches_res.json()
    assert any(b["batch_id"] == batch_id for b in b_list)

    # 3. Decision explanation for a transaction in the batch
    first_txn = ids[0]
    exp_res = client.get(f"/recovery/explain/{batch_id}/{first_txn}?strategy=rpa_optimizer")
    assert exp_res.status_code == 200
    exp = exp_res.json()
    assert exp["transaction_id"] == first_txn
    assert exp["batch_id"] == batch_id
    assert exp["decision"] is not None
    assert exp["prediction"] is not None
    assert exp["ev"] is not None
    assert exp["policy"] is not None
    assert exp["execution"] is not None
    assert exp["verification"] is not None

    # Unknown strategy returns 400
    bad_strat = client.get(f"/recovery/explain/{batch_id}/{first_txn}?strategy=invalid_strat")
    assert bad_strat.status_code == 400