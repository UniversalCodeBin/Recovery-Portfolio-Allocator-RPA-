"""Provider-neutral execution safety state machine.

This layer is intentionally separate from the demo simulator. A real provider
must call it through a durable repository which enforces the same idempotency
key and resource reservation inside one database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class ExecutionState(StrEnum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


_ALLOWED_TRANSITIONS = {
    ExecutionState.PLANNED: {
        ExecutionState.AUTHORIZED,
        ExecutionState.BLOCKED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.AUTHORIZED: {
        ExecutionState.EXECUTING,
        ExecutionState.BLOCKED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.EXECUTING: {
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.BLOCKED,
    },
    ExecutionState.SUCCEEDED: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.BLOCKED: set(),
    ExecutionState.CANCELLED: set(),
}


@dataclass(frozen=True)
class ExecutionDecision:
    execution_id: str
    transaction_id: str
    idempotency_key: str
    state: ExecutionState
    decision_expires_at: datetime
    policy_allowed: bool
    authorized: bool
    resources_reserved: bool

    def can_execute(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return (
            self.state == ExecutionState.AUTHORIZED
            and self.policy_allowed
            and self.authorized
            and self.resources_reserved
            and self.decision_expires_at > current
        )


def transition(
    decision: ExecutionDecision, target: ExecutionState, *, now: datetime | None = None
) -> ExecutionDecision:
    if target not in _ALLOWED_TRANSITIONS[decision.state]:
        raise ValueError(f"invalid execution transition {decision.state} -> {target}")
    if target == ExecutionState.EXECUTING and not decision.can_execute(now):
        raise PermissionError("execution preconditions failed")
    return ExecutionDecision(**{**decision.__dict__, "state": target})
