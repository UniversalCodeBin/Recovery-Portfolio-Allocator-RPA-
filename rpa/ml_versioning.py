"""ML model versioning and artifact management.

Provides:
- Model registry integration
- Artifact integrity verification (SHA256)
- Feature schema versioning
- Calibration metadata tracking
- Model loading with fallback
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rpa.config import DEFAULT_MODEL_IDENTIFIER, MODELS_DIR
from rpa.settings import get_settings

logger = logging.getLogger(__name__)


class ModelError(Exception):
    """Model loading or validation error."""


class ModelNotFoundError(ModelError):
    """Model artifact not found."""


class ModelIntegrityError(ModelError):
    """Model artifact integrity check failed."""


@dataclass(frozen=True)
class ModelArtifact:
    """Metadata about a model artifact."""

    model_version: str
    artifact_path: Path
    artifact_sha256: str
    feature_schema_version: str
    preprocessing_version: str
    calibration_metadata: dict[str, Any]
    training_metadata: dict[str, Any]
    created_at: datetime


def compute_artifact_sha256(artifact_path: Path) -> str:
    """Compute SHA256 hash of a model artifact."""
    sha256 = hashlib.sha256()
    with open(artifact_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def load_model_metadata(model_version: str | None = None) -> dict[str, Any]:
    """Load model metadata from artifacts directory."""
    if model_version is None:
        model_version = DEFAULT_MODEL_IDENTIFIER

    model_dir = MODELS_DIR / model_version
    if not model_dir.exists():
        raise ModelNotFoundError(f"Model directory not found: {model_dir}")

    metadata_file = model_dir / "model_metadata.json"
    if not metadata_file.exists():
        raise ModelNotFoundError(f"Model metadata not found: {metadata_file}")

    with open(metadata_file, "r") as f:
        return json.load(f)


def validate_model_artifact(
    model_version: str,
    expected_sha256: str | None = None,
) -> bool:
    """Validate model artifact integrity."""
    get_settings()

    model_dir = MODELS_DIR / model_version
    if not model_dir.exists():
        raise ModelNotFoundError(f"Model directory not found: {model_dir}")

    # Find the main model file
    model_files = list(model_dir.glob("*.joblib")) + list(model_dir.glob("*.pkl"))
    if not model_files:
        raise ModelNotFoundError(f"No model files found in {model_dir}")

    model_file = model_files[0]
    actual_sha256 = compute_artifact_sha256(model_file)

    if expected_sha256 and actual_sha256 != expected_sha256:
        raise ModelIntegrityError(
            f"Model artifact integrity check failed: expected {expected_sha256}, got {actual_sha256}"
        )

    return True


def register_model(
    model_version: str,
    artifact_sha256: str,
    feature_schema_version: str,
    preprocessing_version: str,
    calibration_metadata: dict[str, Any],
    training_metadata: dict[str, Any],
) -> None:
    """Register a model in the database."""
    settings = get_settings()

    if settings.mode == "demo":
        logger.info("Demo mode: skipping model registration for %s", model_version)
        return

    try:
        from rpa.database import ModelRegistryRepository, get_pool, transaction

        pool = get_pool()
        with pool.connection() as conn, transaction(conn):
            ModelRegistryRepository.register(
                conn=conn,
                model_version=model_version,
                artifact_sha256=artifact_sha256,
                feature_schema_version=feature_schema_version,
                preprocessing_version=preprocessing_version,
                calibration_metadata=calibration_metadata,
                training_metadata=training_metadata,
            )

        logger.info("Model registered: %s", model_version)
    except ImportError:
        logger.warning("Database not available, skipping model registration")


def load_model(model_version: str | None = None):
    """Load a model from artifacts directory."""
    if model_version is None:
        model_version = DEFAULT_MODEL_IDENTIFIER

    model_dir = MODELS_DIR / model_version
    if not model_dir.exists():
        raise ModelNotFoundError(f"Model directory not found: {model_dir}")

    # Load metadata
    metadata = load_model_metadata(model_version)

    # Validate artifact if SHA256 is available
    expected_sha256 = metadata.get("artifact_sha256")
    if expected_sha256:
        validate_model_artifact(model_version, expected_sha256)

    # Load the model
    import joblib

    model_files = list(model_dir.glob("*.joblib")) + list(model_dir.glob("*.pkl"))
    if not model_files:
        raise ModelNotFoundError(f"No model files found in {model_dir}")

    model = joblib.load(model_files[0])
    logger.info("Model loaded: %s from %s", model_version, model_files[0])

    return model, metadata


def get_feature_schema_version() -> str:
    """Get the current feature schema version."""
    from ml.config import FeatureFlags

    flags = FeatureFlags()
    # Version based on feature groups enabled
    enabled_groups = sorted(
        [k for k, v in flags.__dict__.items() if v and k.startswith("use_")]
    )
    return f"v1-{len(enabled_groups)}groups"


def get_preprocessing_version() -> str:
    """Get the current preprocessing version."""
    return "v1"


__all__ = [
    "ModelArtifact",
    "ModelError",
    "ModelIntegrityError",
    "ModelNotFoundError",
    "compute_artifact_sha256",
    "get_feature_schema_version",
    "get_preprocessing_version",
    "load_model",
    "load_model_metadata",
    "register_model",
    "validate_model_artifact",
]
