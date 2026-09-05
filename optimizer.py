"""OR-Tools CBC exact ILP integration for the Revenue Recovery Allocator.

Formulation (see plan):

  max  sum_{i in T, j in A} x_ij * EV_ij
  s.t. sum_{j in A} x_ij = 1                       for all i in T
       sum_{i} x_ij * R_{j,r}  <=  cap_r          for all r in R
       x_ij in {0,1}

EV_ij = amount_i * p_ij - cost_j  (expected net recovery).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from ortools.linear_solver import pywraplp

from actions import ResourceVector, action_resource_vector
from config import Action

NO_ACTION = Action.NO_INTERVENTION


@dataclass(frozen=True)
class SolverResult:
    """Result of one ILP solve."""

    status: str
    optimal: bool
    objective: float
    assignment: np.ndarray         # action index per transaction
    resources_used: Dict[str, float]
    gaps: Optional[Dict[str, float]] = None


def _resource_capacity_dict(
    incentive_cap: Optional[float] = None,
    human_cap: Optional[float] = None,
    messaging_cap: Optional[float] = None,
    retry_cap: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    return {
        "retry": retry_cap,
        "messaging": messaging_cap,
        "incentive": incentive_cap,
        "human": human_cap,
    }


def solve_ilp(
    ev_matrix: np.ndarray,
    actions: Sequence[Action],
    capacity: Dict[str, Optional[float]],
    time_limit_seconds: float = 30.0,
) -> SolverResult:
    """Solve the exact ILP via CBC (free MIP solver shipped with OR-Tools).

    ev_matrix shape (n_transactions, len(actions)); column j aligned with
    actions[j]. capacity: mapping resource-name -> capacity (None = unlimited).
    """
    n, m = ev_matrix.shape
    if len(actions) != m:
        raise ValueError("len(actions) must match ev_matrix columns")

    solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        raise RuntimeError("CBC solver unavailable in OR-Tools build")

    # Binary decision variables: x[i][j] = 1 iff txn i receives action j.
    x: List[List[pywraplp.Variable]] = [
        [solver.BoolVar(f"x_{i}_{j}") for j in range(m)] for i in range(n)
    ]

    # Objective: maximize total expected net recovery.
    objective = solver.Objective()
    for i in range(n):
        for j in range(m):
            objective.SetCoefficient(x[i][j], float(ev_matrix[i, j]))
    objective.SetMaximization()

    # Constraint 1: exactly one action per transaction.
    for i in range(n):
        c = solver.Constraint(1, 1)
        for j in range(m):
            c.SetCoefficient(x[i][j], 1.0)

    # Constraint 2..K: resource capacities.
    resource_keys = ["retry", "messaging", "incentive", "human"]
    for r in resource_keys:
        cap = capacity.get(r)
        if cap is None:
            continue
        cons = solver.Constraint(0.0, float(cap))
        for i in range(n):
            for j in range(m):
                rv = action_resource_vector(actions[j])
                unit = getattr(rv, r)
                if unit > 0:
                    cons.SetCoefficient(x[i][j], float(unit))

    solver.SetTimeLimit(int(time_limit_seconds * 1000))
    status = solver.Solve()

    if status not in (
        pywraplp.Solver.OPTIMAL,
        pywraplp.Solver.FEASIBLE,
    ):
        return SolverResult(
            status=str(status),
            optimal=False,
            objective=0.0,
            assignment=np.zeros(n, dtype=int),
            resources_used={k: 0.0 for k in resource_keys},
        )

    assignment = np.zeros(n, dtype=int)
    for i in range(n):
        for j in range(m):
            if x[i][j].solution_value() > 0.5:
                assignment[i] = j
                break

    objective_value = float(objective.Value())
    resources_used: Dict[str, float] = {k: 0.0 for k in resource_keys}
    gaps: Dict[str, float] = {}
    for i in range(n):
        rv = action_resource_vector(actions[assignment[i]])
        for r in resource_keys:
            resources_used[r] += getattr(rv, r)
    for r, cap in capacity.items():
        if cap is not None and cap > 0:
            gaps[r] = resources_used.get(r, 0.0) / cap

    return SolverResult(
        status=str(status),
        optimal=(status == pywraplp.Solver.OPTIMAL),
        objective=objective_value,
        assignment=assignment,
        resources_used=resources_used,
        gaps=gaps,
    )


def brute_force_solve(
    ev_matrix: np.ndarray,
    actions: Sequence[Action],
    capacity: Dict[str, Optional[float]],
) -> Tuple[float, np.ndarray]:
    """Exhaustive optimal solution for tiny instances (testing the ILP)."""
    n, m = ev_matrix.shape
    if n > 8 or m > 6:
        raise ValueError("brute_force_solve limited to <=8 txns and <=6 actions")
    resource_keys = ["retry", "messaging", "incentive", "human"]
    best_obj = -np.inf
    best = np.zeros(n, dtype=int)

    def feasible(assign: np.ndarray) -> bool:
        used = {r: 0.0 for r in resource_keys}
        for i in range(n):
            rv = action_resource_vector(actions[assign[i]])
            for r in resource_keys:
                used[r] += getattr(rv, r)
        for r in resource_keys:
            cap = capacity.get(r)
            if cap is not None and used[r] > cap + 1e-9:
                return False
        return True

    def dfs(i: int, assign: np.ndarray, obj: float) -> None:
        nonlocal best_obj, best
        if i == n:
            if feasible(assign):
                if obj > best_obj:
                    best_obj = obj
                    best = assign.copy()
            return
        for j in range(m):
            assign[i] = j
            dfs(i + 1, assign, obj + float(ev_matrix[i, j]))
        assign[i] = -1

    dfs(0, np.full(n, -1, dtype=int), 0.0)
    if best_obj == -np.inf:
        raise ValueError("Brute force found no feasible solution")
    return float(best_obj), best