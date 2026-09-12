"""Production PostgreSQL database layer for RPA.

Provides:
- Connection pooling with psycopg3
- Transaction management with context managers
- Migration runner with version tracking
- Repository pattern for type-safe data access
- Atomic resource reservation with SELECT FOR UPDATE
"""

from __future__ import annotations

import builtins
import contextlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

from rpa.settings import get_settings

# psycopg_pool is optional — demo mode works without it.
try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    _HAS_DB = True
except ImportError:
    psycopg = None  # type: ignore
    sql = None  # type: ignore
    dict_row = None  # type: ignore
    ConnectionPool = None  # type: ignore
    _HAS_DB = False

logger = logging.getLogger(__name__)

SCHEMA = "rpa"
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database" / "migrations"


@dataclass(frozen=True)
class PoolConfig:
    min_size: int
    max_size: int
    acquire_timeout: float
    kwargs: dict[str, Any]


class DatabaseError(Exception):
    """Database operation failed."""


class MigrationError(DatabaseError):
    """Migration failed."""


class ResourceExhaustedError(DatabaseError):
    """Insufficient resources for operation."""


class IdempotencyConflictError(DatabaseError):
    """Duplicate idempotency key."""


class TenantNotFoundError(DatabaseError):
    """Tenant not found."""


class OptimisticLockError(DatabaseError):
    """Concurrent modification detected."""


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _build_pool_config() -> PoolConfig:
    settings = get_settings()
    return PoolConfig(
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        acquire_timeout=settings.db_pool_acquire_timeout_seconds,
        kwargs={
            "application_name": "rpa-api",
            "row_factory": dict_row,
            "autocommit": False,
        },
    )


def get_pool():
    """Get or create the global connection pool."""
    global _pool
    if not _HAS_DB:
        raise DatabaseError(
            "psycopg_pool not installed. Install with: pip install psycopg_pool\n"
            "Or set RPA_MODE=demo to run without a database."
        )
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                config = _build_pool_config()
                if not get_settings().database_url:
                    raise DatabaseError("RPA_DATABASE_URL not configured")
                _pool = ConnectionPool(
                    get_settings().database_url,
                    min_size=config.min_size,
                    max_size=config.max_size,
                    timeout=config.acquire_timeout,
                    kwargs=config.kwargs,
                    open=True,
                )
                logger.info(
                    "Database pool created: min=%d max=%d",
                    config.min_size,
                    config.max_size,
                )
    return _pool


def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
            logger.info("Database pool closed")


@contextlib.contextmanager
def connection():
    """Acquire a connection from the pool."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextlib.contextmanager
def transaction(conn=None):
    """Transaction context manager. Commits on success, rolls back on exception."""
    owns_conn = conn is None
    if owns_conn:
        conn = get_pool().getconn()
    try:
        with conn.transaction():
            yield conn
    finally:
        if owns_conn:
            get_pool().putconn(conn)


def run_migrations(conn=None):
    """Run all pending migrations in lexical order. Returns list of applied versions."""
    applied: list = []

    def _run(conn) -> list:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{SCHEMA}".schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """
            )
            cur.execute(f'SELECT version FROM "{SCHEMA}".schema_migrations')
            already_applied = {row["version"] for row in cur.fetchall()}

        migration_files = sorted(MIGRATIONS_DIR.glob("V*.sql"))
        for mig_file in migration_files:
            version = mig_file.stem
            if version in already_applied:
                logger.debug("Migration %s already applied", version)
                continue
            logger.info("Applying migration %s", version)
            sql_text = mig_file.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql_text)
                cur.execute(
                    f'INSERT INTO "{SCHEMA}".schema_migrations (version) VALUES (%s)',
                    (version,),
                )
            applied.append(version)
        return applied

    if conn is not None:
        return _run(conn)
    else:
        with transaction() as migration_conn:
            return _run(migration_conn)


def _qualified(table: str) -> sql.Identifier:
    return sql.Identifier(SCHEMA, table)


# ---------------------------------------------------------------------------
# Repository classes
# ---------------------------------------------------------------------------


