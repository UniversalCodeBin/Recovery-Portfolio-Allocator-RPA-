"""Strategy Comparison Interface.

Provides a normalized recovery-plan interface over four strategies:

  * ``no_action``    — take no intervention on every transaction
  * ``rule_based``   — deterministic documented rule (fixed baseline)
  * ``ev_greedy``    — EV-per-resource greedy (strong baseline)
  * ``rpa_optimizer``— exact ILP portfolio optimizer (the differentiator)

Fairness contract: every strategy receives IDENTICAL inputs — the same
transaction batch, the same frozen predictions, the same action set, the same
resource limits, the same EV table and the same policy allow/block verdicts,
drawn with the same random seed where randomness plays a role.

Crucially, every strategy only ever SELECTS amongst *policy-ALLOWED* actions.
A blocked action reaches neither the optimizer nor execution. The no-op action
is always allowed, guaranteeing a feasible plan.

Each strategy returns a :class:`PortfolioPlan` with a normalized shape, so
strategies can be compared directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from rpa.ev_engine import EVTable
from rpa.loading import ActionSpec
from rpa.optimizer import Optimizer, PortfolioPlan, ev_per_resource_greedy
from rpa.policy_engine import PolicyVerdict

# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
STRATEGY_NAMES = ["no_action", "rule_based", "ev_greedy", "rpa_optimizer"]

RESOURCE_KEYS = ["retry", "messaging", "incentive_budget", "human_slots"]


class RuleBasedEngine:
    """Deterministic documented rule for the fixed baseline.

    Rule (per transaction, applied to allowed interventions):
      1. Human escalation if amount >= HIGH AND overdue >= OVERDUE_HIGH
         AND historical success-rate <= SUCCESS_THRESHOLD
      2. Else incentive if amount >= MID AND overdue >= OVERDUE_MID
      3. Else payment link if amount >= MID
      4. Else retry if retry_count < 2
      5. Else customer message if historical success-rate >= SUCCESS_MIN
      6. Else no action
    """

    HIGH_AMOUNT = 5000.0
    MID_AMOUNT = 1500.0
    OVERDUE_HIGH = 30
    OVERDUE_MID = 7
    SUCCESS_THRESHOLD = 0.4
    SUCCESS_MIN = 0.6
    MAX_RETRIES = 2

    def choose(self, row: Dict, allowed_types: List[str]) -> Optional[str]:
        """Return the preferred action TYPE if allowed, else None."""
        amount = float(row.get("amount", 0.0))
        overdue = int(row.get("days_overdue", 0))
        retries = int(row.get("retry_count", 0))
        success = float(row.get("historical_success_rate", 0.0))

        priority_types = []
        if (amount >= self.HIGH_AMOUNT and overdue >= self.OVERDUE_HIGH
                and success <= self.SUCCESS_THRESHOLD):
            priority_types.append("human_escalation")
        elif amount >= self.MID_AMOUNT and overdue >= self.OVERDUE_MID:
            priority_types.append("incentive")
        elif amount >= self.MID_AMOUNT:
            priority_types.append("payment_link")
        elif retries < self.MAX_RETRIES:
            priority_types.append("retry")
        elif success >= self.SUCCESS_MIN:
            priority_types.append("customer_message")

        for t in priority_types:
            if t in allowed_types:
                return t
        return None


def _action_by_type(actions: List[ActionSpec], action_type: str) -> Optional[ActionSpec]:
    for a in actions:
        if a.action_type == action_type:
            return a
    return None


def _action_by_id(actions: List[ActionSpec], action_id: str) -> Optional[ActionSpec]:
    for a in actions:
        if a.action_id == action_id:
            return a
    return None


class StrategyConfig:
    def __init__(
        self,
        no_op_action_id: str = "act_no_intervention",
        rule: Optional[RuleBasedEngine] = None,
        optimizer: Optional[Optimizer] = None,
    ) -> None:
        self.no_op_action_id = no_op_action_id
        self.rule = rule or RuleBasedEngine()
        self.optimizer = optimizer or Optimizer()


class StrategyRunner:
    """Runs each strategy over identical inputs -> {name: PortfolioPlan}."""

    def __init__(self, config: Optional[StrategyConfig] = None) -> None:
        self.config = config or StrategyConfig()

    # -- build allowed-action boolean matrix from policy verdicts ----------
    @staticmethod
    def _allowed_matrix(
        ev: EVTable,
        verdicts: List[PolicyVerdict],
        actions: List[ActionSpec],
    ) -> np.ndarray:
        allowed = np.zeros((ev.n_transactions, len(actions)), dtype=bool)
        action_idx = {a.action_id: j for j, a in enumerate(actions)}
        vmap = {(v.transaction_id, v.action_id): v for v in verdicts}
        for row in ev.rows:
            v = vmap.get((row.transaction_id, row.action_id))
            if v is not None and v.decision == "ALLOW":
                allowed[ev.row_index(row.transaction_id), action_idx[row.action_id]] = True
        return allowed

    # ------------------------------------------------------------------
    def no_action(
        self, ev: EVTable, transaction_ids: List[str], actions: List[ActionSpec],
        capacity: Dict[str, Optional[float]],
    ) -> PortfolioPlan:
        no_op = _action_by_type(actions, "no_intervention") \
            or _action_by_id(actions, self.config.no_op_action_id)
        if no_op is None:
            raise ValueError("no no-op action available")
        n = len(transaction_ids)
        idx = next(i for i, a in enumerate(actions) if a.action_id == no_op.action_id)
        net = [float(ev.net_ev_matrix[ev.row_index(t), idx]) for t in transaction_ids]
        return PortfolioPlan(
            transaction_ids=transaction_ids,
            actions=[no_op] * n,
            net_ev_per_txn=net,
            total_net_ev=float(sum(net)),
            resource_used={k: 0.0 for k in RESOURCE_KEYS},
            capacities=dict(capacity),
            name="no_action",
            status="deterministic",
        )

    # ------------------------------------------------------------------
    def rule_based(
        self, ev: EVTable, transactions, transaction_ids: List[str], actions: List[ActionSpec],
        capacity: Dict[str, Optional[float]], verdicts: List[PolicyVerdict],
    ) -> PortfolioPlan:
        allowed_types_per_txn: Dict[str, List[str]] = {t: [] for t in transaction_ids}
        for v in verdicts:
            if v.decision == "ALLOW":
                allowed_types_per_txn.setdefault(v.transaction_id, []).append(v.action_type)
        txn_rows = {r.get("transaction_id"): r for r in transactions.to_dict(orient="records")}
        used: Dict[str, float] = {k: 0.0 for k in RESOURCE_KEYS}
        remaining = {k: float(v) for k, v in capacity.items() if v is not None}

        def fits(action: ActionSpec) -> bool:
            return all(
                units <= remaining.get(key, float("inf")) + 1e-9
                for key, units in action.resource_requirements.items()
                if units and units > 0
            )

        def allowed_action(txn_id: str, action: Optional[ActionSpec]) -> bool:
            return action is not None and action.action_type in allowed_types_per_txn.get(txn_id, [])
        chosen_actions: List[ActionSpec] = []
        net_vals: List[float] = []
        for t in transaction_ids:
            row = txn_rows.get(t, {})
            allowed_types = [x for x in allowed_types_per_txn.get(t, []) if x != "no_intervention"]
            pref_type = self.config.rule.choose(row, allowed_types)
            act = None
            if pref_type is not None:
                act = _action_by_type(actions, pref_type)
            if not allowed_action(t, act) or not fits(act):
                act = _action_by_type(actions, "no_intervention") \
                    or _action_by_id(actions, self.config.no_op_action_id)
            if not allowed_action(t, act) or not fits(act):
                raise ValueError(f"no policy-approved feasible action for transaction {t}")
            chosen_actions.append(act)
            j = next(i for i, a in enumerate(actions) if a.action_id == act.action_id)
            net_vals.append(float(ev.net_ev_matrix[ev.row_index(t), j]))
            for k, u in act.resource_requirements.items():
                if u and u > 0 and k in used:
                    used[k] += u
                    if k in remaining:
                        remaining[k] -= u
        return PortfolioPlan(
            transaction_ids=transaction_ids,
            actions=chosen_actions,
            net_ev_per_txn=net_vals,
            total_net_ev=float(sum(net_vals)),
            resource_used=used,
            capacities=dict(capacity),
            name="rule_based",
            status="deterministic",
        )

    # ------------------------------------------------------------------
    def ev_greedy(
        self, ev: EVTable, transaction_ids: List[str], actions: List[ActionSpec],
        capacity: Dict[str, Optional[float]], verdicts: List[PolicyVerdict],
    ) -> PortfolioPlan:
        allowed = self._allowed_matrix(ev, verdicts, actions)
        masked = np.where(allowed, ev.net_ev_matrix, -np.inf)
        return ev_per_resource_greedy(
            masked, actions, transaction_ids, capacity, no_op_action_id=self.config.no_op_action_id
        )

    # ------------------------------------------------------------------
    def rpa_optimizer(
        self, ev: EVTable, transaction_ids: List[str], actions: List[ActionSpec],
        capacity: Dict[str, Optional[float]], verdicts: List[PolicyVerdict],
    ) -> PortfolioPlan:
        allowed = self._allowed_matrix(ev, verdicts, actions)
        masked = np.where(allowed, ev.net_ev_matrix, -1e6)
        return self.config.optimizer.solve(
            masked, actions, transaction_ids, capacity
        )

    # ------------------------------------------------------------------
    def run_all(
        self,
        ev: EVTable,
        transactions,
        transaction_ids: List[str],
        actions: List[ActionSpec],
        capacity: Dict[str, Optional[float]],
        verdicts: List[PolicyVerdict],
    ) -> Dict[str, PortfolioPlan]:
        return {
            "no_action": self.no_action(ev, transaction_ids, actions, capacity),
            "rule_based": self.rule_based(ev, transactions, transaction_ids, actions, capacity, verdicts),
            "ev_greedy": self.ev_greedy(ev, transaction_ids, actions, capacity, verdicts),
            "rpa_optimizer": self.rpa_optimizer(ev, transaction_ids, actions, capacity, verdicts),
        }

    def run_one(self, name: str, *args, **kwargs) -> PortfolioPlan:
        fn = getattr(self, name, None)
        if fn is None:
            raise ValueError(f"unknown strategy: {name}")
        return fn(*args, **kwargs)


__all__ = [
    "StrategyRunner",
    "StrategyConfig",
    "RuleBasedEngine",
    "STRATEGY_NAMES",
]
