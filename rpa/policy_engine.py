"""Policy Engine (hard gate).

Enforces merchant-defined hard constraints over candidate actions for a
transaction. A blocked action MUST never reach execution.

For each (transaction, action) pair the policy returns an ALLOW or BLOCK
verdict plus:

  * policy id
  * rule triggered
  * reason
  * relevant limit
  * current usage (so usage can be inspected/audited)

Policies evaluated (each is a hard gate):
  * disabled action        -> BLOCK
  * blocked action list    -> BLOCK
  * prohibited combination -> BLOCK
  * retry limit            -> BLOCK (retry_count >= max_retries_per_transaction)
  * min net-EV threshold   -> BLOCK any intervention with EV below threshold
  * per-transaction incentive budget cap -> BLOCK
  * batch resource limits  -> BLOCK anything exceeding remaining capacity
                               (incentive budget, messaging, human slots, retry)

The engine is pure: it takes the *current* resource state as input and returns
verdicts + the resource delta. Applying a plan must go through this engine so
a plan can never exceed limits or violate rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from rpa.config import POLICY_VERSION, PolicyConfig
from rpa.ev_engine import EVTable
from rpa.loading import ActionSpec


@dataclass
class PolicyVerdict:
    transaction_id: str
    action_id: str
    decision: str  # "ALLOW" | "BLOCK"
    policy_id: str = POLICY_VERSION
    rule: str = ""
    reason: str = ""
    limit: float | None = None
    current_usage: float | None = None
    action_type: str = ""

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "decision": self.decision,
            "policy_id": self.policy_id,
            "rule": self.rule,
            "reason": self.reason,
            "limit": self.limit,
            "current_usage": self.current_usage,
        }


@dataclass
class ResourceState:
    """Current (remaining) resource capacity across a batch."""

    remaining: dict[str, float] = field(default_factory=dict)

    def can_consume(self, action: ActionSpec) -> bool:
        for key, units in action.resource_requirements.items():
            if units and units > 0:
                current = self.remaining.get(key)
                if current is not None and units > current + 1e-9:
                    return False
        return True

    def consume(self, action: ActionSpec) -> None:
        for key, units in action.resource_requirements.items():
            if units and units > 0:
                current = self.remaining.get(key)
                if current is not None:
                    self.remaining[key] = current - units

    def usage(self, initial: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, cap in initial.items():
            if cap is not None:
                used = max(0.0, cap - self.remaining.get(key, cap))
                out[key] = used
        return out

    def snapshot(self) -> dict[str, float]:
        return dict(self.remaining)


class PolicyEngine:
    def __init__(self, config: PolicyConfig = PolicyConfig()) -> None:  # noqa: B008
        self.config = config

    # -- initial resource state -------------------------------------------
    def initial_resource_state(
        self, resource_limits: dict[str, float | None]
    ) -> ResourceState:
        return ResourceState(
            remaining={
                k: float(v) if v is not None else float("inf")
                for k, v in resource_limits.items()
                if v is not None
            }
        )

    # -- evaluate a single candidate --------------------------------------
    def evaluate_one(
        self,
        *,
        transaction_id: str,
        action: ActionSpec,
        net_ev: float,
        retry_count: int,
        resource_state: ResourceState,
    ) -> PolicyVerdict:
        """Evaluate one (txn, action); does NOT consume resources (pure)."""
        # 1. disabled action
        if not action.enabled:
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="action_disabled",
                reason=f"action {action.action_id} is disabled",
                action_type=action.action_type,
            )
        # 2. blocked action list
        if (
            action.action_id in self.config.blocked_actions
            or action.action_type in self.config.blocked_actions
        ):
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="action_blocked",
                reason=f"action {action.action_id} is on the blocked list",
                action_type=action.action_type,
            )
        # 3. prohibited combination (per-transaction)
        if self.config.prohibit_combination and not action.is_no_op:
            for combo in self.config.prohibit_combination:
                if action.action_type in combo:
                    return PolicyVerdict(
                        transaction_id=transaction_id,
                        action_id=action.action_id,
                        decision="BLOCK",
                        rule="prohibited_combination",
                        reason=f"action {action.action_type} is in prohibited combination {combo}",
                        action_type=action.action_type,
                    )
        # 4. retry limit
        if (
            action.action_type == "retry"
            and retry_count >= self.config.max_retries_per_transaction
        ):
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="retry_limit",
                reason=f"retry_count {retry_count} >= max {self.config.max_retries_per_transaction}",
                limit=self.config.max_retries_per_transaction,
                current_usage=float(retry_count),
                action_type=action.action_type,
            )
        # 5. min net-EV threshold (only binds on interventions)
        if not action.is_no_op and net_ev < self.config.min_net_ev_threshold:
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="min_net_ev",
                reason=f"net EV {net_ev:.2f} < threshold {self.config.min_net_ev_threshold}",
                limit=self.config.min_net_ev_threshold,
                current_usage=float(net_ev),
                action_type=action.action_type,
            )
        # 6. per-transaction incentive budget cap
        incentive_units = action.resource_requirements.get("incentive_budget", 0.0)
        if (
            incentive_units > 0
            and self.config.max_incentive_per_transaction is not None
            and incentive_units > self.config.max_incentive_per_transaction
        ):
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="max_incentive_per_txn",
                reason=f"incentive {incentive_units} exceeds cap {self.config.max_incentive_per_transaction}",
                limit=self.config.max_incentive_per_transaction,
                current_usage=float(incentive_units),
                action_type=action.action_type,
            )
        # 7. batch resource availability (hard gate)
        if not resource_state.can_consume(action):
            blocked_by = next(
                (
                    k
                    for k, u in action.resource_requirements.items()
                    if u
                    and u > 0
                    and resource_state.remaining.get(k) is not None
                    and u > (resource_state.remaining.get(k) or 0.0) + 1e-9
                ),
                None,
            )
            if blocked_by is None:
                blocked_by = "unknown"
            return PolicyVerdict(
                transaction_id=transaction_id,
                action_id=action.action_id,
                decision="BLOCK",
                rule="resource_exhausted",
                reason=f"insufficient remaining {blocked_by} capacity",
                limit=resource_state.remaining.get(blocked_by, 0.0),
                current_usage=action.resource_requirements.get(blocked_by, 0.0),
                action_type=action.action_type,
            )
        return PolicyVerdict(
            transaction_id=transaction_id,
            action_id=action.action_id,
            decision="ALLOW",
            rule="ok",
            reason="",
            action_type=action.action_type,
        )

    # -- evaluate all candidates for a batch (no consumption) ---------------
    def screen(
        self,
        ev_table: EVTable,
        transactions: pd.DataFrame,
        resource_state: ResourceState,
    ) -> list[PolicyVerdict]:
        """Return a verdict for every candidate in the EV table."""
        retry_counts = dict(
            zip(
                transactions["transaction_id"].tolist(),
                transactions["retry_count"].astype(int).tolist(),
            )
        )
        verdicts: list[PolicyVerdict] = []
        for row in ev_table.rows:
            action = next(a for a in ev_table.actions if a.action_id == row.action_id)
            v = self.evaluate_one(
                transaction_id=row.transaction_id,
                action=action,
                net_ev=row.net_expected,
                retry_count=retry_counts.get(row.transaction_id, 0),
                resource_state=resource_state,
            )
            verdicts.append(v)
        return verdicts

    def is_allowed(self, verdict: PolicyVerdict) -> bool:
        return verdict.decision == "ALLOW"


__all__ = ["PolicyConfig", "PolicyEngine", "PolicyVerdict", "ResourceState"]