class TenantRepository:
    """Tenant management."""

    @staticmethod
    def create(
        conn: psycopg.Connection, name: str, tenant_id: UUID | None = None
    ) -> UUID:
        tid = tenant_id or uuid4()
        with conn.cursor() as cur:
            cur.execute(
                f'INSERT INTO "{SCHEMA}".tenants (tenant_id, name) VALUES (%s, %s)',
                (str(tid), name),
            )
        return tid

    @staticmethod
    def get(conn: psycopg.Connection, tenant_id: UUID) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".tenants WHERE tenant_id = %s',
                (str(tenant_id),),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def list(conn: psycopg.Connection) -> builtins.list[dict]:
        with conn.cursor() as cur:
            cur.execute(f'SELECT * FROM "{SCHEMA}".tenants ORDER BY created_at DESC')
            return cur.fetchall()  # type: ignore[return-value]


class UserRepository:
    """User management with password hashing."""

    @staticmethod
    def create(
        conn: psycopg.Connection,
        tenant_id: UUID,
        email: str,
        password_hash: str,
        role: str,
    ) -> UUID:
        uid = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".users (user_id, tenant_id, email, password_hash, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (str(uid), str(tenant_id), email, password_hash, role),
            )
        return uid

    @staticmethod
    def get_by_email(
        conn: psycopg.Connection, tenant_id: UUID, email: str
    ) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM "{SCHEMA}".users
                WHERE tenant_id = %s AND email = %s AND active = TRUE
                """,
                (str(tenant_id), email),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def get(conn: psycopg.Connection, user_id: UUID) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".users WHERE user_id = %s',
                (str(user_id),),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def list(conn: psycopg.Connection, tenant_id: UUID) -> builtins.list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".users WHERE tenant_id = %s ORDER BY created_at DESC',
                (str(tenant_id),),
            )
            return cur.fetchall()  # type: ignore[return-value]


class RevokedTokenRepository:
    """Token revocation list."""

    @staticmethod
    def add(
        conn: psycopg.Connection, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".revoked_tokens (token_id, user_id, expires_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (token_id) DO NOTHING
                """,
                (str(token_id), str(user_id), expires_at),
            )

    @staticmethod
    def is_revoked(conn: psycopg.Connection, token_id: UUID) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT 1 FROM "{SCHEMA}".revoked_tokens
                WHERE token_id = %s AND expires_at > now()
                """,
                (str(token_id),),
            )
            return cur.fetchone() is not None

    @staticmethod
    def cleanup_expired(conn: psycopg.Connection) -> int:
        with conn.cursor() as cur:
            cur.execute(
                f'DELETE FROM "{SCHEMA}".revoked_tokens WHERE expires_at <= now()'
            )
            return cur.rowcount


class ResourceReservationRepository:
    """Atomic resource reservation with SELECT FOR UPDATE."""

    RESOURCE_TYPES = ("retry", "messaging", "incentive_budget", "human_slots")

    @staticmethod
    def get_tenant_limits(
        conn: psycopg.Connection, tenant_id: UUID
    ) -> dict[str, float]:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT resource_type, limit_value
                FROM "{SCHEMA}".tenant_resource_limits
                WHERE tenant_id = %s
                """,
                (str(tenant_id),),
            )
            return {
                row["resource_type"]: float(row["limit_value"])  # type: ignore[call-overload]
                for row in cur.fetchall()
            }

    @staticmethod
    def set_tenant_limit(
        conn: psycopg.Connection,
        tenant_id: UUID,
        resource_type: str,
        limit_value: float,
    ) -> None:
        if resource_type not in ResourceReservationRepository.RESOURCE_TYPES:
            raise ValueError(f"Invalid resource type: {resource_type}")
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".tenant_resource_limits (tenant_id, resource_type, limit_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, resource_type) DO UPDATE SET
                    limit_value = EXCLUDED.limit_value,
                    updated_at = now()
                """,
                (str(tenant_id), resource_type, limit_value),
            )

    @staticmethod
    def reserve(
        conn: psycopg.Connection,
        tenant_id: UUID,
        job_id: UUID,
        resources: dict[str, float],
    ) -> list[UUID]:
        """Atomically reserve resources. Raises ResourceExhaustedError if insufficient."""
        reservation_ids = []
        for resource_type, amount in resources.items():
            if amount <= 0:
                continue
            with conn.cursor() as cur:
                # Lock the tenant limit row
                cur.execute(
                    f"""
                    SELECT limit_value FROM "{SCHEMA}".tenant_resource_limits
                    WHERE tenant_id = %s AND resource_type = %s
                    FOR UPDATE
                    """,
                    (str(tenant_id), resource_type),
                )
                limit_row = cur.fetchone()
                if not limit_row:
                    raise ResourceExhaustedError(
                        f"No limit configured for {resource_type}"
                    )
                limit_value = float(limit_row["limit_value"])  # type: ignore[call-overload]

                # Check current reservations
                cur.execute(
                    f"""
                    SELECT COALESCE(SUM(reserved_amount), 0) as used
                    FROM "{SCHEMA}".resource_reservations
                    WHERE tenant_id = %s AND resource_type = %s
                      AND status IN ('reserved', 'consumed')
                    """,
                    (str(tenant_id), resource_type),
                )
                used_row = cur.fetchone()
                used = float(used_row["used"]) if used_row else 0.0  # type: ignore[call-overload]

                if used + amount > limit_value + 1e-9:
                    raise ResourceExhaustedError(
                        f"Insufficient {resource_type}: limit={limit_value}, used={used}, requested={amount}"
                    )

                rid = uuid4()
                cur.execute(
                    f"""
                    INSERT INTO "{SCHEMA}".resource_reservations
                    (reservation_id, tenant_id, job_id, resource_type, reserved_amount, status)
                    VALUES (%s, %s, %s, %s, %s, 'reserved')
                    """,
                    (str(rid), str(tenant_id), str(job_id), resource_type, amount),
                )
                reservation_ids.append(rid)
        return reservation_ids

    @staticmethod
    def consume(
        conn: psycopg.Connection, job_id: UUID, resource_type: str, amount: float
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE "{SCHEMA}".resource_reservations
                SET status = 'consumed', updated_at = now()
                WHERE job_id = %s AND resource_type = %s AND status = 'reserved'
                """,
                (str(job_id), resource_type),
            )

    @staticmethod
    def release(
        conn: psycopg.Connection, job_id: UUID, resource_type: str | None = None
    ) -> None:
        with conn.cursor() as cur:
            if resource_type:
                cur.execute(
                    f"""
                    UPDATE "{SCHEMA}".resource_reservations
                    SET status = 'released', updated_at = now()
                    WHERE job_id = %s AND resource_type = %s
                      AND status IN ('reserved', 'consumed')
                    """,
                    (str(job_id), resource_type),
                )
            else:
                cur.execute(
                    f"""
                    UPDATE "{SCHEMA}".resource_reservations
                    SET status = 'released', updated_at = now()
                    WHERE job_id = %s AND status IN ('reserved', 'consumed')
                    """,
                    (str(job_id),),
                )

    @staticmethod
    def get_job_reservations(conn: psycopg.Connection, job_id: UUID) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM "{SCHEMA}".resource_reservations
                WHERE job_id = %s
                ORDER BY resource_type
                """,
                (str(job_id),),
            )
            return cur.fetchall()  # type: ignore[return-value]


class RecoveryJobRepository:
    """Recovery job lifecycle management."""

    @staticmethod
    def create(
        conn: psycopg.Connection,
        tenant_id: UUID,
        requested_by: UUID,
        request_payload: dict,
        correlation_id: UUID,
    ) -> UUID:
        job_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".recovery_jobs
                (job_id, tenant_id, requested_by, request_payload, correlation_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    str(job_id),
                    str(tenant_id),
                    str(requested_by),
                    request_payload,
                    str(correlation_id),
                ),
            )
        return job_id

    @staticmethod
    def update_status(
        conn: psycopg.Connection,
        job_id: UUID,
        status: str,
        progress: int = 0,
        error_code: str | None = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE "{SCHEMA}".recovery_jobs
                SET status = %s, progress = %s, error_code = %s, updated_at = now()
                WHERE job_id = %s
                """,
                (status, progress, error_code, str(job_id)),
            )

    @staticmethod
    def get(conn: psycopg.Connection, job_id: UUID) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".recovery_jobs WHERE job_id = %s',
                (str(job_id),),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def list_for_tenant(
        conn: psycopg.Connection, tenant_id: UUID, status: str | None = None
    ) -> list[dict]:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    f"""
                    SELECT * FROM "{SCHEMA}".recovery_jobs
                    WHERE tenant_id = %s AND status = %s
                    ORDER BY created_at DESC
                    """,
                    (str(tenant_id), status),
                )
            else:
                cur.execute(
                    f"""
                    SELECT * FROM "{SCHEMA}".recovery_jobs
                    WHERE tenant_id = %s
                    ORDER BY created_at DESC
                    """,
                    (str(tenant_id),),
                )
            return cur.fetchall()  # type: ignore[return-value]


