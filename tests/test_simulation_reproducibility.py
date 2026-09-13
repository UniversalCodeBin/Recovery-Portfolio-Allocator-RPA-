"""Regression tests for deterministic per-transaction Monte-Carlo simulation.

Verifies that for a given (transaction_id, batch_seed), the Monte-Carlo
outcome realization is deterministic and independent of:
  - strategy
  - action execution order
  - plan ordering
  - number of previous random draws
  - number of executions before that transaction
"""

from __future__ import annotations

import pytest

from rpa.config import default_resource_limits
from rpa.loading import load_actions, load_customers, load_transactions
from rpa.orchestrator import RPABatchOrchestrator


@pytest.fixture(scope="module")
def transactions():
    return load_transactions("demo")


@pytest.fixture(scope="module")
def customers():
    return load_customers()


@pytest.fixture(scope="module")
def actions():
    return load_actions()


@pytest.fixture(scope="module")
def limits():
    return default_resource_limits()


@pytest.fixture(scope="module")
def batch_42(transactions, customers, actions, limits):
    """Run all 4 strategies with seed 42."""
    orch = RPABatchOrchestrator()
    return orch.run_batch(
        transactions=transactions,
        actions=actions,
        customers=customers,
        resource_limits=limits,
        batch_seed=42,
        strategies=["no_action", "rule_based", "ev_greedy", "rpa_optimizer"],
    )


@pytest.fixture(scope="module")
def batch_42_rerun(transactions, customers, actions, limits):
    """Run all 4 strategies with seed 42 again (reproducibility check)."""
    orch = RPABatchOrchestrator()
    return orch.run_batch(
        transactions=transactions,
        actions=actions,
        customers=customers,
        resource_limits=limits,
        batch_seed=42,
        strategies=["no_action", "rule_based", "ev_greedy", "rpa_optimizer"],
    )


@pytest.fixture(scope="module")
def batch_43(transactions, customers, actions, limits):
    """Run all 4 strategies with seed 43."""
    orch = RPABatchOrchestrator()
    return orch.run_batch(
        transactions=transactions,
        actions=actions,
        customers=customers,
        resource_limits=limits,
        batch_seed=43,
        strategies=["no_action", "rule_based", "ev_greedy", "rpa_optimizer"],
    )


def _outcome_map(result, strategy: str) -> dict[str, dict]:
    """Map transaction_id → {status, action_type, p_predicted}."""
    frame = result.executions[strategy].to_frame()
    return {
        row["transaction_id"]: {
            "status": row["status"],
            "action_type": row["action_type"],
            "p_predicted": row["p_predicted"],
        }
        for _, row in frame.iterrows()
    }


class TestDeterministicPerTransaction:
    """Same (txn_id, seed) → same outcome regardless of strategy."""

    def test_same_action_same_outcome_across_strategies(self, batch_42):
        """For every transaction where the same action is assigned, the
        Monte-Carlo outcome (success/fail) must be identical across strategies."""
        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        outcomes = {s: _outcome_map(batch_42, s) for s in strategies}

        # Collect all transaction IDs present in at least 2 strategies
        all_txns = set()
        for s in strategies:
            all_txns.update(outcomes[s].keys())

        same_action_diff_outcome = 0
        for txn in all_txns:
            # Get actions assigned by each strategy
            strat_actions = {}
            for s in strategies:
                if txn in outcomes[s]:
                    strat_actions[s] = outcomes[s][txn]

            # Find strategies that assign the same action to this txn
            action_groups: dict[str, list[dict]] = {}
            for s, info in strat_actions.items():
                action_groups.setdefault(info["action_type"], []).append(info)

            # Within each action group, all statuses must be identical
            for action_type, infos in action_groups.items():
                statuses = {i["status"] for i in infos}
                if len(statuses) > 1:
                    same_action_diff_outcome += 1

        assert same_action_diff_outcome == 0, (
            f"Found {same_action_diff_outcome} transactions where same action "
            f"produced different outcomes across strategies"
        )

    def test_same_action_same_fraction_across_strategies(self, batch_42):
        """For successful transactions with the same action, the recovered
        amount must be identical across strategies (same partial fraction)."""
        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        recovered = {}
        for s in strategies:
            frame = batch_42.executions[s].to_frame()
            recovered[s] = {
                row["transaction_id"]: row["recovered_amount"]
                for _, row in frame.iterrows()
                if row["status"] == "successful"
            }

        all_txns = set()
        for s in strategies:
            all_txns.update(recovered[s].keys())

        for txn in all_txns:
            vals = [recovered[s].get(txn) for s in strategies if txn in recovered[s]]
            if len(vals) > 1:
                assert len(set(vals)) == 1, (
                    f"Transaction {txn} has different recovered amounts: "
                    f"{dict(zip([s for s in strategies if txn in recovered[s]], vals))}"
                )


