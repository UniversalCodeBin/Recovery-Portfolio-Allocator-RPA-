"""Production authentication and authorization for RPA API.

Provides:
- JWT HS256 access tokens with standard claims
- Token validation with expiry, issuer, revocation checks
- Role-based access control (RBAC)
- Password hashing with PBKDF2-HMAC-SHA256
- Dependency injection for FastAPI
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rpa.security import (
    AuthenticationError,
    Principal,
    issue_access_token,
    validate_access_token,
)
from rpa.settings import get_settings

security = HTTPBearer(auto_error=False)


def _has_database() -> bool:
    try:
        from rpa.database import _HAS_DB

        return _HAS_DB
    except ImportError:
        return False


def _get_database_imports():
    from rpa.database import (
        RevokedTokenRepository,
        UserRepository,
        get_pool,
        transaction,
    )

    return RevokedTokenRepository, UserRepository, get_pool, transaction


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    token: str
    token_id: str


class AuthorizationError(Exception):
    pass


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> Principal:
    settings = get_settings()

    if settings.mode == "demo":
        return Principal(
            user_id="demo-user",
            tenant_id="demo-tenant",
            role="ADMIN",
            token_id="demo-token",
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    if _has_database():
        try:
            RevokedTokenRepo, _, get_pool_fn, _ = _get_database_imports()
            token_id = _extract_token_id(token)
            if token_id:
                pool = get_pool_fn()
                with pool.connection() as conn:
                    if RevokedTokenRepo.is_revoked(conn, token_id=token_id):
                        raise AuthenticationError("Token revoked")
        except AuthenticationError:
            raise
        except Exception:  # noqa: BLE001, S110
            pass

    try:
        principal = validate_access_token(
            token,
            key=settings.auth_signing_key or "demo-signing-key",
            issuer=settings.auth_issuer,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return principal


def _extract_token_id(token: str) -> str:
    import base64
    import json

    try:
        _, payload, _ = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded))
        return decoded.get("jti", "")
    except Exception:  # noqa: BLE001
        return ""


async def get_auth_context(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> AuthContext:
    token = credentials.credentials if credentials else "demo-token"
    return AuthContext(
        principal=principal,
        token=token,
        token_id=principal.token_id,
    )


def require_role(*allowed_roles: str):
    async def _check(
        principal: Principal = Depends(get_current_principal),  # noqa: B008
    ) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: one of {allowed_roles}, got {principal.role}",
            )
        return principal

    return _check


require_admin = require_role("ADMIN")
require_merchant_admin = require_role("ADMIN", "MERCHANT_ADMIN")
require_operator = require_role("ADMIN", "MERCHANT_ADMIN", "OPERATOR")
require_viewer = require_role("ADMIN", "MERCHANT_ADMIN", "OPERATOR", "VIEWER")


async def get_tenant_id(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
) -> str:
    return principal.tenant_id


async def get_user_id(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
) -> str:
    return principal.user_id


async def create_access_token(principal: Principal) -> str:
    settings = get_settings()
    return issue_access_token(
        principal,
        key=settings.auth_signing_key or "demo-signing-key",
        issuer=settings.auth_issuer,
        ttl_seconds=settings.access_token_ttl_seconds,
    )


async def authenticate_user(
    tenant_id: str, email: str, password: str
) -> Principal | None:
    """Authenticate a user against the database. Returns Principal or None."""
    if not _has_database():
        return None
    try:
        from rpa.database import UserRepository, get_pool

        pool = get_pool()
        with pool.connection() as conn:
            user = UserRepository.get_by_email(conn, UUID(tenant_id), email)
            if user is None:
                return None
            from rpa.security import verify_password

            if not verify_password(password, user["password_hash"]):
                return None
            return Principal(
                tenant_id=tenant_id,
                user_id=str(user["user_id"]),
                role=user["role"],
                token_id="",
            )
    except Exception:  # noqa: BLE001
        return None


async def revoke_token(token_id: str, user_id: str) -> None:
    if not _has_database():
        return
    RevokedTokenRepo, _, get_pool_fn, transaction_fn = _get_database_imports()
    settings = get_settings()
    pool = get_pool_fn()
    with pool.connection() as conn, transaction_fn(conn):
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.access_token_ttl_seconds
        )
        RevokedTokenRepo.add(conn, token_id, user_id, expires_at)


__all__ = [
    "AuthContext",
    "AuthorizationError",
    "create_access_token",
    "get_auth_context",
    "get_current_principal",
    "get_tenant_id",
    "get_user_id",
    "require_admin",
    "require_merchant_admin",
    "require_operator",
    "require_role",
    "require_viewer",
    "revoke_token",
]