class ProviderEventRepository:
    """Idempotent webhook event processing."""

    @staticmethod
    def record(
        conn: psycopg.Connection,
        tenant_id: UUID,
        provider: str,
        external_event_id: str,
        event_type: str,
        payload: dict,
    ) -> UUID:
        event_id = uuid4()
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"""
                    INSERT INTO "{SCHEMA}".provider_events
                    (provider_event_id, tenant_id, provider, external_event_id, event_type, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(event_id),
                        str(tenant_id),
                        provider,
                        external_event_id,
                        event_type,
                        payload,
                    ),
                )
            except psycopg.errors.UniqueViolation:
                # Already processed - fetch existing
                cur.execute(
                    f"""
                    SELECT provider_event_id FROM "{SCHEMA}".provider_events
                    WHERE tenant_id = %s AND provider = %s AND external_event_id = %s
                    """,
                    (str(tenant_id), provider, external_event_id),
                )
                row = cur.fetchone()
                if row:
                    return UUID(row["provider_event_id"])  # type: ignore[call-overload]
                raise
        return event_id

    @staticmethod
    def mark_processed(conn: psycopg.Connection, event_id: UUID) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE "{SCHEMA}".provider_events
                SET processed_at = now()
                WHERE provider_event_id = %s
                """,
                (str(event_id),),
            )


