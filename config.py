"""Centralized configuration for the RPA validation experiment.

All tunable constants, resource limits, action costs, seeds and dataset
sizes live here so the experiment is fully configurable from one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Action(str, Enum):
    """Candidate recovery actions available to the allocator."""

    NO_INTERVENTION = "no_intervention"
    RETRY = "retry"
    PAYMENT_LINK = "payment_link"
    CUSTOMER_MESSAGE = "customer_message"
    INCENTIVE = "incentive"
    HUMAN_ESCALATION = "human_escalation"


class Resource(str, Enum):
    """Shared resources that can bind across transactions."""

    RETRY = "retry"            # retry capacity (count of retries)
    MESSAGING = "messaging"    # message send capacity (count)
    INCENTIVE_BUDGET = "incentive_budget"  # total rupee budget
    HUMAN_SLOTS = "human_slots"  # count of human escalation slots


# ---------------------------------------------------------------------------
# Dataset composition
# ---------------------------------------------------------------------------
DATA_SEED: int = 42                  # master seed for data generation
N_TRAIN: int = 280                    # training records
N_VAL: int = 80                       # validation records
N_TEST: int = 100                     # test records
N_DEMO_POOL: int = 150                # held-out demo transaction pool size
N_DEMO_BATCH: int = 120               # transactions per demo batch (<= N_DEMO_POOL)
N_EXPERIMENT_SEEDS: int = 20          # independent seeded demo batches

# Feature / categorical vocabulary
PAYMENT_METHODS: List[str] = ["upi", "credit_card", "debit_card", "net_banking"]
BANKS: List[str] = ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Yes"]
FAILURE_REASONS: List[str] = [
    "insufficient_funds",
    "invalid_pin",
    "network_timeout",
    "bank_down",
    "limit_exceeded",
    "expired_card",
]

# Amount distribution lognormal params (INR)
AMOUNT_LOG_MEAN: float = 7.5
AMOUNT_LOG_SIGMA: float = 1.3


# ---------------------------------------------------------------------------
# Ground-truth generative model parameters (hidden from strategies/model).
# These define P(recovery | features, action) used to simulate outcomes.
# ---------------------------------------------------------------------------
@dataclass
class GroundTruthParams:
    """Logistic coefficients for the hidden generative model.

    logit(P) = intercept + sum(beta_k * feature_k) + action_effect[j]
    """

    intercept: float = -2.2
    beta_amount: float = 0.35          # higher value -> slightly higher base recovery
    beta_success: float = 2.4          # strong: historically-successful pay more
    beta_overdue: float = -0.15        # more overdue -> harder to recover (per 30d)
    beta_ltv: float = 0.20
    beta_behavior: float = -0.8        # riskier behavior -> lower base recovery
    beta_retry_count: float = -0.25    # already retried a lot -> lower odds
    action_effect: Dict[str, float] = field(
        default_factory=lambda: {
            Action.NO_INTERVENTION.value: 0.0,
            Action.RETRY.value: 0.6,
            Action.PAYMENT_LINK.value: 0.9,
            Action.CUSTOMER_MESSAGE.value: 0.7,
            Action.INCENTIVE.value: 1.3,
            Action.HUMAN_ESCALATION.value: 2.0,
        }
    )


# ---------------------------------------------------------------------------
# Action economics: cost (rupees) and per-action resource consumption.
# ---------------------------------------------------------------------------
@dataclass
class ActionSpec:
    """Cost, resource consumption and utility of a single action."""

    # cost in rupees of applying the action
    rupee_cost: float = 0.0
    # per-application consumption of each resource (0 => no consumption)
    res_retry: float = 0.0
    res_messaging: float = 0.0
    res_incentive: float = 0.0        # rupees of incentive budget
    res_human: float = 0.0            # human slots


ACTION_SPECS: Dict[Action, ActionSpec] = {
    Action.NO_INTERVENTION: ActionSpec(rupee_cost=0.0),
    Action.RETRY: ActionSpec(
        rupee_cost=1.0, res_retry=1.0
    ),
    Action.PAYMENT_LINK: ActionSpec(
        rupee_cost=2.0, res_messaging=1.0
    ),
    Action.CUSTOMER_MESSAGE: ActionSpec(
        rupee_cost=0.5, res_messaging=1.0
    ),
    Action.INCENTIVE: ActionSpec(
        rupee_cost=25.0,
        res_incentive=50.0,   # incentive value given to customer (budget rupee)
        res_messaging=1.0,    # must message to deliver incentive
    ),
    Action.HUMAN_ESCALATION: ActionSpec(
        rupee_cost=40.0,
        res_human=1.0,
        res_messaging=1.0,    # human uses messaging channel to reach out
    ),
}

# Actions that consume messaging capacity (for utilization reporting)
MESSAGING_ACTIONS: List[Action] = [
    Action.PAYMENT_LINK,
    Action.CUSTOMER_MESSAGE,
    Action.INCENTIVE,
    Action.HUMAN_ESCALATION,
]


# ---------------------------------------------------------------------------
# Scenario resource limits.
# Each scenario fixes capacities; at least one resource is expected to bind
# (verified empirically at runtime by the experiment orchestrator).
# "None" capacity means unlimited.
# ---------------------------------------------------------------------------
@dataclass
class Scenario:
    name: str
    description: str
    incentive_budget: Optional[float]
    human_slots: Optional[int]
    messaging_capacity: Optional[int]
    retry_capacity: Optional[int]


@dataclass
class PerActionConsumption:
    """Vector of resource units consumed by a single application of an action."""

    retry: float = 0.0
    messaging: float = 0.0
    incentive: float = 0.0
    human: float = 0.0


def action_consumption(action: Action) -> PerActionConsumption:
    spec = ACTION_SPECS[action]
    return PerActionConsumption(
        retry=spec.res_retry,
        messaging=spec.res_messaging,
        incentive=spec.res_incentive,
        human=spec.res_human,
    )


# Resource limits chosen as fractions of the demo batch size so that the
# specific resource binds. These are set on generative-design grounds
# (e.g., "only ~35% of transactions can get an incentive"), not tuned on
# test outcomes.
_M = 100  # reference batch size for defining fractions
SCENARIOS: Dict[str, Scenario] = {
    "A": Scenario(
        name="A",
        description="Single resource constraint: only incentive budget binds.",
        incentive_budget=35 * 50,   # ~35 incentives worth
        human_slots=None,
        messaging_capacity=None,
        retry_capacity=None,
    ),
    "B": Scenario(
        name="B",
        description="Two simultaneous binding resources: incentive + human.",
        incentive_budget=40 * 50,
        human_slots=int(0.12 * _M),   # 12 human slots (binds)
        messaging_capacity=None,
        retry_capacity=None,
    ),
    "C": Scenario(
        name="C",
        description="Three simultaneous binding resources: incentive + human + messaging.",
        incentive_budget=40 * 50,
        human_slots=int(0.08 * _M),   # 8 human slots (binds)
        messaging_capacity=int(0.60 * _M),  # messaging can cover 60% of batch
        retry_capacity=None,
    ),
    "D": Scenario(
        name="D",
        description="Tight-resource stress test: very limited capacity overall.",
        incentive_budget=12 * 50,
        human_slots=int(0.05 * _M),
        messaging_capacity=int(0.25 * _M),
        retry_capacity=int(0.20 * _M),
    ),
    "E": Scenario(
        name="E",
        description="Relaxed resources: abundant capacity, few/none bind.",
        incentive_budget=10_000,
        human_slots=500,
        messaging_capacity=10_000,
        retry_capacity=10_000,
    ),
}

# Minimum number of distinct resources that must bind for RPA to have a
# fighting chance; the experiment asserts this per scenario (excluding E).
MIN_BINDING_RESOURCES: int = 2
# Scenario E is intentionally used to confirm RPA's advantage can disappear.
RELAXED_SCENARIO: str = "E"


# A single GroundTruthParams instance used throughout (hidden from strategies).
GROUND_TRUTH: GroundTruthParams = GroundTruthParams()


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
MODEL_SEED: int = 123
LOGREG_C: float = 1.0
LOGREG_MAX_ITER: int = 2000
CALIBRATION_METHOD: str = "isotonic"   # "sigmoid" | "isotonic" | "none"
# Probability floor to avoid undefined log-odds / division by zero.
PROB_EPS: float = 1e-6

# Numeric columns that enter the model (raw, before standardization).
# Model does its own standardization internally (frozen preprocessor).
NUMERIC_FEATURES: List[str] = [
    "amount",
    "retry_count",
    "days_overdue",
    "customer_ltv",
    "historical_success_rate",
    "historical_recovery_rate",
    "customer_behavior_score",
]

CATEGORICAL_FEATURES: List[str] = [
    "payment_method",
    "bank",
    "failure_reason",
]


# ---------------------------------------------------------------------------
# Strategy parameters (fixed rule)
# ---------------------------------------------------------------------------
RULE_HIGH_AMOUNT: float = 5000.0
RULE_MID_AMOUNT: float = 1500.0
RULE_SUCESS_THRESHOLD: float = 0.4
RULE_OVERDUE_HIGH: int = 30
RULE_OVERDUE_MID: int = 7
RULE_MAX_RETRIES: int = 2
RULE_SUCCESS_MIN: float = 0.6


# ---------------------------------------------------------------------------
# Output / reporting
# ---------------------------------------------------------------------------
RESULTS_DIR: str = "results"
PLOTS_DIR: str = "results/plots"
REPORT_PATH: str = "results/experiment_report.md"
TABLE_PATH: str = "results/strategy_comparison.csv"
BINDING_ANALYSIS_PATH: str = "results/binding_analysis.csv"

# Aggregation stats to report across seeds
AGG_STATS: List[str] = ["mean", "std", "median", "min", "max"]
CI_ALPHA: float = 0.05   # 95% CI

# Outcome simulation latency (for notes)
OUTCOME_PRNG_PREFIX: str = "outcome"


def action_order() -> List[Action]:
    return list(Action)


def candidate_actions(exclude: Optional[Tuple[Action, ...]] = None) -> List[Action]:
    acts = action_order()
    if exclude:
        acts = [a for a in acts if a not in exclude]
    return acts
