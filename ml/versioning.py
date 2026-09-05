"""Model versioning.

Each prediction record carries a ``model_identifier`` so historical
prediction rows can always be attributed to a specific frozen model.

A *model version* is a string of the form ``"<prefix>-<group>-v<n>"`` where:

* ``prefix``     — typically ``rpa-recovery-logreg`` (configurable);
* ``group``      — one of the ablation keys (``A_basic``, ``B_customer``,
                   ``C_action``, ``D_interactions``) or ``full`` for the
                   production model that combines all groups;
* ``n``          — monotonic integer; bumped when the same logical model is
                   retrained.

Helpers here centralize the construction so all prediction records use a
consistent format and a single source of truth for the prefix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import DEFAULT_MODEL_VERSION, MODELS_DIR

_VERSION_RE = re.compile(r"^(?P<prefix>[a-z0-9\-]+)-(?P<group>[a-z_]+)-v(?P<n>\d+)$")


@dataclass(frozen=True)
class ModelVersion:
    prefix: str
    group: str
    n: int

    @property
    def identifier(self) -> str:
        return f"{self.prefix}-{self.group}-v{self.n}"

    @staticmethod
    def parse(identifier: str) -> "ModelVersion":
        m = _VERSION_RE.match(identifier)
        if not m:
            raise ValueError(f"invalid model identifier: {identifier!r}")
        return ModelVersion(prefix=m.group("prefix"), group=m.group("group"), n=int(m.group("n")))


def default_version(group: str = "full", n: int = 1) -> str:
    """Build a default model identifier for the production model.

    The prefix defaults to ``DEFAULT_MODEL_VERSION`` ("rpa-recovery-logreg-v1"
    minus the trailing ``-v1``). To keep things explicit we use a fresh
    identifier ``rpa-recovery-logreg-<group>-v1``.
    """
    prefix = DEFAULT_MODEL_VERSION.rsplit("-v", 1)[0]  # "rpa-recovery-logreg"
    return ModelVersion(prefix=prefix, group=group, n=n).identifier


def artifact_paths(model_id: str, base_dir: Optional[Path] = None) -> dict:
    """Return canonical artifact paths for a given model identifier."""
    base = base_dir or MODELS_DIR
    safe = model_id.replace("/", "_")
    return {
        "model_dir": base / safe,
        "model_pkl": base / safe / "model.pkl",
        "preprocessor_pkl": base / safe / "preprocessor.pkl",
        "calibrator_pkl": base / safe / "calibrator.pkl",
        "feature_spec_json": base / safe / "feature_spec.json",
        "feature_names_json": base / safe / "feature_names.json",
        "coefficients_csv": base / safe / "coefficients.csv",
        "metadata_json": base / safe / "metadata.json",
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "ModelVersion",
    "default_version",
    "artifact_paths",
    "now_iso",
]