class ProductionExecutionRepository:
    """Production execution with idempotency and state machine."""

    VALID_STATES: ClassVar[tuple[str, ...]] = (
        "PLANNED",
        "AUTHORIZED",
        "EXECUTING",
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
    )

    ALLOWED_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "PLANNED": {"AUTHORIZED", "BLOCKED", "CANCELLED"},
        "AUTHORIZED": {"EXECUTING", "BLOCKED", "CANCELLED"},
        "EXECUTING": {"SUCCEEDED", "FAILED", "BLOCKED"},
        "SUCCEEDED": set(),
        "FAILED": set(),
        "BLOCKED": set(),
        "CANCELLED": set(),
    }

    @staticmethod
    def create(
        conn: psycopg.Connection,
        tenant_id: UUID,
        job_id: UUID,
        transaction_id: str,
        idempotency_key: str,
        policy_version: str,
        model_version: str,
        optimizer_version: str,
        decision_expires_at: datetime,
        correlation_id: UUID,
    ) -> UUID:
        exec_id = uuid4()
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"""
                    INSERT INTO "{SCHEMA}".production_executions
                    (execution_id, tenant_id, job_id, transaction_id, idempotency_key,
                     state, policy_version, model_version, optimizer_version,
                     decision_expires_at, correlation_id)
                    VALUES (%s, %s, %s, %s, %s, 'PLANNED', %s, %s, %s, %s, %s)
                    """,
                    (
                        str(exec_id),
                        str(tenant_id),
                        str(job_id),
                        transaction_id,
                        idempotency_key,
                        policy_version,
                        model_version,
                        optimizer_version,
                        decision_expires_at,
                        str(correlation_id),
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                # Check if it's the idempotency key conflict
                cur.execute(
                    f"""
                    SELECT execution_id FROM "{SCHEMA}".production_executions
                    WHERE tenant_id = %s AND idempotency_key = %s
                    """,
                    (str(tenant_id), idempotency_key),
                )
                row = cur.fetchone()
                if row:
                    raise IdempotencyConflictError(
                        f"Execution already exists for idempotency key: {idempotency_key}"
                    ) from exc
                raise
        return exec_id

    @staticmethod
    def transition(
        conn: psycopg.Connection,
        execution_id: UUID,
        target_state: str,
        provider_reference: str | None = None,
    ) -> dict:
        """Atomically transition state with validation. Returns updated row."""
        if target_state not in ProductionExecutionRepository.VALID_STATES:
            raise ValueError(f"Invalid state: {target_state}")

        with conn.cursor() as cur:
            # Lock the row
            cur.execute(
                f"""
                SELECT * FROM "{SCHEMA}".production_executions
                WHERE execution_id = %s FOR UPDATE
                """,
                (str(execution_id),),
            )
            row = cur.fetchone()
            if not row:
                raise DatabaseError(f"Execution not found: {execution_id}")

            current_state = row["state"]  # type: ignore[call-overload]
            if (
                target_state
                not in ProductionExecutionRepository.ALLOWED_TRANSITIONS.get(
                    current_state, set()
                )
            ):
                raise DatabaseError(
                    f"Invalid transition: {current_state} -> {target_state}"
                )

            # Validate preconditions for EXECUTING
            if target_state == "EXECUTING":
                if row["decision_expires_at"] <= datetime.now(timezone.utc):  # type: ignore[call-overload]
                    raise DatabaseError("Decision expired")
                if not row["policy_allowed"]:  # type: ignore[call-overload]
                    raise DatabaseError("Policy not allowed")
                if not row["authorized"]:  # type: ignore[call-overload]
                    raise DatabaseError("Not authorized")
                if not row["resources_reserved"]:  # type: ignore[call-overload]
                    raise DatabaseError("Resources not reserved")

            updates = ["state = %s", "updated_at = now()"]
            params = [target_state]
            if provider_reference:
                updates.append("provider_reference = %s")
                params.append(provider_reference)
            if target_state == "AUTHORIZED":
                updates.append("authorized = TRUE")
            if target_state == "EXECUTING":
                updates.append("resources_reserved = TRUE")

            params.append(str(execution_id))
            cur.execute(
                f"""
                UPDATE "{SCHEMA}".production_executions
                SET {", ".join(updates)}
                WHERE execution_id = %s
                RETURNING *
                """,
                params,
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def get(conn: psycopg.Connection, execution_id: UUID) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".production_executions WHERE execution_id = %s',
                (str(execution_id),),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def get_by_idempotency(
        conn: psycopg.Connection, tenant_id: UUID, idempotency_key: str
    ) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM "{SCHEMA}".production_executions
                WHERE tenant_id = %s AND idempotency_key = %s
                """,
                (str(tenant_id), idempotency_key),
            )
            return cur.fetchone()  # type: ignore[return-value]


class ModelRegistryRepository:
    """Model version registry with artifact integrity."""

    @staticmethod
    def register(
        conn: psycopg.Connection,
        model_version: str,
        artifact_sha256: str,
        feature_schema_version: str,
        preprocessing_version: str,
        calibration_metadata: dict,
        training_metadata: dict,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".model_registry
                (model_version, artifact_sha256, feature_schema_version, preprocessing_version,
                 calibration_metadata, training_metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_version) DO UPDATE SET
                    artifact_sha256 = EXCLUDED.artifact_sha256,
                    feature_schema_version = EXCLUDED.feature_schema_version,
                    preprocessing_version = EXCLUDED.preprocessing_version,
                    calibration_metadata = EXCLUDED.calibration_metadata,
                    training_metadata = EXCLUDED.training_metadata
                """,
                (
                    model_version,
                    artifact_sha256,
                    feature_schema_version,
                    preprocessing_version,
                    calibration_metadata,
                    training_metadata,
                ),
            )

    @staticmethod
    def get(conn: psycopg.Connection, model_version: str) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{SCHEMA}".model_registry WHERE model_version = %s',
                (model_version,),
            )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def validate_artifact(
        conn: psycopg.Connection, model_version: str, sha256: str
    ) -> bool:
        row = ModelRegistryRepository.get(conn, model_version)
        return row is not None and row["artifact_sha256"] == sha256


