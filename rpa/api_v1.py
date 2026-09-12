"""Production v1 API router for RPA.

Provides:
- JWT-authenticated endpoints
- Idempotent recovery job creation
- Webhook ingestion with signature verification
- Tenant-scoped resource management
- Production execution state machine
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from rpa.api_models import (
    ExecutionStatus,
    JobCreateRequest,
    JobDetailResponse,
    JobResponse,
    JobStatus,
    ProductionExecutionCreateRequest,
    ProductionExecutionResponse,
    TenantCreateRequest,
    TenantResponse,
    TokenRequest,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
)
from rpa.auth import (
    AuthContext,
    get_auth_context,
    require_admin,
    require_merchant_admin,
)
from rpa.security import Principal
from rpa.settings import get_settings
from rpa.webhook import (
    WebhookSecurityError,
    extract_webhook_headers,
    validate_webhook_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["production-v1"])


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@router.post("/auth/token", response_model=TokenResponse)
async def create_token(req: TokenRequest):
    """Authenticate and issue an access token."""
    settings = get_settings()

    if settings.mode == "demo":
        # In demo mode, return a synthetic token
        principal = Principal(
            user_id="demo-user",
            tenant_id="demo-tenant",
            role="ADMIN",
            token_id="demo-token",
        )
        from rpa.auth import create_access_token

        token = await create_access_token(principal)
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=settings.access_token_ttl_seconds,
        )

    # Production: authenticate against database
    try:
        from rpa.auth import authenticate_user, create_access_token

        auth_principal: Principal | None = await authenticate_user(
            req.tenant_id, req.email, req.password
        )
        if not auth_principal:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        token = await create_access_token(auth_principal)
        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=settings.access_token_ttl_seconds,
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production auth requires database. Install psycopg_pool.",
        )


# ---------------------------------------------------------------------------
# Recovery job endpoints (production)
# ---------------------------------------------------------------------------
@router.post(
    "/recovery/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED
)
async def create_recovery_job(
    req: JobCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),  # noqa: B008
):
    """Create an async recovery job (production mode)."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /recovery/batch for demo mode",
        )

    # Production: create job in database
    try:
        from rpa.database import (
            RecoveryJobRepository,
            get_pool,
            transaction,
        )

        pool = get_pool()
        correlation_id = uuid.uuid4()

        with pool.connection() as conn, transaction(conn):
            job_id = RecoveryJobRepository.create(
                conn=conn,
                tenant_id=UUID(auth.principal.tenant_id),
                requested_by=UUID(auth.principal.user_id),
                request_payload=req.model_dump(),
                correlation_id=correlation_id,
            )
            RecoveryJobRepository.update_status(conn, job_id, "queued")

        return JobResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            progress=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production jobs require database",
        )


@router.get("/recovery/jobs/{job_id}", response_model=JobDetailResponse)
async def get_recovery_job(
    job_id: UUID,
    auth: AuthContext = Depends(get_auth_context),  # noqa: B008
):
    """Get recovery job status and results."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /recovery/batch/{batch_id} for demo mode",
        )

    try:
        from rpa.database import RecoveryJobRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            job = RecoveryJobRepository.get(conn, job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found: {job_id}",
                )
            if str(job["tenant_id"]) != auth.principal.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job not found: {job_id}",
                )

        return JobDetailResponse(
            job_id=job["job_id"],
            status=job["status"],
            progress=job["progress"],
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            request_payload=job["request_payload"],
            error_code=job.get("error_code"),
            correlation_id=job["correlation_id"],
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production jobs require database",
        )


@router.get("/recovery/jobs", response_model=list[JobResponse])
async def list_recovery_jobs(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    auth: AuthContext = Depends(get_auth_context),  # noqa: B008
):
    """List recovery jobs for the current tenant."""
    settings = get_settings()

    if settings.mode == "demo":
        return []

    try:
        from rpa.database import RecoveryJobRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            jobs = RecoveryJobRepository.list_for_tenant(
                conn,
                UUID(auth.principal.tenant_id),
                status=status_filter,
            )

        return [
            JobResponse(
                job_id=job["job_id"],
                status=job["status"],
                progress=job["progress"],
                created_at=job["created_at"],
                updated_at=job["updated_at"],
            )
            for job in jobs[offset : offset + limit]
        ]
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# Webhook ingestion
# ---------------------------------------------------------------------------
@router.post("/webhooks/{provider}")
async def ingest_webhook(
    provider: str,
    request: Request,
):
    """Ingest a payment provider webhook event."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhooks not supported in demo mode",
        )

    # Read body for signature verification
    body = await request.body()

    # Extract headers
    headers = dict(request.headers)
    normalized = extract_webhook_headers(headers)

    if "signature" not in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing webhook signature",
        )

    if "timestamp" not in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing webhook timestamp",
        )

    event_id = normalized.get("event_id", str(uuid.uuid4()))
    event_type = normalized.get("event_type", "unknown")

    try:
        event = validate_webhook_event(
            provider=provider,
            headers=headers,
            body=body,
            event_id=event_id,
            event_type=event_type,
            timestamp=normalized["timestamp"],
            signature=normalized["signature"],
        )
    except WebhookSecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    # Store event idempotently
    try:
        from rpa.database import ProviderEventRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            # TODO: Extract tenant_id from JWT or event payload
            # For now, use a default tenant
            event_id = ProviderEventRepository.record(
                conn=conn,
                tenant_id=uuid.uuid4(),  # TODO: Extract from JWT
                provider=event.provider,
                external_event_id=event.event_id,
                event_type=event.event_type,
                payload=event.payload,
            )
            ProviderEventRepository.mark_processed(conn, event_id)

        return {"status": "accepted", "event_id": str(event_id)}
    except ImportError:
        logger.warning("Webhook received but database not available")
        return {"status": "accepted", "event_id": event_id}