class TestSeedReproducibility:
    """Same seed → identical results across repeated runs."""

    def test_seed_42_reproducible(self, batch_42, batch_42_rerun):
        """Running seed 42 twice must produce identical execution outcomes."""
        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        for s in strategies:
            f1 = batch_42.executions[s].to_frame()
            f2 = batch_42_rerun.executions[s].to_frame()
            assert len(f1) == len(f2), f"{s}: different row count"
            for _, row1 in f1.iterrows():
                row2 = f2[f2["transaction_id"] == row1["transaction_id"]].iloc[0]
                assert row1["status"] == row2["status"], (
                    f"{s}/{row1['transaction_id']}: seed 42 not reproducible "
                    f"({row1['status']} vs {row2['status']})"
                )
                assert row1["recovered_amount"] == row2["recovered_amount"], (
                    f"{s}/{row1['transaction_id']}: recovered_amount differs"
                )

    def test_seed_42_same_transaction_ids(self, batch_42, batch_42_rerun):
        """Transaction IDs must be identical between two seed-42 runs."""
        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        for s in strategies:
            ids1 = batch_42.executions[s].to_frame()["transaction_id"].tolist()
            ids2 = batch_42_rerun.executions[s].to_frame()["transaction_id"].tolist()
            assert ids1 == ids2, f"{s}: transaction order differs between runs"


class TestDifferentSeeds:
    """Different seeds may produce different results."""

    def test_seed_43_differs_from_42(self, batch_42, batch_43):
        """Seed 43 should produce different outcomes than seed 42 for at
        least some transactions (statistical test)."""
        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        for s in strategies:
            f42 = batch_42.executions[s].to_frame()
            f43 = batch_43.executions[s].to_frame()
            # At least one transaction should have different status
            merged = f42.merge(
                f43[["transaction_id", "status"]],
                on="transaction_id",
                suffixes=("_42", "_43"),
            )
            diff = (merged["status_42"] != merged["status_43"]).sum()
            assert diff > 0, (
                f"Strategy {s}: seed 43 produced identical outcomes to seed 42 "
                f"(expected at least 1 difference)"
            )


class TestExecutionOrderIndependence:
    """Results must not depend on strategy execution order."""

    def test_order_independence(self, transactions, customers, actions, limits):
        """Run strategies in two different orders; results must be identical."""
        # Order 1: default
        orch1 = RPABatchOrchestrator()
        r1 = orch1.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=42,
            strategies=["rpa_optimizer", "ev_greedy", "rule_based", "no_action"],
        )

        # Order 2: reversed
        orch2 = RPABatchOrchestrator()
        r2 = orch2.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=42,
            strategies=["no_action", "rule_based", "ev_greedy", "rpa_optimizer"],
        )

        strategies = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]
        for s in strategies:
            f1 = r1.executions[s].to_frame()
            f2 = r2.executions[s].to_frame()
            assert len(f1) == len(f2), f"{s}: different row count"
            for _, row1 in f1.iterrows():
                row2 = f2[f2["transaction_id"] == row1["transaction_id"]].iloc[0]
                assert row1["status"] == row2["status"], (
                    f"{s}/{row1['transaction_id']}: execution order affected outcome "
                    f"({row1['status']} vs {row2['status']})"
                )
