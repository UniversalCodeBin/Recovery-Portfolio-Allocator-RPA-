"""Execution Simulator.

Deterministic, reproducible simulation of a policy-approved recovery plan. It
is a SIMULATION ONLY — it never moves real money. Every step is clearly
labelled as simulation.

Feeding:
  * an approved :class:`PortfolioPlan` (already only policy-approved actions),
  * the transaction amounts,
  * per-(txn, action) predicted probabilities,
  * a random seed.

Behavior:
  * Only policy-approved actions are executed. If an action arrives here that
    was NOT approved, it is recorded as ``blocked`` and NOT executed
    (fail-closed).
  * Outcomes are drawn with a seeded generator derived from
    (batch_seed, plan.name) so the same seed reproduces the same realization
    and different strategies on the same batch share outcome randomness where
    possible.
  * On success, the recovered amount is the recoverable amount (amount *
    recovered_fraction), where recovered_fraction is drawn in
    [partial_low, partial_high] for partial and 1.0 for full recovery.

Each execution row records: transaction_id, action_id, plan name, status
(attempted / successful / failed / blocked), recovered_amount, recovery_cost
(total action + incentive cost), net_recovered_amount, seed, and a simulation
flag.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from rpa.config import SIMULATOR_VERSION, EVEngineConfig, SimulationConfig
from rpa.loading import ActionSpec
from rpa.optimizer import PortfolioPlan
from rpa.policy_engine import PolicyEngine, PolicyVerdict

# Execution statuses.
ATTEMPTED = "attempted"
SUCCESSFUL = "successful"
FAILED = "failed"
BLOCKED = "blocked"


@dataclass
class ExecutionResult:
    executions: list[dict]  # one per transaction
    plan_name: str
    batch_seed: int
    net_recovered_total: float
    simulation: bool = True
    version: str = SIMULATOR_VERSION

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.executions)

    def batch_metrics(self) -> dict:
        df = self.to_frame()
        return {
            "plan_name": self.plan_name,
            "n_transactions": len(df),
            "n_attempted": int(df["attempted"].sum()),
            "n_successful": int((df["status"] == SUCCESSFUL).sum()),
            "n_failed": int((df["status"] == FAILED).sum()),
            "n_blocked": int((df["status"] == BLOCKED).sum()),
            "recovered_total": float(df["recovered_amount"].sum()),
            "cost_total": float(df["recovery_cost"].sum()),
            "net_recovered_total": float(df["net_recovered_amount"].sum()),
            "simulation": True,
        }


class ExecutionSimulator:
    def __init__(
        self,
        ev_config: EVEngineConfig = EVEngineConfig(),  # noqa: B008
        sim_config: SimulationConfig = SimulationConfig(),  # noqa: B008
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.ev_config = ev_config
        self.sim_config = sim_config
        self.policy_engine = policy_engine or PolicyEngine()

    @staticmethod
    def _derive_seed(batch_seed: int, tag: str) -> int:
        digest = hashlib.sha256(f"{batch_seed}:{tag}".encode()).hexdigest()
        return int(digest[:16], 16)

    def _approved_actions(self, verdicts: list[PolicyVerdict]) -> set[tuple[str, str]]:
        """Return approvals at the transaction/action granularity.

        A policy verdict is never global to an action: retry limits, EV, and
        per-transaction restrictions can legitimately block the same action
        for one transaction while allowing it for another.
        """
        return {
            (v.transaction_id, v.action_id) for v in verdicts if v.decision == "ALLOW"
        }

    def execute(
        self,
        plan: PortfolioPlan,
        transactions: pd.DataFrame,
        probabilities: np.ndarray,
        actions: list[ActionSpec],
        verdicts: list[PolicyVerdict],
        batch_seed: int,
    ) -> ExecutionResult:
        """Simulate execution of `plan`.

        ``verdicts`` is the full policy screen; only actions with an ALLOW
        verdict are executed. plan's actions must all be in the allowed set —
        any that isn't is recorded as blocked (fail-closed).

        Outcomes are deterministic per (transaction_id, batch_seed). The same
        transaction with the same seed always produces the same Monte-Carlo
        realization regardless of strategy, action execution order, or plan
        ordering.  This is achieved by deriving a per-transaction RNG seed
        from ``hash(transaction_id, batch_seed)`` instead of consuming a
        shared per-strategy RNG sequence.
        """
        approved = self._approved_actions(verdicts)
        # Build action id -> column index
        action_idx = {a.action_id: j for j, a in enumerate(actions)}
        txn_idx = {t: i for i, t in enumerate(transactions["transaction_id"].tolist())}
        amounts_by_txn = transactions.set_index("transaction_id")["amount"]

        rows: list[dict] = []
        for i, txn in enumerate(plan.transaction_ids):
            action = plan.actions[i]
            if (txn, action.action_id) not in approved:
                rows.append(self._blocked_row(txn, action))
                continue
            # ---- execute (simulate) ----
            amounts = amounts_by_txn.loc[txn]
            p = float(
                np.clip(
                    probabilities[txn_idx[txn], action_idx[action.action_id]],
                    self.ev_config.prob_floor,
                    self.ev_config.prob_ceil,
                )
            )
            recoverable = float(amounts) * (1.0 - self.ev_config.recovery_friction)

            # Per-transaction deterministic RNG: same (txn_id, seed) → same outcome
            rng_txn_success = np.random.default_rng(
                self._derive_seed(
                    batch_seed, f"{self.sim_config.seed_salt}:success:{txn}"
                )
            )
            rng_txn_fraction = np.random.default_rng(
                self._derive_seed(
                    batch_seed, f"{self.sim_config.seed_salt}:fraction:{txn}"
                )
            )

            success_draw = rng_txn_success.random()
            succeeded = success_draw < p

            cost = self._recovery_cost(action)

            status = SUCCESSFUL if succeeded else FAILED
            if succeeded:
                frac_draw = rng_txn_fraction.random()
                frac = (
                    1.0 + (self.sim_config.partial_low - 1.0) * frac_draw
                    if False
                    else (
                        self.sim_config.partial_low
                        + (self.sim_config.partial_high - self.sim_config.partial_low)
                        * frac_draw
                    )
                )
                recovered = recoverable * frac
            else:
                recovered = 0.0

            rows.append(
                {
                    "transaction_id": txn,
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "plan_name": plan.name,
                    "status": status,
                    "attempted": 1,
                    "recovered_amount": round(float(recovered), 4),
                    "recovery_cost": round(float(cost), 4),
                    "net_recovered_amount": round(float(recovered - cost), 4),
                    "p_predicted": round(p, 6),
                    "seed": batch_seed,
                    "simulation": True,
                }
            )

        net = sum(float(r["net_recovered_amount"]) for r in rows)
        return ExecutionResult(
            executions=rows,
            plan_name=plan.name,
            batch_seed=batch_seed,
            net_recovered_total=float(net),
        )

    def _recovery_cost(self, action: ActionSpec) -> float:
        """Total rupee cost: handling cost + incentive budget + handling fee."""
        action_cost = float(action.action_cost)
        incentive_units = float(
            action.resource_requirements.get("incentive_budget", 0.0)
        )
        incentive_cost = incentive_units * self.ev_config.incentive_handling_fee
        return action_cost + incentive_cost

    def _blocked_row(self, txn: str, action: ActionSpec) -> dict:
        return {
            "transaction_id": txn,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "plan_name": None,
            "status": BLOCKED,
            "attempted": 0,
            "recovered_amount": 0.0,
            "recovery_cost": 0.0,
            "net_recovered_amount": 0.0,
            "p_predicted": 0.0,
            "seed": None,
            "simulation": True,
        }


__all__ = ["ExecutionResult", "ExecutionSimulator"]
