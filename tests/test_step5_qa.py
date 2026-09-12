"""Regression coverage for Step 5 boundary and policy-safety fixes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from rpa.api import BatchRequest
from rpa.ev_engine import EVEngine
from rpa.execution_simulator import ExecutionSimulator
from rpa.loading import ActionSpec
from rpa.optimizer import PortfolioPlan
from rpa.policy_engine import PolicyVerdict
from rpa.strategies import StrategyRunner


def test_execution_requires_transaction_specific_policy_approval():
    no_op = ActionSpec("noop", "no_intervention", 0.0, {})
    retry = ActionSpec("retry", "retry", 1.0, {"retry": 1.0})
    txns = pd.DataFrame({"transaction_id": ["a", "b"], "amount": [100.0, 100.0]})
    plan = PortfolioPlan(["a", "b"], [retry, retry], [1.0, 1.0], 2.0, {}, {}, "test")
    verdicts = [
        PolicyVerdict("a", "retry", "ALLOW"),
        PolicyVerdict("b", "retry", "BLOCK"),
        PolicyVerdict("a", "noop", "ALLOW"),
        PolicyVerdict("b", "noop", "ALLOW"),
    ]
    result = ExecutionSimulator().execute(
        plan, txns, np.ones((2, 2)), [no_op, retry], verdicts, 7
    )
    assert result.executions[0]["status"] in {"successful", "failed"}
    assert result.executions[1]["status"] == "blocked"
    assert result.executions[1]["attempted"] == 0


def test_rule_based_respects_shared_resource_capacity():
    no_op = ActionSpec("noop", "no_intervention", 0.0, {})
    retry = ActionSpec("retry", "retry", 1.0, {"retry": 1.0})
    actions = [no_op, retry]
    txns = pd.DataFrame(
        {
            "transaction_id": ["a", "b"],
            "amount": [100.0, 100.0],
            "days_overdue": [0, 0],
            "retry_count": [0, 0],
            "historical_success_rate": [0.0, 0.0],
        }
    )
    ev = EVEngine().compute(txns, np.array([[0.0, 1.0], [0.0, 1.0]]), actions)
    verdicts = [
        PolicyVerdict(t, a.action_id, "ALLOW", action_type=a.action_type)
        for t in txns.transaction_id
        for a in actions
    ]
    plan = StrategyRunner().rule_based(
        ev, txns, ["a", "b"], actions, {"retry": 1.0}, verdicts
    )
    assert [a.action_id for a in plan.actions].count("retry") == 1
    assert plan.resource_used["retry"] == 1.0


def test_api_rejects_invalid_resource_limits_and_duplicate_ids():
    for payload in (
        {"resource_limits": {"bogus": 1}},
        {"resource_limits": {"retry": -1}},
        {"transaction_ids": ["x", "x"]},
        {"strategies": ["not_a_strategy"]},
    ):
        with pytest.raises(ValidationError):
            BatchRequest.model_validate(payload)
