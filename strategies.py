"""The four allocation strategies.

All four strategies receive IDENTICAL inputs:
  - the same transaction batch
  - the same frozen P(recovery | txn, action) predictions
  - the same action set, costs and resource limits

Each returns a StrategyAllocation: one committed action per transaction plus
metadata (expected value, resource usage, violations).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from actions import (
    ResourceState,
    ResourceVector,
    action_cost,
    build_initial_resource_state,
    capacity_dict_from_scenario,
)
from config import (
    Action,
    Resource,
    RULE_HIGH_AMOUNT,
    RULE_MAX_RETRIES,
    RULE_MID_AMOUNT,
    RULE_OVERDUE_HIGH,
    RULE_OVERDUE_MID,
    RULE_SUCESS_THRESHOLD,
    RULE_SUCCESS_MIN,
    action_consumption,
)
from data_generation import Transaction
from expected_value import expected_net_recovery, expected_value_matrix, ev_ratio_matrix
from optimizer import solve_ilp

ACTIONS_LIST = [
    Action.NO_INTERVENTION,
    Action.RETRY,
    Action.PAYMENT_LINK,
    Action.CUSTOMER_MESSAGE,
    Action.INCENTIVE,
    Action.HUMAN_ESCALATION,
]
NO_ACTION_IDX = ACTIONS_LIST.index(Action.NO_INTERVENTION)


@dataclass
class StrategyAllocation:
    """Outcome of a single strategy run on one batch."""

    name: str
    actions: List[Action]                       # one per transaction
    action_indices: List[int]
    expected_values: List[float]                # EV of chosen action per txn
    resource_used: Dict[str, float]
    capacities: Dict[Resource, float]
    violations: List[str] = field(default_factory=list)
    solve_status: str = "deterministic"         # e.g. "optimal" for ILP

    def check_violations(self) -> List[str]:
        """Verify no resource constraint or one-action-per-transaction violated."""
        used = {r: 0.0 for r in ("retry", "messaging", "incentive", "human")}
        for action in self.actions:
            cons = action_consumption(action)
            used["retry"] += cons.retry
            used["messaging"] += cons.messaging
            used["incentive"] += cons.incentive
            used["human"] += cons.human
        seen = len(self.actions)
        if seen != len(self.actions):
            self.violations.append("one_action_per_transaction")
        for res, cap in self.capacities.items():
            key = res.value
            if res == Resource.RETRY:
                key = "retry"
            elif res == Resource.MESSAGING:
                key = "messaging"
            elif res == Resource.INCENTIVE_BUDGET:
                key = "incentive"
            elif res == Resource.HUMAN_SLOTS:
                key = "human"
            if used.get(key, 0.0) > cap + 1e-9:
                self.violations.append(f"capacity_exceeded:{res.value}")
        return self.violations


# ---------------------------------------------------------------------------
# Strategy 1: No intervention
# ---------------------------------------------------------------------------
def no_intervention_strategy(
    transactions: Sequence[Transaction],
    probabilities: Dict[Action, np.ndarray],
    capacity: Dict[Resource, float],
) -> StrategyAllocation:
    n = len(transactions)
    actions = [Action.NO_INTERVENTION] * n
    evs = [expected_net_recovery(
        float(t.amount),
        float(probabilities[Action.NO_INTERVENTION][i]),
        action_cost(Action.NO_INTERVENTION),
    ) for i, t in enumerate(transactions)]
    return StrategyAllocation(
        name="no_intervention",
        actions=actions,
        action_indices=[NO_ACTION_IDX] * n,
        expected_values=evs,
        resource_used={"retry": 0.0, "messaging": 0.0, "incentive": 0.0, "human": 0.0},
        capacities=dict(capacity),
        solve_status="deterministic",
    )


# ---------------------------------------------------------------------------
# Strategy 2: Fixed rule baseline (transparent, deterministic, documented)
# ---------------------------------------------------------------------------
def _rule_choice(
    t: Transaction,
    probabilities: Dict[Action, np.ndarray],
    res_state: ResourceState,
) -> Action:
    """Documented rule:
      1. Human escalation if value high & success-rate low & severely overdue
      2. Else incentive if value mid+ and overdue >= 7
      3. Else payment link if value mid+
      4. Else retry if retry_count < 2
      5. Else customer message if historical success-rate >= 0.6
      6. Else no intervention
    """
    amount = t.amount
    if (
        amount >= RULE_HIGH_AMOUNT
        and t.historical_success_rate <= RULE_SUCESS_THRESHOLD
        and t.days_overdue >= RULE_OVERDUE_HIGH
    ):
        return Action.HUMAN_ESCALATION
    if amount >= RULE_MID_AMOUNT and t.days_overdue >= RULE_OVERDUE_MID:
        return Action.INCENTIVE
    if amount >= RULE_MID_AMOUNT:
        return Action.PAYMENT_LINK
    if t.retry_count < RULE_MAX_RETRIES:
        return Action.RETRY
    if t.historical_success_rate >= RULE_SUCCESS_MIN:
        return Action.CUSTOMER_MESSAGE
    return Action.NO_INTERVENTION


def fixed_rule_strategy(
    transactions: Sequence[Transaction],
    probabilities: Dict[Action, np.ndarray],
    capacity: Dict[Resource, float],
) -> StrategyAllocation:
    """Deterministic rule policy, applied greedily under resource caps.

    Rule is documented in _rule_choice. If a chosen action exceeds available
    capacity, fall back to the next-best affordable action (then no-op).
    """
    res_state = build_initial_resource_state(capacity)
    actions: List[Action] = []
    evs: List[float] = []
    used = {"retry": 0.0, "messaging": 0.0, "incentive": 0.0, "human": 0.0}

    for i, t in enumerate(transactions):
        chosen = _rule_choice(t, probabilities, res_state)
        rv = _resource_vector(chosen)
        if not res_state.can_apply(rv):
            # fallback: first affordable action in preference order that is no-op
            chosen = Action.NO_INTERVENTION
            for fallback in ACTIONS_LIST:
                if fallback == Action.NO_INTERVENTION:
                    continue
                fb_rv = _resource_vector(fallback)
                if res_state.can_apply(fb_rv):
                    chosen = fallback
                    break
        rv = _resource_vector(chosen)
        res_state.apply(rv)
        for r in ("retry", "messaging", "incentive", "human"):
            used[r] += getattr(rv, r)
        actions.append(chosen)
        evs.append(expected_net_recovery(
            float(t.amount),
            float(probabilities[chosen][i]),
            action_cost(chosen),
        ))

    return StrategyAllocation(
        name="fixed_rule",
        actions=actions,
        action_indices=[ACTIONS_LIST.index(a) for a in actions],
        expected_values=evs,
        resource_used=used,
        capacities=dict(capacity),
        solve_status="deterministic",
    )


def _resource_vector(action: Action) -> ResourceVector:
    from actions import action_resource_vector
    return action_resource_vector(action)


# ---------------------------------------------------------------------------
# Strategy 3: EV-ratio greedy baseline (strong, not a strawman)
# ---------------------------------------------------------------------------
def ev_greedy_strategy(
    transactions: Sequence[Transaction],
    probabilities: Dict[Action, np.ndarray],
    capacity: Dict[Resource, float],
) -> StrategyAllocation:
    """Strong greedy baseline: capacity-rationed per-transaction EV maximization.

    Algorithm (documented, honest, NOT a strawman):
      1. For each transaction compute EV_i(a) for every action (incl. no-op).
      2. Compute marginal value MV_i = max_a EV_i(a) - EV_i(no-op) -- the
         value lost if the transaction receives no intervention. Transactions
         with larger MV lose more from inaction, so scarce capacity is
         rationed to them first (this is the "bang for buck" priority).
      3. Process transactions in descending MV order; give each its highest-EV
         action that fits in remaining capacity (falling back to the next-best
         feasible action, else no-intervention).

    Properties:
      - When NO constraint binds, every transaction receives its absolute
        best-EV action => identical to the unconstrained optimizer (ties with
        RPA). The greedy's weakness is only the *myopic ordering*: it commits
        to an action greedily and never re-optimizes globally.
      - It respects all resource capacities by construction.
    """
    res_state = build_initial_resource_state(capacity)
    n = len(transactions)
    actions_arr: List[Action] = [Action.NO_INTERVENTION] * n
    evs_arr: List[float] = [0.0] * n
    used = {"retry": 0.0, "messaging": 0.0, "incentive": 0.0, "human": 0.0}

    # EV per (txn, action).
    ev_mat = expected_value_matrix(
        [float(t.amount) for t in transactions],
        probabilities,
        ACTIONS_LIST,
    )

    no_op_col = NO_ACTION_IDX
    marginal = ev_mat[:, :] - ev_mat[:, no_op_col][:, None]
    # Ration by marginal value of best action vs no-op.
    order = np.argsort(-marginal.max(axis=1), kind="stable")

    for pos in order:
        i = int(pos)
        candidates = sorted(
            range(len(ACTIONS_LIST)),
            key=lambda j: -float(ev_mat[i, j]),
        )
        chosen = Action.NO_INTERVENTION
        chosen_idx = NO_ACTION_IDX
        for j in candidates:
            action = ACTIONS_LIST[j]
            rv = _resource_vector(action)
            if not res_state.can_apply(rv):
                continue
            res_state.apply(rv)
            for r in ("retry", "messaging", "incentive", "human"):
                used[r] += getattr(rv, r)
            chosen = action
            chosen_idx = j
            break

        actions_arr[i] = chosen
        evs_arr[i] = float(ev_mat[i, chosen_idx])

    return StrategyAllocation(
        name="ev_greedy",
        actions=actions_arr,
        action_indices=[ACTIONS_LIST.index(a) for a in actions_arr],
        expected_values=evs_arr,
        resource_used=used,
        capacities=dict(capacity),
        solve_status="greedy",
    )


# ---------------------------------------------------------------------------
# Strategy 4: RPA (constrained portfolio optimizer, exact ILP via CBC)
# ---------------------------------------------------------------------------
def rpa_strategy(
    transactions: Sequence[Transaction],
    probabilities: Dict[Action, np.ndarray],
    capacity: Dict[Resource, float],
    ev_matrix: Optional[np.ndarray] = None,
) -> StrategyAllocation:
    """Exact constrained portfolio allocation via OR-Tools CBC ILP.

    Objective: maximize sum of EV over (txn, action) with one-action-per-txn
    and all capacity constraints.
    """
    amounts = [float(t.amount) for t in transactions]
    if ev_matrix is None:
        ev_matrix = expected_value_matrix(amounts, probabilities, ACTIONS_LIST)

    cap_for_solver: Dict[str, Optional[float]] = {
        "retry": capacity.get(Resource.RETRY),
        "messaging": capacity.get(Resource.MESSAGING),
        "incentive": capacity.get(Resource.INCENTIVE_BUDGET),
        "human": capacity.get(Resource.HUMAN_SLOTS),
    }

    result = solve_ilp(ev_matrix, ACTIONS_LIST, cap_for_solver)

    actions = [ACTIONS_LIST[int(j)] for j in result.assignment]
    evs = [float(ev_matrix[i, int(result.assignment[i])]) for i in range(len(transactions))]
    used = {k: float(v) for k, v in result.resources_used.items()}

    return StrategyAllocation(
        name="rpa",
        actions=actions,
        action_indices=[int(j) for j in result.assignment],
        expected_values=evs,
        resource_used=used,
        capacities=dict(capacity),
        violations=[],
        solve_status="optimal" if result.optimal else f"status={result.status}",
    )


# ---------------------------------------------------------------------------
# Shared strategy runners (identical inputs)
# ---------------------------------------------------------------------------
def run_all_strategies(
    transactions: Sequence[Transaction],
    probabilities: Dict[Action, np.ndarray],
    capacity: Dict[Resource, float],
) -> Dict[str, StrategyAllocation]:
    """Run all four strategies on identical inputs, return {name: allocation}.

    This is the fair-comparison entry point used by the experiment.
    """
    return {
        "no_intervention": no_intervention_strategy(transactions, probabilities, capacity),
        "fixed_rule": fixed_rule_strategy(transactions, probabilities, capacity),
        "ev_greedy": ev_greedy_strategy(transactions, probabilities, capacity),
        "rpa": rpa_strategy(transactions, probabilities, capacity),
    }