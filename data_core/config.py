"""Centralized configuration for the RPA Step 1 data foundation.

All tunables that affect *data* reproducibility live here: master seeds, dataset
sizes, file paths, allowed category vocabularies, validation thresholds and the
PostgreSQL connection parameters. Database secrets are read from environment
variables (see ``.env.example``); no password is ever hard-coded.

Stable domain constants that are shared with the experiment layer are *reused*
from the top-level ``config`` module so that recovery actions, resources and
categorical vocabularies have a single source of truth:

* ``Action`` / ``Resource`` enumerations
* ``PAYMENT_METHODS``, ``BANKS``, ``FAILURE_REASONS``
* ``AMOUNT_LOG_MEAN`` / ``AMOUNT_LOG_SIGMA`` (amount distribution)
* ``DATA_SEED`` (master data seed)
* ``ACTION_SPECS`` (per-action rupee cost + resource consumption)

Step-2/3-specific configuration (the hidden ground-truth model, the resource
scenarios, model hyper-parameters, strategy rules) is deliberately **not**
imported here so the data layer can evolve independently.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List

from config import (
    ACTION_SPECS,
    AMOUNT_LOG_MEAN,
    AMOUNT_LOG_SIGMA,
    BANKS,
    DATA_SEED,
    FAILURE_REASONS,
    PAYMENT_METHODS,
    Action,
    Resource,
)

# ---------------------------------------------------------------------------
# Project root / canonical paths
# ---------------------------------------------------------------------------
ROOT_DIR: Path = Path(__file__).resolve().parents[1]
DATA_DIR: Path = ROOT_DIR / "data"
RAW_DIR: Path = DATA_DIR / "raw"
CLEANED_DIR: Path = DATA_DIR / "cleaned"
VALIDATED_DIR: Path = DATA_DIR / "validated"
SPLITS_DIR: Path = DATA_DIR / "splits"

REPORTS_DIR: Path = ROOT_DIR / "reports"
DATA_QUALITY_DIR: Path = REPORTS_DIR / "data_quality"

DATABASE_DIR: Path = ROOT_DIR / "database"
SQL_SCHEMA_DIR: Path = DATABASE_DIR / "schema"
SQL_MIGRATIONS_DIR: Path = DATABASE_DIR / "migrations"
SCRIPTS_DIR: Path = ROOT_DIR / "scripts"

DATA_FORMAT: str = "csv"


def _path(dir_: Path, name: str, fmt: str = DATA_FORMAT) -> Path:
    return dir_ / f"{name}.{fmt}"


RAW_PATH: Path = _path(RAW_DIR, "raw_dataset")
CLEANED_PATH: Path = _path(CLEANED_DIR, "cleaned_dataset")
VALIDATED_PATH: Path = _path(VALIDATED_DIR, "validated_dataset")
QUALITY_REPORT_JSON_PATH: Path = DATA_QUALITY_DIR / "data_quality_report.json"
QUALITY_REPORT_MD_PATH: Path = DATA_QUALITY_DIR / "data_quality_report.md"

SPLIT_PATH_TEMPLATE: str = "split_{name}.csv"


# ---------------------------------------------------------------------------
# Reproducibility: seeds
# ---------------------------------------------------------------------------
MASTER_SEED: int = DATA_SEED
DATA_GENERATION_SEED: int = MASTER_SEED
SPLIT_SEED: int = 1009
DEMO_POOL_SEED: int = 2123


# ---------------------------------------------------------------------------
# Dataset sizing (transaction-level counts)
# ---------------------------------------------------------------------------
N_CUSTOMERS: int = 200
CUSTOMERS_PER_TXN_MEAN: float = 1.0
TOTAL_TARGET: int = 2000
N_TRAIN_TXNS_TARGET: int = 800
N_VAL_TXNS_TARGET: int = 400
N_TEST_TXNS_TARGET: int = 400
N_DEMO_TXNS_TARGET: int = 400

TRAIN_FRACTION: float = N_TRAIN_TXNS_TARGET / TOTAL_TARGET
VAL_FRACTION: float = N_VAL_TXNS_TARGET / TOTAL_TARGET
TEST_FRACTION: float = N_TEST_TXNS_TARGET / TOTAL_TARGET
DEMO_FRACTION: float = N_DEMO_TXNS_TARGET / TOTAL_TARGET

SPLIT_NAMES: List[str] = ["train", "val", "test", "demo"]
SPLIT_FRACTIONS: Dict[str, float] = {
    "train": TRAIN_FRACTION,
    "val": VAL_FRACTION,
    "test": TEST_FRACTION,
    "demo": DEMO_FRACTION,
}


# ---------------------------------------------------------------------------
# Categorical vocabularies (domain configuration -- not hard-coded in logic)
# ---------------------------------------------------------------------------
PAYMENT_METHODS_LIST: List[str] = list(PAYMENT_METHODS)
BANKS_LIST: List[str] = list(BANKS)
FAILURE_REASONS_LIST: List[str] = list(FAILURE_REASONS)

CUSTOMER_SEGMENTS: List[str] = ["retail", "business", "enterprise"]
SEGMENT_WEIGHTS: List[float] = [0.70, 0.22, 0.08]

CURRENCIES: List[str] = ["INR"]

TRANSACTION_STATUSES: List[str] = ["failed", "pending", "charged_back"]
TRANSACTION_STATUS_WEIGHTS: List[float] = [0.7, 0.2, 0.1]

RECOVERY_STATUSES: List[str] = ["recovered", "partial", "failed"]

ACTIONS_ENABLED: Dict[str, bool] = {a.value: True for a in Action}
RESOURCE_TYPES: List[str] = [r.value for r in Resource]


class CustomerSegment(str, Enum):
    RETAIL = "retail"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


AMOUNT_MIN: float = 100.0
AMOUNT_MAX: float = 100_000.0

CUSTOMER_LTV_MIN: float = 5_000.0
CUSTOMER_LTV_MAX: float = 1_000_000.0
CUSTOMER_TENURE_MIN_DAYS: int = 1
CUSTOMER_TENURE_MAX_DAYS: int = 365 * 5

DEFAULT_REFERENCE_DATE: str = "2026-09-04"
# Deterministic "as-of" timestamp used in generated audit-log rows so the
# whole dataset (including audit entries) is reproducible for a fixed seed.
AUDIT_TIMESTAMP: str = f"{DEFAULT_REFERENCE_DATE}T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Neutral outcome model (synthetic realization of historical attempts)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OutcomeModelParams:
    base_recovery: Dict[Action, float] = field(default_factory=lambda: {
        Action.NO_INTERVENTION: 0.18,
        Action.RETRY: 0.28,
        Action.PAYMENT_LINK: 0.34,
        Action.CUSTOMER_MESSAGE: 0.30,
        Action.INCENTIVE: 0.40,
        Action.HUMAN_ESCALATION: 0.55,
    })
    beta_success: float = 1.8
    beta_overdue: float = -0.12
    beta_ltv: float = 0.30
    beta_behavior: float = -0.6
    beta_retry: float = -0.30
    amount_log_mean: float = AMOUNT_LOG_MEAN
    amount_log_sigma: float = AMOUNT_LOG_SIGMA
    partial_recovery_low: float = 0.10
    partial_recovery_high: float = 0.60


OUTCOME_MODEL: OutcomeModelParams = OutcomeModelParams()


# ---------------------------------------------------------------------------
# Domain validation thresholds
# ---------------------------------------------------------------------------
class ValidationThresholds:
    AMOUNT_MIN: float = AMOUNT_MIN
    AMOUNT_MAX: float = AMOUNT_MAX
    PROB_MIN: float = 0.0
    PROB_MAX: float = 1.0
    RETRY_MIN: int = 0
    RETRY_MAX: int = 100
    DAYS_OVERDUE_MIN: int = 0
    DAYS_OVERDUE_MAX: int = 365 * 3
    RATE_MIN: float = 0.0
    RATE_MAX: float = 1.0
    LTV_MIN: float = 0.0
    TENURE_MIN: int = 0
    RECOVERED_MIN: float = 0.0
    PROBABILITY_DECIMALS: int = 6


# ---------------------------------------------------------------------------
# PostgreSQL connection (env-driven, no hard-coded secrets)
# ---------------------------------------------------------------------------
DB_HOST: str = os.environ.get("RPA_DB_HOST", "localhost")
DB_PORT: str = os.environ.get("RPA_DB_PORT", "5432")
DB_NAME: str = os.environ.get("RPA_DB_NAME", "rpa")
DB_USER: str = os.environ.get("RPA_DB_USER", "rpa")
DB_PASSWORD: str = os.environ.get("RPA_DB_PASSWORD", "")
DB_SCHEMA: str = os.environ.get("RPA_DB_SCHEMA", "rpa")


def database_url() -> str:
    pw = DB_PASSWORD
    auth = f"{DB_USER}:{pw}" if pw else f"{DB_USER}"
    return f"postgresql://{auth}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
