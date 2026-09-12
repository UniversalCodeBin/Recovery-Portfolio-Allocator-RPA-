"""Step 3 backend tests (Recovery Portfolio Allocator decision layer).

Covers the deterministic core that Step 4 (frontend) and the evaluator rely on:

* prediction service (frozen model live scoring — never retrains)
* expected-value math (explicit, auditable formula)
* policy engine hard gates (allow/block, budgets, limits)
* resource-state accounting
* ILP optimizer (one action per txn, shared caps, no-op feasibility)
* EV-per-resource greedy baseline
* strategy parity (identical inputs across all strategies)
* no-bypass-of-policy (blocked actions never reach execution)
* seeded execution simulator + verification reconciliation
* audit trail + explain_selection
* full batch orchestration (end-to-end, fail-closed, reproducible)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rpa.config import (
    POLICY_VERSION,
    PolicyConfig,
    default_resource_limits,
)
from rpa.ev_engine import INCENTIVE_RESOURCE_KEY, EVEngine
from rpa.execution_simulator import BLOCKED, FAILED, SUCCESSFUL, ExecutionSimulator
from rpa.loading import (
    ActionSpec,
    load_actions,
    load_customers,
    load_predictions_csv,
    load_transactions,
    predictions_matrix,
)
from rpa.optimizer import Optimizer, PortfolioPlan, ev_per_resource_greedy
from rpa.orchestrator import RPABatchOrchestrator, run_batch_on_split
from rpa.policy_engine import PolicyEngine, ResourceState
from rpa.prediction_service import PredictionService
from rpa.strategies import STRATEGY_NAMES, StrategyRunner
from rpa.verification import VerificationLayer


# ---------------------------------------------------------------------------
# Shared fixtures (isolated runs dir; real Step 1/2 data artifacts)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def runs_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("rpa_runs")


@pytest.fixture(autouse=True)
def isolated_runs(runs_tmp, monkeypatch):
    monkeypatch.setattr("rpa.orchestrator.RUNS_DIR", runs_tmp)
    monkeypatch.setattr("rpa.config.RUNS_DIR", runs_tmp)
    return runs_tmp


@pytest.fixture(scope="module")
def actions():
    return load_actions()


@pytest.fixture(scope="module")
def customers():
    return load_customers()


@pytest.fixture(scope="module")
def demo():
    return load_transactions("demo")


def _action_by_type(actions, action_type):
    return next(a for a in actions if a.action_type == action_type)


def _txns(amounts, retry_counts=None, n=12, seed=0):
    """Minimal transaction frame with the columns Step 3 components consume."""
    rng = np.random.default_rng(seed)
    n = max(len(amounts), n)
    return pd.DataFrame(
        {
            "transaction_id": [f"txn_{i:04d}" for i in range(n)],
            "customer_id": [f"cust_{i:04d}" for i in range(n)],
            "amount": [float(amounts[i % len(amounts)]) for i in range(n)],
            "currency": ["INR"] * n,
            "retry_count": [
                int((retry_counts or [0])[i % len(retry_counts or [0])])
                for i in range(n)
            ],
            "days_overdue": [int(rng.integers(0, 60)) for _ in range(n)],
            "historical_success_rate": [float(rng.random()) for _ in range(n)],
        }
    )


def _prob_matrix(n_txn, n_act, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(rng.random((n_txn, n_act)), 0.001, 0.99)


# ---------------------------------------------------------------------------
# 1. EV engine
# ---------------------------------------------------------------------------
def test_ev_formula_reconciles(actions):
    engine = EVEngine()
    incentive = _action_by_type(actions, "incentive")
    row = engine.compute_row("t1", 1000.0, incentive, 0.5)
    assert row.recoverable_amount == pytest.approx(1000.0)
    assert row.gross_expected == pytest.approx(500.0)
    assert row.action_cost == pytest.approx(incentive.action_cost)
    assert row.incentive_cost == pytest.approx(
        incentive.resource_units(INCENTIVE_RESOURCE_KEY)
        * engine.config.incentive_handling_fee
    )
    assert row.total_cost == pytest.approx(row.action_cost + row.incentive_cost)
    assert row.net_expected == pytest.approx(row.gross_expected - row.total_cost)


def test_ev_no_op_has_no_cost(actions):
    engine = EVEngine()
    no_op = _action_by_type(actions, "no_intervention")
    row = engine.compute_row("t1", 2000.0, no_op, 0.5)
    assert row.is_no_op
    assert row.action_cost == 0.0
    assert row.incentive_cost == 0.0
    assert row.net_expected == pytest.approx(1000.0)


def test_ev_probability_clipped(actions):
    engine = EVEngine()
    no_op = _action_by_type(actions, "no_intervention")
    row = engine.compute_row("t1", 100.0, no_op, 1e-12)
    assert row.p_recovery == pytest.approx(engine.config.prob_floor)


def test_ev_table_matrix_shape(actions):
    n = 8
    txns = _txns([1000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions))
    table = EVEngine().compute(txns, probs, actions)
    assert table.net_ev_matrix.shape == (n, len(actions))
    assert table.probability_matrix.shape == (n, len(actions))
    assert table.n_transactions == n
    assert table.n_actions == len(actions)


def test_ev_shape_mismatch_rejected(actions):
    with pytest.raises(ValueError):
        EVEngine().compute(_txns([100.0], n=4), np.zeros((3, 6)), actions)


# ---------------------------------------------------------------------------
# 2. Policy engine hard gates
# ---------------------------------------------------------------------------
def test_policy_allows_clean_candidate(actions):
    no_op = _action_by_type(actions, "no_intervention")
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    v = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=no_op,
        net_ev=10.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "ALLOW"
    assert v.rule == "ok"


def test_policy_blocks_disabled_action(actions):
    banned = ActionSpec(
        action_id="act_disabled",
        action_type="retry",
        action_cost=1.0,
        resource_requirements={"retry": 1.0},
        enabled=False,
    )
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    v = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=banned,
        net_ev=50.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "BLOCK"
    assert v.rule == "action_disabled"


def test_policy_blocks_listed_action(actions):
    cfg = PolicyConfig(blocked_actions=["act_incentive"])
    retry_act = _action_by_type(actions, "retry")
    rs = PolicyEngine(cfg).initial_resource_state(default_resource_limits())
    v = PolicyEngine(cfg).evaluate_one(
        transaction_id="t1",
        action=retry_act,
        net_ev=50.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "ALLOW"
    inc = _action_by_type(actions, "incentive")
    v2 = PolicyEngine(cfg).evaluate_one(
        transaction_id="t1",
        action=inc,
        net_ev=50.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v2.decision == "BLOCK"
    assert v2.rule == "action_blocked"


def test_policy_retry_limit(actions):
    retry_act = _action_by_type(actions, "retry")
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    v = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=retry_act,
        net_ev=50.0,
        retry_count=2,
        resource_state=rs,  # max_retries_per_transaction = 2
    )
    assert v.decision == "BLOCK"
    assert v.rule == "retry_limit"


def test_policy_min_net_ev_threshold(actions):
    inc = _action_by_type(actions, "incentive")
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    v = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=inc,
        net_ev=-10.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "BLOCK"
    assert v.rule == "min_net_ev"
    # No-op is never blocked by EV threshold.
    no_op = _action_by_type(actions, "no_intervention")
    v2 = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=no_op,
        net_ev=-5.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v2.decision == "ALLOW"


def test_policy_max_incentive_per_txn(actions):
    cfg = PolicyConfig(max_incentive_per_transaction=10.0)
    inc = _action_by_type(actions, "incentive")  # consumes 50 units
    rs = PolicyEngine(cfg).initial_resource_state(default_resource_limits())
    v = PolicyEngine(cfg).evaluate_one(
        transaction_id="t1",
        action=inc,
        net_ev=50.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "BLOCK"
    assert v.rule == "max_incentive_per_txn"


def test_policy_resource_exhausted_gate(actions):
    human = _action_by_type(actions, "human_escalation")
    rs = ResourceState(remaining={"human_slots": 0.0})
    v = PolicyEngine().evaluate_one(
        transaction_id="t1",
        action=human,
        net_ev=500.0,
        retry_count=0,
        resource_state=rs,
    )
    assert v.decision == "BLOCK"
    assert v.rule == "resource_exhausted"


def test_policy_screen_covers_every_pair(actions):
    n = 5
    txns = _txns([5000.0] * n, retry_counts=[0], n=n)
    probs = _prob_matrix(n, len(actions))
    table = EVEngine().compute(txns, probs, actions)
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    verdicts = PolicyEngine().screen(table, txns, rs)
    assert len(verdicts) == n * len(actions)
    assert {v.decision for v in verdicts} <= {"ALLOW", "BLOCK"}
    assert all(v.policy_id == POLICY_VERSION for v in verdicts)


def test_resource_state_accounting(actions):
    inc = _action_by_type(actions, "incentive")
    rs = ResourceState(remaining={"incentive_budget": 50.0, "messaging": 1.0})
    assert rs.can_consume(inc)
    rs.consume(inc)
    assert rs.remaining["incentive_budget"] == pytest.approx(0.0)
    assert rs.remaining["messaging"] == pytest.approx(0.0)
    assert not rs.can_consume(inc)


# ---------------------------------------------------------------------------
# 3. Optimizer (one action per txn, shared caps, feasibility)
# ---------------------------------------------------------------------------
def test_optimizer_one_action_per_txn(actions):
    n = 10
    txns = _txns([1000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions))
    table = EVEngine().compute(txns, probs, actions)
    plan = Optimizer().solve(
        table.net_ev_matrix,
        actions,
        txns["transaction_id"].tolist(),
        default_resource_limits(),
    )
    assert plan.status == "optimal"
    assert len(plan.transaction_ids) == n
    assert len(plan.actions) == n
    assert len(plan.net_ev_per_txn) == n


def test_optimizer_respects_shared_caps(actions):
    n = 40
    txns = _txns([20000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=3)
    table = EVEngine().compute(txns, probs, actions)
    caps = {
        "incentive_budget": 500.0,
        "human_slots": 4.0,
        "messaging": 30.0,
        "retry": 30.0,
    }
    plan = Optimizer().solve(
        table.net_ev_matrix, actions, txns["transaction_id"].tolist(), caps
    )
    assert plan.status == "optimal"
    for key, cap in caps.items():
        assert plan.resource_used[key] <= cap + 1e-9, (key, plan.resource_used)


def test_optimizer_no_op_guarantees_feasibility(actions):
    n = 8
    txns = _txns([100.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=5)
    table = EVEngine().compute(txns, probs, actions)
    # Tight caps: no intervention can be afforded for everyone.
    caps = {"incentive_budget": 0.0, "human_slots": 0.0, "messaging": 0.0, "retry": 0.0}
    plan = Optimizer().solve(
        table.net_ev_matrix, actions, txns["transaction_id"].tolist(), caps
    )
    assert all(a.action_type == "no_intervention" for a in plan.actions)
    assert plan.total_net_ev == pytest.approx(float(table.net_ev_matrix[:, 0].sum()))


def test_optimizer_unconstrained_picks_argmax(actions):
    n = 8
    txns = _txns([5000.0] * n, n=n)
    rng = np.random.default_rng(9)
    probs = np.clip(rng.random((n, len(actions))), 0.3, 0.9)
    table = EVEngine().compute(txns, probs, actions)
    caps = {"incentive_budget": 1e9, "human_slots": 1e9, "messaging": 1e9, "retry": 1e9}
    plan = Optimizer().solve(
        table.net_ev_matrix, actions, txns["transaction_id"].tolist(), caps
    )
    per_txn_max = table.net_ev_matrix.max(axis=1).sum()
    assert plan.total_net_ev == pytest.approx(float(per_txn_max), abs=1e-6)


def test_optimizer_deterministic(actions):
    n = 10
    txns = _txns([5000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=11)
    table = EVEngine().compute(txns, probs, actions)
    txn_ids = txns["transaction_id"].tolist()
    p1 = Optimizer().solve(
        table.net_ev_matrix, actions, txn_ids, default_resource_limits()
    )
    p2 = Optimizer().solve(
        table.net_ev_matrix, actions, txn_ids, default_resource_limits()
    )
    assert [a.action_id for a in p1.actions] == [a.action_id for a in p2.actions]
    np.testing.assert_allclose(p1.net_ev_per_txn, p2.net_ev_per_txn)


def test_optimizer_no_bypass_of_masked_columns(actions):
    n = 10
    txns = _txns([5000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=13)
    table = EVEngine().compute(txns, probs, actions)
    mask = np.ones((n, len(actions)), dtype=bool)
    inc_idx = next(j for j, a in enumerate(actions) if a.action_type == "incentive")
    mask[:, inc_idx] = False
    masked = np.where(mask, table.net_ev_matrix, -1e6)
    plan = Optimizer().solve(
        masked, actions, txns["transaction_id"].tolist(), default_resource_limits()
    )
    assert all(a.action_type != "incentive" for a in plan.actions)


def test_greedy_respects_caps(actions):
    n = 40
    txns = _txns([20000.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=17)
    table = EVEngine().compute(txns, probs, actions)
    caps = {
        "incentive_budget": 400.0,
        "human_slots": 3.0,
        "messaging": 20.0,
        "retry": 20.0,
    }
    plan = ev_per_resource_greedy(
        table.net_ev_matrix, actions, txns["transaction_id"].tolist(), caps
    )
    assert len(plan.actions) == n
    for key, cap in caps.items():
        assert plan.resource_used[key] <= cap + 1e-9


# ---------------------------------------------------------------------------
# 4. Strategies: fairness parity + policy non-bypass
# ---------------------------------------------------------------------------
def test_strategy_names_and_parity(actions):
    n = 12
    txns = _txns([2500.0] * n, retry_counts=[0, 1, 2], n=n)
    probs = _prob_matrix(n, len(actions), seed=19)
    table = EVEngine().compute(txns, probs, actions)
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    verdicts = PolicyEngine().screen(table, txns, rs)
    runner = StrategyRunner()
    plans = runner.run_all(
        table,
        txns,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    assert set(plans.keys()) == set(STRATEGY_NAMES)
    for name, plan in plans.items():
        assert plan.transaction_ids == txns["transaction_id"].tolist(), name
        assert plan.name == name


def test_strategies_never_select_blocked_actions(actions):
    n = 20
    txns = _txns([20000.0] * n, retry_counts=[0], n=n)
    probs = _prob_matrix(n, len(actions), seed=23)
    table = EVEngine().compute(txns, probs, actions)
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    verdicts = PolicyEngine().screen(table, txns, rs)
    # Force-block incentive for every transaction.
    for v in verdicts:
        if v.action_id == "act_incentive":
            v.decision = "BLOCK"
            v.rule = "forced_for_test"
    runner = StrategyRunner()
    plans = runner.run_all(
        table,
        txns,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    for name, plan in plans.items():
        chosen_types = {a.action_type for a in plan.actions}
        assert "incentive" not in chosen_types, name


def test_rule_based_high_value_escalation(actions):
    n = 1
    txns = _txns([200000.0], retry_counts=[0], n=n)
    txns.at[0, "days_overdue"] = 60
    txns.at[0, "historical_success_rate"] = 0.1
    probs = np.full((1, len(actions)), 0.5)
    for j, a in enumerate(actions):
        if a.action_type != "human_escalation":
            probs[0, j] = 0.0
    table = EVEngine().compute(txns, probs, actions)
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    verdicts = PolicyEngine().screen(table, txns, rs)
    plan = StrategyRunner().rule_based(
        table,
        txns,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    assert plan.actions[0].action_type == "human_escalation"


# ---------------------------------------------------------------------------
# 5. Execution simulator (seeded, simulation-only, fail-closed)
# ---------------------------------------------------------------------------
@pytest.fixture()
def sim_context(actions):
    n = 10
    txns = _txns([2500.0] * n, n=n)
    probs = _prob_matrix(n, len(actions), seed=29)
    table = EVEngine().compute(txns, probs, actions)
    rs = PolicyEngine().initial_resource_state(default_resource_limits())
    verdicts = PolicyEngine().screen(table, txns, rs)
    return {"txns": txns, "probs": probs, "table": table, "verdicts": verdicts}


def test_execution_deterministic_by_seed(actions, sim_context):
    txns = sim_context["txns"]
    probs = sim_context["probs"]
    table = sim_context["table"]
    verdicts = sim_context["verdicts"]
    plan = StrategyRunner().rpa_optimizer(
        table,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    sim = ExecutionSimulator()
    e1 = sim.execute(plan, txns, probs, actions, verdicts, batch_seed=42)
    e2 = sim.execute(plan, txns, probs, actions, verdicts, batch_seed=42)
    assert [r["status"] for r in e1.executions] == [r["status"] for r in e2.executions]
    np.testing.assert_allclose(
        [r["net_recovered_amount"] for r in e1.executions],
        [r["net_recovered_amount"] for r in e2.executions],
    )
    assert e1.simulation is True


def test_execution_different_seeds_differ(actions, sim_context):
    txns = sim_context["txns"]
    probs = sim_context["probs"]
    table = sim_context["table"]
    verdicts = sim_context["verdicts"]
    plan = StrategyRunner().rpa_optimizer(
        table,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    sim = ExecutionSimulator()
    e1 = sim.execute(plan, txns, probs, actions, verdicts, batch_seed=1)
    e2 = sim.execute(plan, txns, probs, actions, verdicts, batch_seed=2)
    assert e1.net_recovered_total != e2.net_recovered_total
    assert e1.batch_metrics()["simulation"] is True


def test_execution_fail_closed_on_non_approved_action(actions, sim_context):
    txns = sim_context["txns"]
    probs = sim_context["probs"]
    verdicts = sim_context["verdicts"]
    no_op = _action_by_type(actions, "no_intervention")
    plan = PortfolioPlan(
        transaction_ids=txns["transaction_id"].tolist(),
        actions=[no_op] * len(txns),
        net_ev_per_txn=[0.0] * len(txns),
        total_net_ev=0.0,
        resource_used={},
        capacities={},
        name="no_action",
        status="deterministic",
    )
    # Force every verdict to BLOCK so the no-op action is NOT approved.
    for v in verdicts:
        v.decision = "BLOCK"
        v.rule = "forced"
    res = ExecutionSimulator().execute(
        plan, txns, probs, actions, verdicts, batch_seed=0
    )
    assert all(r["status"] == BLOCKED for r in res.executions)
    assert all(r["attempted"] == 0 for r in res.executions)


def test_execution_recovery_cost_formula(actions):
    inc = _action_by_type(actions, "incentive")
    sim = ExecutionSimulator()
    cost = sim._recovery_cost(inc)
    assert cost == pytest.approx(
        inc.action_cost + 50.0 * sim.ev_config.incentive_handling_fee
    )
    no_op = _action_by_type(actions, "no_intervention")
    assert sim._recovery_cost(no_op) == pytest.approx(0.0)


def test_execution_success_stays_within_recoverable(actions, sim_context):
    txns = sim_context["txns"]
    probs = sim_context["probs"]
    table = sim_context["table"]
    verdicts = sim_context["verdicts"]
    plan = StrategyRunner().rpa_optimizer(
        table,
        txns["transaction_id"].tolist(),
        actions,
        default_resource_limits(),
        verdicts,
    )
    res = ExecutionSimulator().execute(
        plan, txns, probs, actions, verdicts, batch_seed=7
    )
    amounts = txns.set_index("transaction_id")["amount"]
    for r in res.executions:
        if r["status"] == SUCCESSFUL:
            assert r["recovered_amount"] <= float(amounts[r["transaction_id"]]) + 1e-6
        assert r["status"] in (SUCCESSFUL, FAILED, BLOCKED)
        assert r["simulation"] is True


# ---------------------------------------------------------------------------
# 6. Verification reconciliation
# ---------------------------------------------------------------------------
def _fake_execution(txns, status="successful"):
    rows = [
        {
            "transaction_id": t,
            "action_id": "act_no_intervention",
            "action_type": "no_intervention",
            "plan_name": "no_action",
            "status": status,
            "attempted": 1 if status != "blocked" else 0,
            "recovered_amount": 10.0 if status == "successful" else 0.0,
            "recovery_cost": 0.0,
            "net_recovered_amount": 10.0 if status == "successful" else 0.0,
            "p_predicted": 0.5,
            "seed": 0,
            "simulation": True,
        }
        for t in txns
    ]
    from rpa.execution_simulator import ExecutionResult

    return ExecutionResult(
        executions=rows, plan_name="no_action", batch_seed=0, net_recovered_total=0.0
    )


def test_verification_passes_when_plan_matches(actions, sim_context):
    txns = sim_context["txns"]
    probs = sim_context["probs"]
    table = EVEngine().compute(txns, probs, actions)
    plan = StrategyRunner().no_action(
        table, txns["transaction_id"].tolist(), actions, default_resource_limits()
    )
    exec_ = _fake_execution(txns["transaction_id"].tolist(), status="successful")
    verif = VerificationLayer().verify(plan, exec_, actions)
    assert verif.passed
    assert verif.batch_metrics["all_verified"] is True
    assert verif.batch_metrics["n_executed"] == len(txns)


def test_verification_flags_mismatched_execution(actions):
    txns = _txns([1000.0], n=2)
    no_op = _action_by_type(actions, "no_intervention")
    from rpa.optimizer import PortfolioPlan

    plan = PortfolioPlan(
        transaction_ids=txns["transaction_id"].tolist(),
        actions=[no_op, no_op],
        net_ev_per_txn=[1.0, 1.0],
        total_net_ev=2.0,
        resource_used={},
        capacities={},
        name="no_action",
        status="deterministic",
    )
    # Execution returns a DIFFERENT action on the second txn.
    rows = _fake_execution(txns["transaction_id"].tolist()).executions
    rows[1]["action_id"] = "act_retry"
    rows[1]["action_type"] = "retry"
    from rpa.execution_simulator import ExecutionResult

    exec_ = ExecutionResult(
        executions=rows, plan_name="no_action", batch_seed=0, net_recovered_total=0.0
    )
    verif = VerificationLayer().verify(plan, exec_, actions)
    assert not verif.passed
    assert verif.rows[1]["verified"] is False
    assert "!= planned" in verif.rows[1]["verification_error"]


def test_verification_flags_missing_execution(actions):
    txns = _txns([1000.0], n=2)
    no_op = _action_by_type(actions, "no_intervention")
    from rpa.optimizer import PortfolioPlan

    plan = PortfolioPlan(
        transaction_ids=txns["transaction_id"].tolist(),
        actions=[no_op, no_op],
        net_ev_per_txn=[1.0, 1.0],
        total_net_ev=2.0,
        resource_used={},
        capacities={},
        name="no_action",
        status="deterministic",
    )
    rows = _fake_execution([txns["transaction_id"].tolist()[0]]).executions
    from rpa.execution_simulator import ExecutionResult

    exec_ = ExecutionResult(
        executions=rows, plan_name="no_action", batch_seed=0, net_recovered_total=0.0
    )
    verif = VerificationLayer().verify(plan, exec_, actions)
    assert not verif.passed
    assert verif.rows[1]["verification_error"] == "missing execution record"


# ---------------------------------------------------------------------------
# 7. Prediction service (frozen model, never re-trains)
# ---------------------------------------------------------------------------
def test_prediction_service_live_scores_subset(demo, customers, actions):
    subset = demo.head(4).reset_index(drop=True)
    service = PredictionService()
    result = service.score(subset, customers, actions)
    assert result.probabilities.shape == (4, len(actions))
    assert len(result.frame) == 4 * len(actions)
    assert (result.probabilities >= 0).all() and (result.probabilities <= 1).all()
    assert not np.isnan(result.probabilities).any()
    assert result.model_identifier == service.model_id or result.model_identifier
    assert "rpa-recovery-logreg" in result.model_identifier


def test_prediction_service_rejects_bad_input(actions, demo, customers):
    service = PredictionService()
    bad = demo.head(2).copy()
    bad.loc[0, "amount"] = np.nan
    with pytest.raises(ValueError):
        service.score(bad, customers, actions)


def test_predictions_matrix_alignment(demo, actions):
    preds = load_predictions_csv()
    mat = predictions_matrix(preds, demo.head(6).reset_index(drop=True), actions)
    assert mat.shape == (6, len(actions))
    # Matrix columns follow `actions` order; row 0 col 0 is no-op prob.
    assert mat[0, 0] == pytest.approx(
        preds[
            (preds["transaction_id"] == demo.iloc[0]["transaction_id"])
            & (preds["action_id"] == actions[0].action_id)
        ]["predicted_recovery_probability"].iloc[0]
    )


# ---------------------------------------------------------------------------
# 8. Audit trail
# ---------------------------------------------------------------------------
def test_audit_has_all_components(demo, customers, actions):
    subset = demo.head(6).reset_index(drop=True)
    probs = _prob_matrix(6, len(actions), seed=31)
    result = RPABatchOrchestrator().run_batch(
        transactions=subset,
        actions=actions,
        customers=customers,
        resource_limits=default_resource_limits(),
        batch_seed=5,
        predictions=probs,
    )
    assert result.status == "completed"
    comps = [e.component for e in result.audit.events]
    assert {"batch", "ev", "policy", "optimizer", "execution", "verification"} <= set(
        comps
    )
    # explain_selection narrative for the ILP decision.
    expl = result.audit.explain_selection(
        subset.iloc[0]["transaction_id"], "rpa_optimizer"
    )
    assert expl["transaction_id"] == subset.iloc[0]["transaction_id"]
    assert expl["policy"]["decision"] == "ALLOW"
    assert expl["decision"]["transaction_id"] == subset.iloc[0]["transaction_id"]
    assert expl["decision"]["action_id"]


def test_audit_records_prediction_when_live_scored(demo, customers, actions):
    txns = demo.head(2).reset_index(drop=True)
    pred = PredictionService().score(txns, customers, actions)
    from rpa.audit import AuditTrail

    trail = AuditTrail("batch_test")
    trail.record_predictions(pred)
    evs = [e for e in trail.events if e.component == "prediction"]
    assert len(evs) == 1
    assert evs[0].event_type == "predictions_scored"
    assert evs[0].event_metadata["model_identifier"] == pred.model_identifier


def test_audit_writes_valid_json(isolated_runs, actions):
    txns = _txns([1000.0], n=3)
    from rpa.audit import AuditTrail

    trail = AuditTrail("batch_write")
    for i in range(3):
        trail.record_ev(
            EVEngine().compute(txns, _prob_matrix(3, len(actions)), actions)
        )
    from rpa.policy_engine import PolicyVerdict

    trail.record_policy([PolicyVerdict("t", "a", "ALLOW")])
    out = Path(isolated_runs) / "batch_write"
    out.mkdir(parents=True, exist_ok=True)
    trail.write(out / "audit.json")
    import json

    data = json.loads((out / "audit.json").read_text())
    assert isinstance(data, list) and data


# ---------------------------------------------------------------------------
# 9. Orchestration end-to-end
# ---------------------------------------------------------------------------
def test_full_batch_on_demo_split_completes(demo, customers, actions, isolated_runs):
    subset = demo.head(15).reset_index(drop=True)
    preds = load_predictions_csv()
    probs = predictions_matrix(preds, subset, actions)
    orch = RPABatchOrchestrator()
    result = orch.run_batch(
        transactions=subset,
        actions=actions,
        customers=customers,
        resource_limits=default_resource_limits(),
        batch_seed=10,
        predictions=probs,
    )
    assert result.status == "completed"
    assert set(result.plans.keys()) == {"no_action", "ev_greedy", "rpa_optimizer"}
    for plan in result.plans.values():
        assert len(plan.actions) == 15
    for verif in result.verifications.values():
        assert verif.passed, verif.batch_metrics
    # Persisted to disk.
    d = Path(isolated_runs) / result.batch_id
    assert (d / "result.json").exists()
    assert (d / "audit.json").exists()


def test_fail_closed_on_bad_predictions(demo, customers, actions):
    subset = demo.head(10).reset_index(drop=True)
    bad_probs = np.zeros((3, 6))  # wrong n_transactions
    result = RPABatchOrchestrator().run_batch(
        transactions=subset,
        actions=actions,
        customers=customers,
        resource_limits=default_resource_limits(),
        batch_seed=1,
        predictions=bad_probs,
    )
    assert result.status == "error"
    assert result.error.startswith("ev_failed")
    assert result.plans == {}


def test_batch_reproducible(demo, customers, actions):
    subset = demo.head(12).reset_index(drop=True)
    probs = predictions_matrix(load_predictions_csv(), subset, actions)
    kw = {
        "transactions": subset,
        "actions": actions,
        "customers": customers,
        "resource_limits": default_resource_limits(),
        "batch_seed": 77,
        "predictions": probs,
    }
    r1 = RPABatchOrchestrator().run_batch(**kw)
    r2 = RPABatchOrchestrator().run_batch(**kw)
    for name in r1.plans:
        assert [a.action_id for a in r1.plans[name].actions] == [
            a.action_id for a in r2.plans[name].actions
        ]
        assert r1.plans[name].total_net_ev == pytest.approx(r2.plans[name].total_net_ev)
        assert r1.executions[name].net_recovered_total == pytest.approx(
            r2.executions[name].net_recovered_total
        )


def test_run_batch_on_split_helper(actions):
    result = run_batch_on_split("demo", batch_seed=3, strategies=["no_action"])
    assert result.status == "completed"
    assert set(result.plans.keys()) == {"no_action"}
