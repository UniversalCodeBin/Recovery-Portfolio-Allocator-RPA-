"""Centralized configuration for the Step 3 backend (RPA decision layer).

This module holds all Step-3 tunables: artifact paths, model identifier,
expected-value formula parameters, policy defaults, optimizer settings,
execution/verification settings and version identifiers.

Configuration-over-hard-coding: every tunable below is a constant that the
tests and the API can override through dependency injection. There are NO
hard-coded economics/limits inside the component modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from data_core.config import ROOT_DIR, VALIDATED_DIR, SPLITS_DIR

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ARTIFACTS_DIR: Path = ROOT_DIR / "artifacts"
MODELS_DIR: Path = ARTIFACTS_DIR / "models"
MODEL_DIR: Path = MODELS_DIR / "rpa-recovery-logreg-full-v1"
PREDICTIONS_DIR: Path = ARTIFACTS_DIR / "predictions"

# Step 3 run / result persistence (JSON "database"-lite; DB optional).
RUNS_DIR: Path = ROOT_DIR / "rpa_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Model / version identifiers
# ---------------------------------------------------------------------------
DEFAULT_MODEL_IDENTIFIER: str = "rpa-recovery-logreg-full-v1"
POLICY_VERSION: str = "policy-v1"
OPTIMIZER_VERSION: str = "optimizer-ilp-cbc-v1"
EV_ENGINE_VERSION: str = "ev-engine-v1"
SIMULATOR_VERSION: str = "simulator-v1"
VERIFICATION_VERSION: str = "verification-v1"

# ---------------------------------------------------------------------------
# Frozen-model feature flags (must match the frozen Step 2 artifact)
# ---------------------------------------------------------------------------
from ml.config import FeatureFlags  # noqa: E402

MODEL_FEATURE_FLAGS: FeatureFlags = FeatureFlags()  # all groups on

# ---------------------------------------------------------------------------
# Expected-value formula.
#
#   EV(action | txn) = P * amount - cost_active
#   recoverable_amount = amount * (1 - recovery_friction)
#
# Costs are additive:
#   total_cost = action_rupee_cost + incentive_cost_component(with fee)
#   gross_expected = P * recoverable_amount
#   net_expected  = gross_expected - total_cost
#
# The incentive "cost" has two parts: the discount given to the customer
# (incentive_budget rupees, from the shared budget) AND a fixed fee for
# running the incentive channel (incentive_handling_fee).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EVEngineConfig:
    recovery_friction: float = 0.0        # fraction of amount not recoverable (default 0)
    incentive_handling_fee: float = 5.0   # per-incentive channel fee (rupees)
    prob_floor: float = 1e-6
    prob_ceil: float = 1.0 - 1e-6

    # rupee cost (handling) of an action is taken from the action's
    # `action_cost` in Step 1 `recovery_actions`; incentive budget is the
    # `incentive_budget` resource requirement of the action.


# ---------------------------------------------------------------------------
# Policy defaults (merchant tunables; each is a documented hard gate).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyConfig:
    min_net_ev_threshold: float = 0.0        # reject interventions with EV < this
    max_incentive_per_transaction: Optional[float] = 5000.0  # never exceed
    max_messages_per_batch: Optional[int] = None    # 0 => unlimited
    max_human_slots_per_batch: Optional[int] = None # 0 => unlimited
    max_retries_per_transaction: int = 2      # retry limit per transaction
    prohibit_combination: List[str] = field(default_factory=lambda: [
        # e.g. ["incentive", "human_escalation"] would forbid using both on
        # one transaction; left empty by default (one action per txn already).
    ])
    # Actions that are NEVER allowed to be selected (hard block).
    blocked_actions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Optimizer settings
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OptimizerConfig:
    solver: str = "CBC"
    time_limit_seconds: float = 30.0
    # A non-optimal CBC feasible incumbent is not executable by default. A
    # production policy may explicitly opt into it after risk review.
    allow_feasible_solution: bool = False
    # One-action-per-transaction is always enforced.
    enforce_one_action_per_txn: bool = True
    # A no-op action is always available (fallback) so the problem is feasible.
    no_op_action_id: str = "act_no_intervention"
    # Resource keys the optimizer enforces as capacities (subset that binds).
    resource_capacity_keys: List[str] = field(default_factory=lambda: [
        "retry", "messaging", "incentive_budget", "human_slots",
    ])


# ---------------------------------------------------------------------------
# Simulation / outcome assumptions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SimulationConfig:
    # Partial recovery: on success, draw a fraction of amount uniformly in
    # [partial_low, partial_high]. Full recovery => 1.0.
    partial_low: float = 0.0
    partial_high: float = 1.0
    # Success probability FUNCTION: P(success | p_pred) = p_pred (identity here;
    # configurable so outcome assumptions are explicit and shared).
    seed_salt: str = "rpa-sim"


# ---------------------------------------------------------------------------
# Default resource limits used when the caller does not supply any.
# These mirror Step 1 `resource_constraints.csv` (the shared batch budget).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResourceLimits:
    incentive_budget: Optional[float] = 5000.0
    human_slots: Optional[int] = 50
    messaging: Optional[int] = 2000
    retry: Optional[int] = 2000


def default_resource_limits() -> Dict[str, Optional[float]]:
    return {
        "incentive_budget": ResourceLimits.incentive_budget,
        "human_slots": ResourceLimits.human_slots,
        "messaging": ResourceLimits.messaging,
        "retry": ResourceLimits.retry,
    }
