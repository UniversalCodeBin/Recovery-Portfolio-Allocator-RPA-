"""Small dependency-free HS256 bearer-token implementation.

Tokens use the standard JWT compact serialization and are validated for
algorithm, issuer, expiry, not-before and signature with constant-time
comparison. Password hashes use PBKDF2-HMAC-SHA256 and never appear in logs.
Persistent users/revocation are provided by the production repository layer;
these primitives intentionally do not authenticate a caller by themselves.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass

ROLES = frozenset({"ADMIN", "MERCHANT_ADMIN", "OPERATOR", "VIEWER"})


class AuthenticationError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    token_id: str


def issue_access_token(
    principal: Principal, *, key: str, issuer: str, ttl_seconds: int
) -> str:
    if principal.role not in ROLES:
        raise ValueError("unknown role")
    now = int(time.time())
    header = _b64(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _b64(
        json.dumps(
            {
                "sub": principal.user_id,
                "tid": principal.tenant_id,
                "role": principal.role,
                "jti": principal.token_id,
                "iss": issuer,
                "iat": now,
                "nbf": now,
                "exp": now + ttl_seconds,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64(
        hmac.new(key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def validate_access_token(
    token: str, *, key: str, issuer: str, revoked_token_ids: Iterable[str] = ()
) -> Principal:
    try:
        header, payload, signature = token.split(".")
        decoded_header = json.loads(_unb64(header))
        claims = json.loads(_unb64(payload))
    except Exception as exc:
        raise AuthenticationError("malformed bearer token") from exc
    expected = _b64(
        hmac.new(key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    if decoded_header != {"alg": "HS256", "typ": "JWT"} or not hmac.compare_digest(
        signature, expected
    ):
        raise AuthenticationError("invalid bearer token")
    now = int(time.time())
    required = ("sub", "tid", "role", "jti", "iss", "exp", "nbf")
    if any(
        not isinstance(claims.get(name), str if name not in {"exp", "nbf"} else int)
        for name in required
    ):
        raise AuthenticationError("invalid bearer token claims")
    if (
        claims["iss"] != issuer
        or claims["role"] not in ROLES
        or claims["exp"] <= now
        or claims["nbf"] > now
    ):
        raise AuthenticationError("expired or invalid bearer token")
    if claims["jti"] in set(revoked_token_ids):
        raise AuthenticationError("revoked bearer token")
    return Principal(claims["sub"], claims["tid"], claims["role"], claims["jti"])


def hash_password(password: str, *, iterations: int = 600_000) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _unb64(raw_salt), int(raw_iterations)
        )
        return hmac.compare_digest(_b64(digest), raw_digest)
    except Exception:  # noqa: BLE001
        return False


def require_role(principal: Principal, *roles: str) -> Principal:
    if principal.role not in roles:
        raise PermissionError("insufficient role")
    return principal
