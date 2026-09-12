"""Webhook security for payment provider integrations.

Provides:
- HMAC-SHA256 signature verification
- Timestamp-based replay protection
- Payload integrity validation
- Idempotent event processing
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from rpa.settings import get_settings

logger = logging.getLogger(__name__)


class WebhookSecurityError(Exception):
    """Webhook security validation failed."""
    pass


class WebhookReplayError(WebhookSecurityError):
    """Webhook timestamp too old — possible replay attack."""
    pass


class WebhookSignatureError(WebhookSecurityError):
    """Webhook signature verification failed."""
    pass


@dataclass(frozen=True)
class WebhookEvent:
    """Validated webhook event."""
    provider: str
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: int
    received_at: int


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """Verify HMAC signature of a webhook payload.
    
    Args:
        payload: Raw request body bytes
        signature: Signature from the webhook header
        secret: Shared HMAC secret
        algorithm: Hash algorithm (default: sha256)
    
    Returns:
        True if signature is valid
    
    Raises:
        WebhookSignatureError if signature is invalid
    """
    if not secret:
        raise WebhookSignatureError("Webhook signing secret not configured")
    
    if not signature:
        raise WebhookSignatureError("Missing webhook signature")
    
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        getattr(hashlib, algorithm),
    ).hexdigest()
    
    # Support both raw hex and base64-encoded signatures
    if signature.startswith("sha256="):
        signature = signature[7:]
    
    # Try hex comparison first
    if hmac.compare_digest(signature, expected):
        return True
    
    # Try base64 comparison
    try:
        expected_b64 = base64.b64encode(bytes.fromhex(expected)).decode()
        if hmac.compare_digest(signature, expected_b64):
            return True
    except Exception:
        pass
    
    raise WebhookSignatureError("Invalid webhook signature")


def verify_webhook_timestamp(
    timestamp: int,
    tolerance_seconds: Optional[int] = None,
) -> bool:
    """Verify webhook timestamp is within tolerance.
    
    Args:
        timestamp: Unix timestamp from the webhook
        tolerance_seconds: Maximum age in seconds (default: from settings)
    
    Returns:
        True if timestamp is valid
    
    Raises:
        WebhookReplayError if timestamp is too old
    """
    if tolerance_seconds is None:
        settings = get_settings()
        tolerance_seconds = settings.webhook_timestamp_tolerance_seconds
    
    now = int(time.time())
    age = now - timestamp
    
    if age > tolerance_seconds:
        raise WebhookReplayError(
            f"Webhook timestamp too old: {age}s ago (tolerance: {tolerance_seconds}s)"
        )
    
    if age < -tolerance_seconds:
        raise WebhookReplayError(
            f"Webhook timestamp is in the future: {-age}s ahead"
        )
    
    return True


def validate_webhook_event(
    provider: str,
    headers: Dict[str, str],
    body: bytes,
    event_id: str,
    event_type: str,
    timestamp: int,
    signature: str,
) -> WebhookEvent:
    """Validate and create a webhook event.
    
    Args:
        provider: Payment provider name
        headers: Request headers
        body: Raw request body
        event_id: Unique event identifier
        event_type: Type of event
        timestamp: Unix timestamp
        signature: HMAC signature
    
    Returns:
        Validated WebhookEvent
    
    Raises:
        WebhookSecurityError if validation fails
    """
    settings = get_settings()
    
    if not settings.webhook_signing_secret:
        raise WebhookSecurityError("Webhook signing secret not configured")
    
    # Verify timestamp
    verify_webhook_timestamp(timestamp)
    
    # Verify signature
    verify_webhook_signature(body, signature, settings.webhook_signing_secret)
    
    # Parse and validate payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebhookSecurityError(f"Invalid JSON payload: {exc}")
    
    return WebhookEvent(
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        timestamp=timestamp,
        received_at=int(time.time()),
    )


def extract_webhook_headers(request_headers: Dict[str, str]) -> Dict[str, str]:
    """Extract and normalize webhook-related headers.
    
    Common header patterns:
    - Razorpay: X-Razorpay-Signature, X-Razorpay-Event
    - Stripe: Stripe-Signature, Stripe-Event
    - Generic: X-Webhook-Signature, X-Webhook-Timestamp
    """
    normalized = {}
    
    # Common signature headers
    sig_headers = [
        "x-razorpay-signature",
        "stripe-signature",
        "x-webhook-signature",
        "x-hub-signature-256",
    ]
    for header in sig_headers:
        if header in request_headers:
            normalized["signature"] = request_headers[header]
            break
    
    # Common timestamp headers
    ts_headers = [
        "x-razorpay-timestamp",
        "x-webhook-timestamp",
        "x-webhook-timestamp-ms",
    ]
    for header in ts_headers:
        if header in request_headers:
            try:
                normalized["timestamp"] = int(request_headers[header])
            except ValueError:
                pass
            break
    
    # Common event ID headers
    id_headers = [
        "x-razorpay-event-id",
        "x-webhook-id",
        "x-event-id",
    ]
    for header in id_headers:
        if header in request_headers:
            normalized["event_id"] = request_headers[header]
            break
    
    # Common event type headers
    type_headers = [
        "x-razorpay-event",
        "x-webhook-event-type",
        "x-event-type",
    ]
    for header in type_headers:
        if header in request_headers:
            normalized["event_type"] = request_headers[header]
            break
    
    return normalized


__all__ = [
    "WebhookSecurityError",
    "WebhookReplayError",
    "WebhookSignatureError",
    "WebhookEvent",
    "verify_webhook_signature",
    "verify_webhook_timestamp",
    "validate_webhook_event",
    "extract_webhook_headers",
]
