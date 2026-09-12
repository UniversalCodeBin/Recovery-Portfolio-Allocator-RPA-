"""Runtime settings and safe deployment-mode validation for RPA.

Demo mode is deliberately the default for backwards compatibility. Production
mode is opt-in and refuses to start without its database and signing secrets.
This module has no third-party configuration dependency so it can run in the
minimal API environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_local_dotenv() -> None:
    """Load a local `.env` only for developer convenience; deployment uses env."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_dotenv()


@dataclass(frozen=True)
class Settings:
    mode: str
    database_url: str | None
    auth_signing_key: str | None
    auth_issuer: str
    access_token_ttl_seconds: int
    cors_origins: tuple[str, ...]
    request_max_bytes: int
    db_pool_min_size: int
    db_pool_max_size: int
    db_pool_acquire_timeout_seconds: float
    # Webhook security
    webhook_signing_secret: str | None
    webhook_timestamp_tolerance_seconds: int
    # ML model
    model_artifact_path: str
    # Demo mode
    demo_data_path: str

    @property
    def production(self) -> bool:
        return self.mode == "production"


def get_settings() -> Settings:
    mode = os.getenv("RPA_MODE", "demo").strip().lower()
    if mode not in {"demo", "production"}:
        raise RuntimeError("RPA_MODE must be 'demo' or 'production'")
    raw_origins = os.getenv("RPA_CORS_ORIGINS", "http://localhost:5173")
    origins = tuple(
        x.strip() for x in raw_origins.split(",") if x.strip() and x.strip() != "*"
    )
    settings = Settings(
        mode=mode,
        database_url=os.getenv("RPA_DATABASE_URL") or None,
        auth_signing_key=os.getenv("RPA_AUTH_SIGNING_KEY") or None,
        auth_issuer=os.getenv("RPA_AUTH_ISSUER", "rpa"),
        access_token_ttl_seconds=int(os.getenv("RPA_ACCESS_TOKEN_TTL_SECONDS", "900")),
        cors_origins=origins,
        request_max_bytes=int(os.getenv("RPA_REQUEST_MAX_BYTES", "1048576")),
        db_pool_min_size=int(os.getenv("RPA_DB_POOL_MIN_SIZE", "1")),
        db_pool_max_size=int(os.getenv("RPA_DB_POOL_MAX_SIZE", "10")),
        db_pool_acquire_timeout_seconds=float(
            os.getenv("RPA_DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "5")
        ),
        webhook_signing_secret=os.getenv("RPA_WEBHOOK_SIGNING_SECRET") or None,
        webhook_timestamp_tolerance_seconds=int(
            os.getenv("RPA_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "300")
        ),
        model_artifact_path=os.getenv(
            "RPA_MODEL_ARTIFACT_PATH", "artifacts/models/rpa-recovery-logreg-full-v1"
        ),
        demo_data_path=os.getenv("RPA_DEMO_DATA_PATH", "data"),
    )
    if (
        settings.access_token_ttl_seconds < 60
        or settings.access_token_ttl_seconds > 86400
    ):
        raise RuntimeError("RPA_ACCESS_TOKEN_TTL_SECONDS must be between 60 and 86400")
    if settings.request_max_bytes < 1024:
        raise RuntimeError("RPA_REQUEST_MAX_BYTES must be at least 1024")
    if settings.db_pool_min_size < 0 or settings.db_pool_max_size < 1:
        raise RuntimeError("database pool sizes are invalid")
    if settings.db_pool_min_size > settings.db_pool_max_size:
        raise RuntimeError("RPA_DB_POOL_MIN_SIZE cannot exceed RPA_DB_POOL_MAX_SIZE")
    if settings.db_pool_acquire_timeout_seconds <= 0:
        raise RuntimeError("RPA_DB_POOL_ACQUIRE_TIMEOUT_SECONDS must be positive")
    if settings.webhook_timestamp_tolerance_seconds <= 0:
        raise RuntimeError("RPA_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS must be positive")
    if settings.production:
        missing = [
            name
            for name, value in {
                "RPA_DATABASE_URL": settings.database_url,
                "RPA_AUTH_SIGNING_KEY": settings.auth_signing_key,
                "RPA_WEBHOOK_SIGNING_SECRET": settings.webhook_signing_secret,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "production configuration missing: " + ", ".join(missing)
            )
        if len(settings.auth_signing_key or "") < 32:
            raise RuntimeError(
                "RPA_AUTH_SIGNING_KEY must contain at least 32 characters"
            )
        if len(settings.webhook_signing_secret or "") < 32:
            raise RuntimeError(
                "RPA_WEBHOOK_SIGNING_SECRET must contain at least 32 characters"
            )
        if not settings.cors_origins:
            raise RuntimeError(
                "RPA_CORS_ORIGINS must contain at least one explicit origin"
            )
    return settings
