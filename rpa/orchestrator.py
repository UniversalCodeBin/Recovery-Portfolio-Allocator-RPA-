"""Batch orchestrator — wires the full Step 3 pipeline for one recovery batch.

Flow:
    load transactions/actions/customers
        -> PredictionService.score        (frozen model, never retrains)
        -> EVEngine.compute                (deterministic economics)
        -> PolicyEngine.screen             (hard gates -> ALLOW/BLOCK)
        -> StrategyRunner.run_all          (no_action, rule_based, ev_greedy, rpa_optimizer)
        -> ExecutionSimulator.execute      (seeded, simulated, policy-approved only)
        -> VerificationLayer.verify        (planned vs executed)
        -> AuditTrail.record_*             (full decision trail)

Fail-closed: any failure in prediction, EV, policy, optimizer, or validation
halts the batch; no plan is produced and no execution happens.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from rpa.audit import AuditTrail
from rpa.config import RUNS_DIR, default_resource_limits
from rpa.ev_engine import EVEngine, EVTable
from rpa.execution_simulator import ExecutionSimulator, ExecutionResult
from rpa.loading import (
    ActionSpec,
    load_actions,
    load_customers,
    load_transactions,
    predictions_matrix,
)
from rpa.optimizer import Optimizer, PortfolioPlan
from rpa.policy_engine import PolicyEngine, PolicyVerdict
from rpa.prediction_service import PredictionResult, PredictionService
from rpa.strategies import StrategyRunner, STRATEGY_NAMES
from rpa.verification import VerificationLayer, VerificationResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BatchResult:
    """Full output of one recovery batch run."""

    batch_id: str
    status: str                       # "completed" | "error" | "pending"
    prediction: Optional[PredictionResult]
    ev_table: Optional[EVTable]
    verdicts: List[PolicyVerdict]
    plans: Dict[str, PortfolioPlan]
    executions: Dict[str, ExecutionResult]
    verifications: Dict[str, VerificationResult]
    actions: List[ActionSpec]
    transaction_ids: List[str]
    resource_limits: Dict[str, Optional[float]]
    audit: AuditTrail
    error: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    # -- derived convenience -------------------------------------------------
    def plan_for(self, strategy: str) -> PortfolioPlan:
        return self.plans[strategy]

    def execution_for(self, strategy: str) -> ExecutionResult:
        return self.executions[strategy]

    def verification_for(self, strategy: str) -> VerificationResult:
        return self.verifications[strategy]

    def n_blocked_overall(self) -> int:
        return sum(v.decision == "BLOCK" for v in self.verdicts)

    # -- persistence ---------------------------------------------------------
    def to_dict(self) -> Dict:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "created_at": self.created_at,
            "error": self.error,
            "prediction": None if self.prediction is None else {
                "model_identifier": self.prediction.model_identifier,
                "n_transactions": self.prediction.n_transactions,
                "n_actions": self.prediction.n_actions,
                "model_metadata": self.prediction.model_metadata,
            },
            "ev_table": self.ev_table.to_frame().to_dict(orient="records")
                if self.ev_table else None,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "plans": {
                name: plan.to_records() for name, plan in self.plans.items()
            },
            "executions": {
                name: ex.to_frame().to_dict(orient="records")
                for name, ex in self.executions.items()
            },
            "verifications": {
                name: {
                    "batch_metrics": verif.batch_metrics,
                    "rows": verif.rows,
                } for name, verif in self.verifications.items()
            },
            "transaction_ids": self.transaction_ids,
            "resource_limits": {k: v for k, v in self.resource_limits.items()},
        }

    def summary(self) -> Dict:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "n_transactions": len(self.transaction_ids),
            "n_actions": len(self.actions),
            "strategy_metrics": {
                name: {
                    "total_expected_net_ev": round(plan.total_net_ev, 4),
                    "resource_used": plan.resource_used,
                    "status": plan.status,
                    **self.verifications[name].batch_metrics,
                }
                for name, plan in self.plans.items()
            },
            "n_blocked_candidates": self.n_blocked_overall(),
            "error": self.error,
        }


class RPABatchOrchestrator:
    """Top-level orchestrator. Dispatches to each component with dependency
    injection so tests can substitute fakes."""

    def __init__(
        self,
        *,
        prediction_service: Optional[PredictionService] = None,
        ev_engine: Optional[EVEngine] = None,
        policy_engine: Optional[PolicyEngine] = None,
        optimizer: Optional[Optimizer] = None,
        strategy_runner: Optional[StrategyRunner] = None,
        simulator: Optional[ExecutionSimulator] = None,
        verifier: Optional[VerificationLayer] = None,
    ) -> None:
        self.prediction_service = prediction_service or PredictionService()
        self.ev_engine = ev_engine or EVEngine()
        self.policy_engine = policy_engine or PolicyEngine()
        self.optimizer = optimizer or Optimizer()
        from rpa.strategies import StrategyConfig
        self.strategy_runner = strategy_runner or StrategyRunner(
            config=StrategyConfig(optimizer=self.optimizer)
        )
        self.simulator = simulator or ExecutionSimulator(
            policy_engine=self.policy_engine
        )
        self.verifier = verifier or VerificationLayer()

    # ------------------------------------------------------------------
    def _fail_closed(self, batch_id: str, err: str) -> BatchResult:
        return BatchResult(
            batch_id=batch_id,
            status="error",
            prediction=None,
            ev_table=None,
            verdicts=[],
            plans={},
            executions={},
            verifications={},
            actions=[],
            transaction_ids=[],
            resource_limits={},
            audit=AuditTrail(batch_id),
            error=err,
        )

    def run_batch(
        self,
        *,
        transactions: pd.DataFrame,
        actions: List[ActionSpec],
        customers: pd.DataFrame,
        resource_limits: Dict[str, Optional[float]],
        batch_seed: int = 0,
        strategies: Optional[List[str]] = None,
        predictions: Optional[np.ndarray] = None,
        predictions_model_id: Optional[str] = None,
        model_metadata: Optional[dict] = None,
        split: Optional[str] = None,
    ) -> BatchResult:
        strategies = strategies or [s for s in STRATEGY_NAMES if s != "rule_based"]
        batch_id = f"batch_{uuid.uuid4().hex[:10]}"
        audit = AuditTrail(batch_id)

        # -- 1. Predictions (frozen model or precomputed) --------------------
        prediction_result: Optional[PredictionResult] = None
        if predictions is not None:
            probs = predictions
            model_id = predictions_model_id or "precomputed"
        else:
            try:
                prediction_result = self.prediction_service.score(
                    transactions, customers, actions
                )
                probs = prediction_result.probabilities
                model_id = prediction_result.model_identifier
            except Exception as exc:
                return self._fail_closed(batch_id, f"prediction_failed: {exc}")

        # -- 2. EV ------------------------------------------------------------
        try:
            ev_table = self.ev_engine.compute(transactions, probs, actions)
        except Exception as exc:
            return self._fail_closed(batch_id, f"ev_failed: {exc}")

        # -- 3. Policy screen (no consumption; block hard) ---------------------
        try:
            res_state = self.policy_engine.initial_resource_state(resource_limits)
            verdicts = self.policy_engine.screen(ev_table, transactions, res_state)
        except Exception as exc:
            return self._fail_closed(batch_id, f"policy_failed: {exc}")

        txn_ids = transactions["transaction_id"].tolist()

        # -- audit the non-decision components --------------------------------
        if prediction_result is not None:
            audit.record_predictions(prediction_result)
        audit.record_batch(
            seed=batch_seed,
            model_identifier=model_id,
            model_metadata=model_metadata or (prediction_result.model_metadata
                                              if prediction_result else {}),
            n_transactions=len(txn_ids),
            n_actions=len(actions),
            actions=actions,
            resource_limits=resource_limits,
            strategies=strategies,
        )
        audit.record_ev(ev_table)
        audit.record_policy(verdicts)

        # -- 4. Strategies -----------------------------------------------------
        plans: Dict[str, PortfolioPlan] = {}
        try:
            all_plans = self.strategy_runner.run_all(
                ev_table, transactions, txn_ids, actions, resource_limits, verdicts
            )
            plans = {name: all_plans[name] for name in strategies if name in all_plans}
        except Exception as exc:
            return self._fail_closed(batch_id, f"optimizer_failed: {exc}")

        rejected = self._rejected_alternatives(ev_table, verdicts, plans)
        audit.record_decisions(plans, rejected_alternatives=rejected)

        # -- 5. Execution (simulation) -----------------------------------------
        executions: Dict[str, ExecutionResult] = {}
        for strategy, plan in plans.items():
            try:
                ex = self.simulator.execute(
                    plan, transactions, probs, actions, verdicts, batch_seed
                )
                executions[strategy] = ex
                audit.record_execution(ex)
            except Exception as exc:
                return self._fail_closed(batch_id, f"execution_failed[{strategy}]: {exc}")

        # -- 6. Verification ----------------------------------------------------
        verifications: Dict[str, VerificationResult] = {}
        for strategy, plan in plans.items():
            verif = self.verifier.verify(
                plan, executions[strategy], actions
            )
            verifications[strategy] = verif
            audit.record_verification(verif)

        result = BatchResult(
            batch_id=batch_id,
            status="completed",
            prediction=prediction_result,
            ev_table=ev_table,
            verdicts=verdicts,
            plans=plans,
            executions=executions,
            verifications=verifications,
            actions=actions,
            transaction_ids=txn_ids,
            resource_limits=resource_limits,
            audit=audit,
        )
        self._persist(result)
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _rejected_alternatives(
        ev_table: EVTable,
        verdicts: List[PolicyVerdict],
        plans: Dict[str, PortfolioPlan],
    ) -> Dict[str, List[Dict]]:
        """Rejected alternatives per transaction per plan (chosen not among top EV)."""
        out: Dict[str, List[Dict]] = {}
        for plan_name, plan in plans.items():
            lst: List[Dict] = []
            for i, txn in enumerate(plan.transaction_ids):
                chosen_action_id = plan.actions[i].action_id
                # Top-5 EV candidates for this transaction.
                row = ev_table.row_index(txn)
                evs = ev_table.net_ev_matrix[row]
                top_idx = np.argsort(-evs)[:5]
                alternatives = []
                for j in top_idx:
                    a = ev_table.actions[j]
                    if a.action_id != chosen_action_id:
                        alternatives.append({
                            "action_id": a.action_id,
                            "action_type": a.action_type,
                            "net_ev": round(float(evs[j]), 4),
                        })
                lst.append({
                    "transaction_id": txn,
                    "chosen_action_id": chosen_action_id,
                    "alternatives": alternatives,
                })
            out[plan_name] = lst
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _persist(result: BatchResult) -> None:
        """Persist batch run to a JSON file (DB write is optional via Step 1
        Database when reachable)."""
        try:
            out_dir = RUNS_DIR / result.batch_id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "result.json").write_text(
                json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
            )
            result.audit.write(out_dir / "audit.json")
        except Exception as exc:
            # Persistence must never take the pipeline down.
            pass


# ---------------------------------------------------------------------------
# High-level convenience: run a whole split end-to-end
# ---------------------------------------------------------------------------
def run_batch_on_split(
    split: str = "demo",
    *,
    batch_seed: int = 0,
    resource_limits: Optional[Dict[str, Optional[float]]] = None,
    strategies: Optional[List[str]] = None,
    orchestrator: Optional[RPABatchOrchestrator] = None,
) -> BatchResult:
    """Load split data and run a full recovery batch."""
    transactions = load_transactions(split)
    customers = load_customers()
    actions = load_actions()
    limits = resource_limits or default_resource_limits()
    orch = orchestrator or RPABatchOrchestrator()
    return orch.run_batch(
        transactions=transactions,
        actions=actions,
        customers=customers,
        resource_limits=limits,
        batch_seed=batch_seed,
        strategies=strategies,
        split=split,
    )


def load_batch_result(batch_id: str) -> Dict:
    """Load a previously persisted batch run result from disk."""
    p = RUNS_DIR / batch_id / "result.json"
    if not p.exists():
        raise FileNotFoundError(f"batch run not found: {batch_id}")
    return json.loads(p.read_text(encoding="utf-8"))


__all__ = ["RPABatchOrchestrator", "BatchResult", "run_batch_on_split", "load_batch_result"]