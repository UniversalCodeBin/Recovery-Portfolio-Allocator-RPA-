"""Verification Layer.

Post-execution verification for every action in a plan:

  * planned vs executed vs successful vs failed vs blocked
  * recovered amount, recovery cost, net recovered amount
  * batch-level metrics

Verification is deterministic: it reconciles what was *planned* (the
:class:`PortfolioPlan`) against what the simulation *executed*. A mismatch
(an action that was planned but came back blocked or missing) is surfaced as a
verification flag/error — nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from rpa.execution_simulator import ExecutionResult
from rpa.loading import ActionSpec
from rpa.optimizer import PortfolioPlan

from rpa.config import VERIFICATION_VERSION


@dataclass
class VerificationResult:
    rows: List[Dict]                 # per-action verification
    batch_metrics: Dict
    passed: bool
    version: str = VERIFICATION_VERSION

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


class VerificationLayer:
    def __init__(self) -> None:
        self.version = VERIFICATION_VERSION

    def verify(
        self,
        plan: PortfolioPlan,
        execution: ExecutionResult,
        actions: List[ActionSpec],
    ) -> VerificationResult:
        exec_by_txn = {r["transaction_id"]: r for r in execution.executions}

        rows: List[Dict] = []
        all_ok = True
        for i, txn in enumerate(plan.transaction_ids):
            planned = plan.actions[i]
            planned_index = next(
                (j for j, a in enumerate(actions) if a.action_id == planned.action_id), -1)
            plan_ev = (
                plan.net_ev_per_txn[i]
                if i < len(plan.net_ev_per_txn) else None
            )
            exec_row = exec_by_txn.get(txn)
            row: Dict = {
                "transaction_id": txn,
                "planned_action_id": planned.action_id,
                "planned_action_type": planned.action_type,
                "planned_net_ev": plan_ev,
                "planned_index": planned_index,
                "executed": False,
                "executed_action_id": None,
                "executed_status": None,
                "successful": False,
                "failed": False,
                "blocked": False,
                "recovered_amount": 0.0,
                "recovery_cost": 0.0,
                "net_recovered_amount": 0.0,
                "verified": False,
            }
            if exec_row is None:
                row["verified"] = False
                row["verification_error"] = "missing execution record"
                all_ok = False
                rows.append(row)
                continue
            row["executed"] = bool(exec_row.get("attempted", 0))
            row["executed_action_id"] = exec_row.get("action_id")
            row["executed_status"] = exec_row.get("status")
            row["successful"] = exec_row.get("status") == "successful"
            row["failed"] = exec_row.get("status") == "failed"
            row["blocked"] = exec_row.get("status") == "blocked"
            row["recovered_amount"] = float(exec_row.get("recovered_amount", 0.0))
            row["recovery_cost"] = float(exec_row.get("recovery_cost", 0.0))
            row["net_recovered_amount"] = float(exec_row.get("net_recovered_amount", 0.0))
            # Cross-check planned vs executed action.
            if exec_row.get("action_id") != planned.action_id:
                row["verified"] = False
                row["verification_error"] = (
                    f"executed action {exec_row.get('action_id')} != planned "
                    f"{planned.action_id}"
                )
                all_ok = False
            elif not row["executed"]:
                row["verified"] = False
                row["verification_error"] = "planned action was not executed"
                all_ok = False
            else:
                row["verified"] = True
            rows.append(row)

        batch_metrics = {
            "plan_name": plan.name,
            "n_transactions": len(plan.transaction_ids),
            "n_planned": len(plan.transaction_ids),
            "n_executed": sum(1 for r in rows if r["executed"]),
            "n_successful": sum(1 for r in rows if r["successful"]),
            "n_failed": sum(1 for r in rows if r["failed"]),
            "n_blocked": sum(1 for r in rows if r["blocked"]),
            "planned_total_net_ev": float(sum(plan.net_ev_per_txn)),
            "recovered_total": float(sum(r["recovered_amount"] for r in rows)),
            "cost_total": float(sum(r["recovery_cost"] for r in rows)),
            "net_recovered_total": float(sum(r["net_recovered_amount"] for r in rows)),
            "all_verified": all_ok,
            "simulation": True,
        }
        return VerificationResult(rows=rows, batch_metrics=batch_metrics, passed=all_ok)


__all__ = ["VerificationLayer", "VerificationResult"]