"""Audit Trail.

Records every decision across the pipeline for later inspection:

  * run / batch metadata (batch_id, model/policy/optimizer versions, seed)
  * per-transaction predicted probabilities (from prediction service)
  * per-transaction EV economics (gross, costs, net)
  * policy verdicts (allow/block + rule + usage)
  * optimizer / strategy decision (chosen action, rejected alternatives)
  * execution result (attempted/successful/failed/blocked, recovered amount)
  * verification result

An evaluator can answer with one query:
  "Why did the system choose this action for transaction X?"
  -> prediction probability -> EV -> policy verdict -> strategy decision
     -> execution outcome -> verification.

The audit is append-only by design. Rows are keyed by
(component: audit_event) with batch-run linkage and full context in JSON.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rpa.config import (
    EV_ENGINE_VERSION,
    OPTIMIZER_VERSION,
    POLICY_VERSION,
    SIMULATOR_VERSION,
    VERIFICATION_VERSION,
)
from rpa.ev_engine import EVTable
from rpa.execution_simulator import ExecutionResult
from rpa.loading import ActionSpec
from rpa.optimizer import PortfolioPlan
from rpa.policy_engine import PolicyVerdict
from rpa.prediction_service import PredictionResult
from rpa.verification import VerificationResult


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Audit event dataclass
# ---------------------------------------------------------------------------
@dataclass
class AuditEvent:
    audit_id: str
    batch_id: str
    component: str  # prediction | ev | policy | optimizer | execution | verification
    event_type: str
    entity_id: str = ""  # transaction_id (or batch for batch-level events)
    event_metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "batch_id": self.batch_id,
            "component": self.component,
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "event_metadata": self.event_metadata,
            "timestamp": self.timestamp,
        }


class AuditTrail:
    """Collects and persists audit events for a run/batch."""

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.events: list[AuditEvent] = []

    # -- batch-level --------------------------------------------------------
    def record_batch(
        self,
        *,
        seed: int,
        model_identifier: str,
        model_metadata: dict,
        n_transactions: int,
        n_actions: int,
        actions: list[ActionSpec],
        resource_limits: dict[str, float | None],
        strategies: list[str],
    ) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="batch",
            event_type="batch_created",
            event_metadata={
                "seed": seed,
                "model_identifier": model_identifier,
                "model_metadata": model_metadata,
                "n_transactions": n_transactions,
                "n_actions": n_actions,
                "actions": [a.action_id for a in actions],
                "resource_limits": {k: v for k, v in resource_limits.items()},
                "strategies": strategies,
                "policy_version": POLICY_VERSION,
                "optimizer_version": OPTIMIZER_VERSION,
                "ev_engine_version": EV_ENGINE_VERSION,
                "simulator_version": SIMULATOR_VERSION,
                "verification_version": VERIFICATION_VERSION,
            },
        )
        self.events.append(ev)
        return ev

    # -- prediction ---------------------------------------------------------
    def record_predictions(self, result: PredictionResult) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="prediction",
            event_type="predictions_scored",
            event_metadata={
                "model_identifier": result.model_identifier,
                "n_transactions": result.n_transactions,
                "n_actions": result.n_actions,
                "rows": result.frame.to_dict(orient="records"),
            },
        )
        self.events.append(ev)
        return ev

    # -- EV -------------------------------------------------------------
    def record_ev(self, ev_table: EVTable) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="ev",
            event_type="ev_computed",
            event_metadata={
                "engine_version": EV_ENGINE_VERSION,
                "config": {
                    "recovery_friction": ev_table.config.recovery_friction,
                    "incentive_handling_fee": ev_table.config.incentive_handling_fee,
                },
                "rows": [r.to_dict() for r in ev_table.rows],
            },
        )
        self.events.append(ev)
        return ev

    # -- policy ---------------------------------------------------------
    def record_policy(self, verdicts: list[PolicyVerdict]) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="policy",
            event_type="policy_screened",
            event_metadata={
                "policy_version": POLICY_VERSION,
                "verdicts": [v.to_dict() for v in verdicts],
            },
        )
        self.events.append(ev)
        return ev

    # -- optimizer / strategy decision -------------------------------------
    def record_decisions(
        self,
        plans: dict[str, PortfolioPlan],
        rejected_alternatives: dict[str, list[dict]] | None = None,
    ) -> AuditEvent:
        decisions = {}
        for name, plan in plans.items():
            decisions[name] = {
                "records": plan.to_records(),
                "total_net_ev": float(plan.total_net_ev),
                "resource_used": plan.resource_used,
                "status": plan.status,
                "version": plan.version,
            }
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="optimizer",
            event_type="plans_created",
            event_metadata={
                "optimizer_version": OPTIMIZER_VERSION,
                "plans": decisions,
                "rejected_alternatives": rejected_alternatives,
            },
        )
        self.events.append(ev)
        return ev

    # -- execution ---------------------------------------------------------
    def record_execution(self, execution: ExecutionResult) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="execution",
            event_type=f"execution_{execution.plan_name}",
            event_metadata={
                "plan_name": execution.plan_name,
                "batch_seed": execution.batch_seed,
                "simulation": execution.simulation,
                "executions": execution.executions,
                "net_recovered_total": execution.net_recovered_total,
            },
        )
        self.events.append(ev)
        return ev

    # -- verification -------------------------------------------------------
    def record_verification(self, verification: VerificationResult) -> AuditEvent:
        ev = AuditEvent(
            audit_id=new_id("aud"),
            batch_id=self.batch_id,
            component="verification",
            event_type="verified",
            event_metadata={
                "version": verification.version,
                "passed": verification.passed,
                "batch_metrics": verification.batch_metrics,
                "rows": verification.rows,
            },
        )
        self.events.append(ev)
        return ev

    # -- persistence ---------------------------------------------------------
    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    def to_json(self) -> str:
        return json.dumps(self.to_dicts(), indent=2, default=str)

    def write(self, path) -> None:
        import pathlib

        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    # -- inspection helpers ---------------------------------------------------
    def decisions_for_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        """Return all audit events touching a transaction, in order added."""
        out = []
        for e in self.events:
            if e.entity_id == transaction_id:
                out.append(e.to_dict())
        return out

    def explain_selection(
        self, transaction_id: str, strategy: str = "rpa_optimizer"
    ) -> dict[str, Any]:
        """Human-readable 'why was this action chosen' narrative.

        The narrative is self-consistent: prediction, EV and policy rows shown
        correspond to the action the strategy actually chose for the
        transaction (so a chosen action is always backed by an ALLOW verdict).
        """
        explanation = {
            "batch_id": self.batch_id,
            "transaction_id": transaction_id,
            "prediction": None,
            "ev": None,
            "policy": None,
            "decision": None,
            "execution": None,
            "verification": None,
        }
        # 1. Resolve the chosen action for this transaction first.
        chosen_action_id = None
        for e in self.events:
            meta = e.event_metadata or {}
            if e.component == "optimizer":
                plan = meta.get("plans") or {}
                for rec in (plan.get(strategy) or {}).get("records", []):
                    if rec.get("transaction_id") == transaction_id:
                        explanation["decision"] = rec
                        chosen_action_id = rec.get("action_id")
                        break
        # 2. Pick the per-action evidence rows that match the chosen action.
        for e in self.events:
            meta = e.event_metadata or {}
            if e.component == "prediction":
                for row in meta.get("rows", []):
                    if row.get("transaction_id") != transaction_id:
                        continue
                    if (
                        chosen_action_id is None
                        or row.get("action_id") == chosen_action_id
                    ):
                        explanation["prediction"] = row
                        break
            if e.component == "ev":
                for row in meta.get("rows", []):
                    if row.get("transaction_id") != transaction_id:
                        continue
                    if (
                        chosen_action_id is None
                        or row.get("action_id") == chosen_action_id
                    ):
                        explanation["ev"] = row
                        break
            if e.component == "policy":
                for v in meta.get("verdicts", []):
                    if v.get("transaction_id") != transaction_id:
                        continue
                    if (
                        chosen_action_id is None
                        or v.get("action_id") == chosen_action_id
                    ):
                        explanation["policy"] = v
                        break
            if e.component == "execution" and e.event_type == f"execution_{strategy}":
                for ex in meta.get("executions", []):
                    if ex.get("transaction_id") == transaction_id:
                        explanation["execution"] = ex
                        break
            if e.component == "verification":
                for row in meta.get("rows", []):
                    if row.get("transaction_id") == transaction_id:
                        explanation["verification"] = row
                        break
        return explanation


__all__ = ["AuditEvent", "AuditTrail"]