class AuditRepository:
    """Append-only audit event storage."""

    @staticmethod
    def record(
        conn: psycopg.Connection,
        tenant_id: UUID,
        run_id: str,
        component: str,
        event_type: str,
        entity_id: str | None,
        event_metadata: dict,
        correlation_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> UUID:
        audit_id = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".audit_events
                (audit_id, run_id, tenant_id, component, event_type, entity_id,
                 event_metadata, correlation_id, actor_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(audit_id),
                    run_id,
                    str(tenant_id),
                    component,
                    event_type,
                    entity_id,
                    event_metadata,
                    str(correlation_id) if correlation_id else None,
                    str(actor_user_id) if actor_user_id else None,
                ),
            )
        return audit_id

    @staticmethod
    def get_for_run(
        conn: psycopg.Connection, run_id: str, tenant_id: UUID | None = None
    ) -> list[dict]:
        with conn.cursor() as cur:
            if tenant_id:
                cur.execute(
                    f"""
                    SELECT * FROM "{SCHEMA}".audit_events
                    WHERE run_id = %s AND tenant_id = %s
                    ORDER BY timestamp
                    """,
                    (run_id, str(tenant_id)),
                )
            else:
                cur.execute(
                    f"""
                    SELECT * FROM "{SCHEMA}".audit_events
                    WHERE run_id = %s
                    ORDER BY timestamp
                    """,
                    (run_id,),
                )
            return cur.fetchall()  # type: ignore[return-value]


