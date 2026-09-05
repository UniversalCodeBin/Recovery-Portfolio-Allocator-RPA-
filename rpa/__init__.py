"""RPA Step 3 — Backend decision pipeline.

Components: prediction service, expected-value engine, policy engine, RPA
optimizer, strategy comparison, execution simulator, verification layer,
audit trail, batch orchestrator, FastAPI MVP API.
"""
from rpa.config import (
    DEFAULT_MODEL_IDENTIFIER,
    POLICY_VERSION,
    OPTIMIZER_VERSION,
    EV_ENGINE_VERSION,
    SIMULATOR_VERSION,
    VERIFICATION_VERSION,
)
from rpa.ev_engine import EVEngine, EVTable, EVRow
from rpa.execution_simulator import ExecutionSimulator, ExecutionResult
from rpa.optimizer import Optimizer, PortfolioPlan, ev_per_resource_greedy
from rpa.orchestrator import (
    RPABatchOrchestrator,
    BatchResult,
    run_batch_on_split,
    load_batch_result,
)
from rpa.policy_engine import PolicyEngine, PolicyVerdict
from rpa.prediction_service import PredictionService, PredictionResult
from rpa.strategies import StrategyRunner, StrategyConfig, RuleBasedEngine, STRATEGY_NAMES
from rpa.verification import VerificationLayer, VerificationResult

__version__ = "0.3.0"
__all__ = [
    "DEFAULT_MODEL_IDENTIFIER",
    "POLICY_VERSION",
    "OPTIMIZER_VERSION",
    "EV_ENGINE_VERSION",
    "SIMULATOR_VERSION",
    "VERIFICATION_VERSION",
    "EVEngine",
    "EVTable",
    "EVRow",
    "ExecutionSimulator",
    "ExecutionResult",
    "Optimizer",
    "PortfolioPlan",
    "ev_per_resource_greedy",
    "RPABatchOrchestrator",
    "BatchResult",
    "run_batch_on_split",
    "load_batch_result",
    "PolicyEngine",
    "PolicyVerdict",
    "PredictionService",
    "PredictionResult",
    "StrategyRunner",
    "StrategyConfig",
    "RuleBasedEngine",
    "STRATEGY_NAMES",
    "VerificationLayer",
    "VerificationResult",
]