# ---------------------------------------------------------------------------
# Production execution
# ---------------------------------------------------------------------------
@router.post(
    "/executions",
    response_model=ProductionExecutionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution(
    req: ProductionExecutionCreateRequest,
    auth: AuthContext = Depends(get_auth_context),  # noqa: B008
):
    """Create a production execution (requires approval flow)."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /recovery/execute for demo mode",
        )

    # Production: create execution with idempotency
    try:
        from rpa.database import (
            ProductionExecutionRepository,
            get_pool,
            transaction,
        )

        pool = get_pool()
        correlation_id = uuid.uuid4()

        with pool.connection() as conn, transaction(conn):
            execution_id = ProductionExecutionRepository.create(
                conn=conn,
                tenant_id=UUID(auth.principal.tenant_id),
                job_id=uuid.uuid4(),  # TODO: Get from request
                transaction_id=req.transaction_id,
                idempotency_key=req.idempotency_key,
                policy_version=req.policy_version,
                model_version=req.model_version,
                optimizer_version=req.optimizer_version,
                decision_expires_at=req.decision_expires_at,
                correlation_id=correlation_id,
            )

        return ProductionExecutionResponse(
            execution_id=execution_id,
            tenant_id=UUID(auth.principal.tenant_id),
            job_id=uuid.uuid4(),
            transaction_id=req.transaction_id,
            idempotency_key=req.idempotency_key,
            state=ExecutionStatus.PLANNED,
            policy_version=req.policy_version,
            model_version=req.model_version,
            optimizer_version=req.optimizer_version,
            decision_expires_at=req.decision_expires_at,
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production executions require database",
        )


@router.post("/executions/{execution_id}/authorize")
async def authorize_execution(
    execution_id: UUID,
    auth: AuthContext = Depends(require_merchant_admin),  # noqa: B008
):
    """Authorize a production execution (requires MERCHANT_ADMIN role)."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not available in demo mode",
        )

    try:
        from rpa.database import ProductionExecutionRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            ProductionExecutionRepository.transition(
                conn,
                execution_id,
                "AUTHORIZED",
            )

        return {"status": "authorized", "execution_id": str(execution_id)}
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Production executions require database",
        )


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------
@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    tenant_id: UUID,
    req: UserCreateRequest,
    auth: AuthContext = Depends(require_admin),  # noqa: B008
):
    """Create a new user (admin only)."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User management not available in demo mode",
        )

    try:
        from rpa.database import UserRepository, get_pool, transaction

        pool = get_pool()
        with pool.connection() as conn, transaction(conn):
            from rpa.security import hash_password

            password_hash = hash_password(req.password)
            user_id = UserRepository.create(
                conn=conn,
                tenant_id=tenant_id,
                email=req.email,
                password_hash=password_hash,
                role=req.role.value,
            )

        return UserResponse(
            user_id=user_id,
            tenant_id=tenant_id,
            email=req.email,
            role=req.role,
            active=True,
            created_at=datetime.now(timezone.utc),
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="User management requires database",
        )


# ---------------------------------------------------------------------------
# Tenant management (admin only)
# ---------------------------------------------------------------------------
@router.post(
    "/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED
)
async def create_tenant(
    req: TenantCreateRequest,
    auth: AuthContext = Depends(require_admin),  # noqa: B008
):
    """Create a new tenant (admin only)."""
    settings = get_settings()

    if settings.mode == "demo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant management not available in demo mode",
        )

    try:
        from rpa.database import TenantRepository, get_pool, transaction

        pool = get_pool()
        with pool.connection() as conn, transaction(conn):
            tenant_id = TenantRepository.create(conn=conn, name=req.name)

        return TenantResponse(
            tenant_id=tenant_id,
            name=req.name,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Tenant management requires database",
        )


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    auth: AuthContext = Depends(require_admin),  # noqa: B008
):
    """List all tenants (admin only)."""
    settings = get_settings()

    if settings.mode == "demo":
        return []

    try:
        from rpa.database import TenantRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            tenants = TenantRepository.list(conn)

        return [
            TenantResponse(
                tenant_id=t["tenant_id"],
                name=t["name"],
                status=t["status"],
                created_at=t["created_at"],
            )
            for t in tenants
        ]
    except ImportError:
        return []


__all__ = ["router"]
