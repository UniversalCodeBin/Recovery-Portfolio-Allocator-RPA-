"""RPA Step 3 — Backend decision pipeline.

Components: prediction service, expected-value engine, policy engine, RPA
optimizer, strategy comparison, execution simulator, verification layer,
audit trail, batch orchestrator, FastAPI MVP API.
"""

from rpa.config import (
    DEFAULT_MODEL_IDENTIFIER,
    EV_ENGINE_VERSION,
    OPTIMIZER_VERSION,
    POLICY_VERSION,
    SIMULATOR_VERSION,
    VERIFICATION_VERSION,
)
from rpa.ev_engine import EVEngine, EVRow, EVTable
from rpa.execution_simulator import ExecutionResult, ExecutionSimulator
from rpa.optimizer import Optimizer, PortfolioPlan, ev_per_resource_greedy
from rpa.orchestrator import (
    BatchResult,
    RPABatchOrchestrator,
    load_batch_result,
    run_batch_on_split,
)
from rpa.policy_engine import PolicyEngine, PolicyVerdict
from rpa.prediction_service import PredictionResult, PredictionService
from rpa.strategies import (
    STRATEGY_NAMES,
    RuleBasedEngine,
    StrategyConfig,
    StrategyRunner,
)
from rpa.verification import VerificationLayer, VerificationResult

__version__ = "0.3.0"
__all__ = [
    "DEFAULT_MODEL_IDENTIFIER",
    "EV_ENGINE_VERSION",
    "OPTIMIZER_VERSION",
    "POLICY_VERSION",
    "SIMULATOR_VERSION",
    "STRATEGY_NAMES",
    "VERIFICATION_VERSION",
    "BatchResult",
    "EVEngine",
    "EVRow",
    "EVTable",
    "ExecutionResult",
    "ExecutionSimulator",
    "Optimizer",
    "PolicyEngine",
    "PolicyVerdict",
    "PortfolioPlan",
    "PredictionResult",
    "PredictionService",
    "RPABatchOrchestrator",
    "RuleBasedEngine",
    "StrategyConfig",
    "StrategyRunner",
    "VerificationLayer",
    "VerificationResult",
    "ev_per_resource_greedy",
    "load_batch_result",
    "run_batch_on_split",
]
