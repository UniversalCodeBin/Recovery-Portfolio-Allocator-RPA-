"""Centralized configuration for the Step 2 ML / feature-engineering layer.

Defines:

* model versioning prefix and seed
* logistic regression hyperparameters
* calibration candidates (chosen on validation)
* artifact paths (models, preprocessing, metrics, ablation, predictions)
* DB table name for prediction persistence
* feature engineering toggles (interactions on/off, ablation groups)

Step 2 deliberately does NOT import the experiment's hidden ground-truth model,
optimizer, strategies or scenarios. It depends only on the Step 1 data
foundation (``data_core``) and the existing top-level ``config`` (for stable
vocabulary: ``Action``, ``Resource``, ``PAYMENT_METHODS``, ``BANKS``,
``FAILURE_REASONS``, ``ACTION_SPECS``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List

from config import Action, Resource

from data_core.config import (
    REPORTS_DIR,
    ROOT_DIR,
    SPLITS_DIR,
    VALIDATED_DIR,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ML_DIR: Path = ROOT_DIR / "ml"
ARTIFACTS_DIR: Path = ROOT_DIR / "artifacts"
MODELS_DIR: Path = ARTIFACTS_DIR / "models"
PREPROCESSING_DIR: Path = ARTIFACTS_DIR / "preprocessing"
REPORTS_ML_DIR: Path = REPORTS_DIR / "model_metrics"
REPORTS_ABLATION_DIR: Path = REPORTS_DIR / "feature_ablation"
PREDICTIONS_DIR: Path = ARTIFACTS_DIR / "predictions"

for _d in (ARTIFACTS_DIR, MODELS_DIR, PREPROCESSING_DIR, REPORTS_ML_DIR, REPORTS_ABLATION_DIR, PREDICTIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED: int = 1234
DEFAULT_MODEL_VERSION: str = "rpa-recovery-logreg-v1"


# ---------------------------------------------------------------------------
# Model hyperparameters (Logistic Regression)
# ---------------------------------------------------------------------------
LOGREG_C: float = 1.0
LOGREG_MAX_ITER: int = 2000
LOGREG_SOLVER: str = "lbfgs"
LOGREG_CLASS_WEIGHT: str | None = None  # set to "balanced" only if needed & measured

# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
class CalibrationMethod(str, Enum):
    NONE = "none"
    SIGMOID = "sigmoid"   # Platt scaling
    ISOTONIC = "isotonic"


CALIBRATION_CANDIDATES: List[str] = ["sigmoid", "isotonic", "none"]


# ---------------------------------------------------------------------------
# Feature engineering toggles
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureFlags:
    """Toggles for optional feature groups (used by feature ablation)."""

    transaction: bool = True
    customer: bool = True
    temporal: bool = True
    payment: bool = True
    action: bool = True
    interactions: bool = True


@dataclass(frozen=True)
class AblationSpec:
    """One ablation configuration: which groups are enabled."""

    name: str
    description: str
    flags: FeatureFlags


ABLATION_SPECS: Dict[str, AblationSpec] = {
    "A_basic": AblationSpec(
        name="A_basic",
        description="Transaction + payment + failure features only.",
        flags=FeatureFlags(transaction=True, customer=False, temporal=False,
                           payment=True, action=False, interactions=False),
    ),
    "B_customer": AblationSpec(
        name="B_customer",
        description="A_basic + customer-history features.",
        flags=FeatureFlags(transaction=True, customer=True, temporal=False,
                           payment=True, action=False, interactions=False),
    ),
    "C_action": AblationSpec(
        name="C_action",
        description="B_customer + temporal + action-conditioned features.",
        flags=FeatureFlags(transaction=True, customer=True, temporal=True,
                           payment=True, action=True, interactions=False),
    ),
    "D_interactions": AblationSpec(
        name="D_interactions",
        description="Full model: all groups + interaction features.",
        flags=FeatureFlags(transaction=True, customer=True, temporal=True,
                           payment=True, action=True, interactions=True),
    ),
}


# ---------------------------------------------------------------------------
# Target / outcome interpretation
# ---------------------------------------------------------------------------
# An "action outcome" row is interpreted as: a recovery attempt occurred for
# (transaction, action). recovered = 1 iff (recovery_status in {recovered,
# partial}) AND recovered_amount > 0. A transaction without an outcome row
# for the action is labeled 0 (no attempt -> no recovery observed).
RECOVERED_STATUSES: List[str] = ["recovered", "partial"]


# ---------------------------------------------------------------------------
# DB persistence (recovery_predictions table created in Step 1)
# ---------------------------------------------------------------------------
DB_PREDICTIONS_TABLE: str = "recovery_predictions"

# ---------------------------------------------------------------------------
# Logging / reporting
# ---------------------------------------------------------------------------
STEP2_REPORT_PATH: Path = REPORTS_DIR / "step2_report.md"
STEP2_REPORT_JSON_PATH: Path = REPORTS_DIR / "step2_report.json"


__all__ = [
    "ML_DIR",
    "ARTIFACTS_DIR",
    "MODELS_DIR",
    "PREPROCESSING_DIR",
    "REPORTS_ML_DIR",
    "REPORTS_ABLATION_DIR",
    "PREDICTIONS_DIR",
    "RANDOM_SEED",
    "DEFAULT_MODEL_VERSION",
    "LOGREG_C",
    "LOGREG_MAX_ITER",
    "LOGREG_SOLVER",
    "LOGREG_CLASS_WEIGHT",
    "CalibrationMethod",
    "CALIBRATION_CANDIDATES",
    "FeatureFlags",
    "AblationSpec",
    "ABLATION_SPECS",
    "RECOVERED_STATUSES",
    "DB_PREDICTIONS_TABLE",
    "STEP2_REPORT_PATH",
    "STEP2_REPORT_JSON_PATH",
]
