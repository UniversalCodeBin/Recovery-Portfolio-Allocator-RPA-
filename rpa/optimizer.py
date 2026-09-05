"""RPA Optimizer (exact ILP) + EV-per-resource greedy baseline.

The optimizer treats the ENTIRE batch as the unit of optimization under shared
resource constraints — it does NOT optimize transactions independently.

Formulation (exact Mixed-Integer Linear Program, solved with OR-Tools CBC):

    Variables:  x[i, a] in {0, 1}  (1 iff txn i receives action a)
    Maximize:   sum_{i,a} x[i,a] * net_ev[i,a]
    subject to
        sum_a x[i,a] = 1                     for all i        (one action per txn)
        sum_i x[i,a] * R[a, r] <= cap[r]     for all resources r  (shared caps)
        x[i,a] in {0, 1}

    where R[a, r] is action a's consumption of shared resource r
          (incentive_budget, human_slots, messaging, retry).

A dedicated no-op action (act_no_intervention with zero resource usage and
typically non-negative EV) guarantees feasibility.

The greedy baseline (ev_per_resource_greedy) is a strong, credible comparator:
it processes transactions in descending order of (best EV / resource consumed),
committing each transaction's best affordable action under remaining capacity.
RPA must beat this baseline to demonstrate portfolio-level value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ortools.linear_solver import pywraplp

from rpa.config import OPTIMIZER_VERSION, OptimizerConfig
from rpa.loading import ActionSpec

# Order in which resource capacities are defined (for stable reporting).
RESOURCE_KEYS = ["retry", "messaging", "incentive_budget", "human_slots"]


@dataclass
class PortfolioPlan:
    """One allocation decision for a batch (per strategy)."""

    transaction_ids: List[str]
    actions: List[ActionSpec]                 # chosen action per transaction
    net_ev_per_txn: List[float]
    total_net_ev: float
    resource_used: Dict[str, float]
    capacities: Dict[str, Optional[float]]
    name: str
    version: str = OPTIMIZER_VERSION
    status: str = "ok"
    solve_time_seconds: Optional[float] = None

    def to_records(self) -> List[Dict]:
        out = []
        for i, txn in enumerate(self.transaction_ids):
            out.append({
                "transaction_id": txn,
                "action_id": self.actions[i].action_id,
                "action_type": self.actions[i].action_type,
                "net_ev": round(self.net_ev_per_txn[i], 6),
                "name": self.name,
                "version": self.version,
                "status": self.status,
            })
        return out


def _resource_consumption(action: ActionSpec) -> Dict[str, float]:
    return {
        key: float(action.resource_requirements.get(key, 0.0) or 0.0)
        for key in RESOURCE_KEYS
    }


class Optimizer:
    """Exact constrained-portfolio solver via OR-Tools CBC."""

    def __init__(self, config: OptimizerConfig = OptimizerConfig()) -> None:
        self.config = config
        self.version = OPTIMIZER_VERSION

    # ------------------------------------------------------------------
    def _find_no_op(self, actions: List[ActionSpec]) -> Optional[int]:
        for i, a in enumerate(actions):
            if a.action_id == self.config.no_op_action_id or a.is_no_op:
                return i
        return None

    def solve(
        self,
        net_ev: np.ndarray,
        actions: List[ActionSpec],
        transaction_ids: List[str],
        capacity: Dict[str, Optional[float]],
    ) -> PortfolioPlan:
        """Solve the exact ILP (portfolio-level) with CBC."""
        n, m = net_ev.shape
        if len(actions) != m:
            raise ValueError("net_ev columns must match len(actions)")
        if len(transaction_ids) != n:
            raise ValueError("net_ev rows must match len(transaction_ids)")

        solver = pywraplp.Solver.CreateSolver(self.config.solver)
        if solver is None:
            raise RuntimeError(f"CBC solver unavailable in OR-Tools build")

        # no-op fallback: ensure a zero-ish column exists for feasibility.
        no_op_idx = self._find_no_op(actions)
        if no_op_idx is None:
            raise ValueError("no no-op action provided; problem may be infeasible")

        x: List[List[pywraplp.Variable]] = [
            [solver.BoolVar(f"x_{i}_{j}") for j in range(m)] for i in range(n)
        ]

        objective = solver.Objective()
        for i in range(n):
            for j in range(m):
                objective.SetCoefficient(x[i][j], float(net_ev[i, j]))
        objective.SetMaximization()

        # Constraint: exactly one action per transaction.
        for i in range(n):
            c = solver.Constraint(1, 1)
            for j in range(m):
                c.SetCoefficient(x[i][j], 1.0)

        # Constraint: shared resource capacities.
        for key in RESOURCE_KEYS:
            cap = capacity.get(key)
            if cap is None:
                continue
            cons = solver.Constraint(0.0, float(cap))
            for i in range(n):
                for j in range(m):
                    units = _resource_consumption(actions[j]).get(key, 0.0)
                    if units > 0:
                        cons.SetCoefficient(x[i][j], float(units))

        solver.SetTimeLimit(int(self.config.time_limit_seconds * 1000))
        status = solver.Solve()
        optimal = status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)
        if not optimal:
            return PortfolioPlan(
                transaction_ids=transaction_ids,
                actions=[actions[no_op_idx]] * n,
                net_ev_per_txn=[float(net_ev[i, no_op_idx]) for i in range(n)],
                total_net_ev=float(sum(net_ev[i, no_op_idx] for i in range(n))),
                resource_used={k: 0.0 for k in RESOURCE_KEYS},
                capacities=dict(capacity),
                name="rpa_optimizer",
                status=f"infeasible:{status}",
            )

        chosen = np.zeros(n, dtype=int)
        for i in range(n):
            for j in range(m):
                if x[i][j].solution_value() > 0.5:
                    chosen[i] = j
                    break
            else:
                chosen[i] = no_op_idx

        net_per_txn = [float(net_ev[i, chosen[i]]) for i in range(n)]
        used: Dict[str, float] = {k: 0.0 for k in RESOURCE_KEYS}
        for i in range(n):
            cons = _resource_consumption(actions[chosen[i]])
            for k in RESOURCE_KEYS:
                used[k] += cons[k]

        return PortfolioPlan(
            transaction_ids=transaction_ids,
            actions=[actions[int(j)] for j in chosen],
            net_ev_per_txn=net_per_txn,
            total_net_ev=float(sum(net_per_txn)),
            resource_used=used,
            capacities=dict(capacity),
            name="rpa_optimizer",
            status="optimal" if status == pywraplp.Solver.OPTIMAL else f"status={status}",
            solve_time_seconds=float(solver.WallTime() / 1000.0) if solver.WallTime() else None,
        )


# ---------------------------------------------------------------------------
# EV-per-resource greedy baseline
# ---------------------------------------------------------------------------
def _resource_magnitude(action: ActionSpec) -> float:
    """Scalar 'size' of an action's resource consumption for EV-ratio ranking.

    For no-resource/no-op actions the magnitude is 1.0 so their EV is used
    directly. Uses rupee-ish weights to make units commensurable.
    """
    req = action.resource_requirements
    w = {
        "retry": 1.0,
        "messaging": 2.0,
        "incentive_budget": 1.0 / 50.0,
        "human_slots": 20.0,
    }
    total = sum(w.get(k, 1.0) * float(v) for k, v in req.items() if v and v > 0)
    return total if total > 1e-12 else 1.0


def ev_per_resource_greedy(
    net_ev: np.ndarray,
    actions: List[ActionSpec],
    transaction_ids: List[str],
    capacity: Dict[str, Optional[float]],
    no_op_action_id: str = "act_no_intervention",
) -> PortfolioPlan:
    """Strong greedy baseline: rank txns by best (EV / resource) ratio.

    Process transactions in descending order of their best-action EV-per-unit-
    resource; commit the best *feasible* action under remaining capacity.
    """
    n, m = net_ev.shape
    remaining: Dict[str, float] = {
        k: float(v) for k, v in capacity.items() if v is not None
    }

    def feasible(action: ActionSpec) -> bool:
        req = action.resource_requirements
        for key, units in req.items():
            if units and units > 0 and key in remaining:
                if units > remaining[key] + 1e-9:
                    return False
        return True

    def consume(action: ActionSpec) -> None:
        for key, units in action.resource_requirements.items():
            if units and units > 0 and key in remaining:
                remaining[key] -= units

    # Score each txn by its best feasible EV-per-resource candidate.
    scores = np.zeros(n)
    for i in range(n):
        best = -np.inf
        for j in range(m):
            magnitudes = _resource_magnitude(actions[j])
            if feasible(actions[j]):
                ratio = float(net_ev[i, j]) / magnitudes
                if ratio > best:
                    best = ratio
        scores[i] = best

    order = np.argsort(-scores, kind="stable")

    chosen = np.zeros(n, dtype=int)
    for pos in order:
        i = int(pos)
        # Choose best-EV feasible action (fall back to no-op).
        candidates = sorted(range(m), key=lambda j: -float(net_ev[i, j]))
        picked = None
        for j in candidates:
            if feasible(actions[j]):
                picked = j
                break
        if picked is None:
            picked = next((j for j in range(m) if actions[j].action_id == no_op_action_id), 0)
        consume(actions[picked])
        chosen[i] = picked

    net_per_txn = [float(net_ev[i, chosen[i]]) for i in range(n)]
    used: Dict[str, float] = {k: 0.0 for k in RESOURCE_KEYS}
    for i in range(n):
        cons = _resource_consumption(actions[chosen[i]])
        for k in RESOURCE_KEYS:
            used[k] += cons[k]

    return PortfolioPlan(
        transaction_ids=transaction_ids,
        actions=[actions[int(j)] for j in chosen],
        net_ev_per_txn=net_per_txn,
        total_net_ev=float(sum(net_per_txn)),
        resource_used=used,
        capacities=dict(capacity),
        name="ev_greedy",
        status="greedy",
    )


__all__ = ["Optimizer", "PortfolioPlan", "ev_per_resource_greedy", "OptimizerConfig"]