class RecoveryRunRepository:
    """Recovery run persistence (replaces JSON file storage)."""

    @staticmethod
    def create(
        conn: psycopg.Connection,
        tenant_id: UUID,
        actor_user_id: UUID,
        correlation_id: UUID,
        idempotency_key: str,
        batch_seed: int,
        model_identifier: str,
        resource_limits: dict,
        strategies: list[str],
        simulation: bool = True,
    ) -> str:
        run_id = f"run_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO "{SCHEMA}".recovery_runs
                (run_id, tenant_id, actor_user_id, correlation_id, idempotency_key,
                 status, batch_seed, model_identifier, resource_limits, strategies,
                 simulation, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    str(tenant_id),
                    str(actor_user_id),
                    str(correlation_id),
                    idempotency_key,
                    batch_seed,
                    model_identifier,
                    resource_limits,
                    strategies,
                    simulation,
                    now,
                    now,
                ),
            )
        return run_id

    @staticmethod
    def update_status(
        conn: psycopg.Connection,
        run_id: str,
        status: str,
        error: str | None = None,
        result_payload: dict | None = None,
    ) -> None:
        with conn.cursor() as cur:
            if result_payload:
                cur.execute(
                    f"""
                    UPDATE "{SCHEMA}".recovery_runs
                    SET status = %s, error = %s, result_payload = %s, updated_at = now()
                    WHERE run_id = %s
                    """,
                    (status, error, result_payload, run_id),
                )
            else:
                cur.execute(
                    f"""
                    UPDATE "{SCHEMA}".recovery_runs
                    SET status = %s, error = %s, updated_at = now()
                    WHERE run_id = %s
                    """,
                    (status, error, run_id),
                )

    @staticmethod
    def get(
        conn: psycopg.Connection, run_id: str, tenant_id: UUID | None = None
    ) -> dict | None:
        with conn.cursor() as cur:
            if tenant_id:
                cur.execute(
                    f'SELECT * FROM "{SCHEMA}".recovery_runs WHERE run_id = %s AND tenant_id = %s',
                    (run_id, str(tenant_id)),
                )
            else:
                cur.execute(
                    f'SELECT * FROM "{SCHEMA}".recovery_runs WHERE run_id = %s',
                    (run_id,),
                )
            return cur.fetchone()  # type: ignore[return-value]

    @staticmethod
    def list_for_tenant(
        conn: psycopg.Connection, tenant_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM "{SCHEMA}".recovery_runs
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (str(tenant_id), limit, offset),
            )
            return cur.fetchall()  # type: ignore[return-value]


__all__ = [
    "AuditRepository",
    "DatabaseError",
    "IdempotencyConflictError",
    "MigrationError",
    "ModelRegistryRepository",
    "OptimisticLockError",
    "ProductionExecutionRepository",
    "ProviderEventRepository",
    "RecoveryJobRepository",
    "RecoveryRunRepository",
    "ResourceExhaustedError",
    "ResourceReservationRepository",
    "RevokedTokenRepository",
    "TenantNotFoundError",
    "TenantRepository",
    "UserRepository",
    "close_pool",
    "connection",
    "get_pool",
    "run_migrations",
    "transaction",
]
