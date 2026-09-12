from datetime import datetime, timedelta, timezone

import pytest

from rpa.execution import ExecutionDecision, ExecutionState, transition
from rpa.security import AuthenticationError, Principal, hash_password, issue_access_token, validate_access_token, verify_password


def test_hs256_token_has_expiry_and_tenant_claims():
    principal = Principal("user-1", "tenant-1", "OPERATOR", "token-1")
    token = issue_access_token(principal, key="x" * 32, issuer="rpa", ttl_seconds=60)
    assert validate_access_token(token, key="x" * 32, issuer="rpa") == principal
    with pytest.raises(AuthenticationError):
        validate_access_token(token, key="y" * 32, issuer="rpa")
    with pytest.raises(AuthenticationError):
        validate_access_token(token, key="x" * 32, issuer="rpa", revoked_token_ids=["token-1"])


def test_password_hash_is_salted_and_verifiable():
    encoded = hash_password("a long password")
    assert verify_password("a long password", encoded)
    assert not verify_password("wrong password", encoded)


def test_execution_state_machine_fails_closed():
    base = ExecutionDecision("ex", "txn", "key", ExecutionState.PLANNED,
        datetime.now(timezone.utc) + timedelta(minutes=1), True, True, True)
    authorized = transition(base, ExecutionState.AUTHORIZED)
    assert transition(authorized, ExecutionState.EXECUTING).state == ExecutionState.EXECUTING
    with pytest.raises(ValueError):
        transition(base, ExecutionState.SUCCEEDED)
    expired = ExecutionDecision(**{**authorized.__dict__, "decision_expires_at": datetime.now(timezone.utc)})
    with pytest.raises(PermissionError):
        transition(expired, ExecutionState.EXECUTING)
