"""Clean boundary for future payment-provider adapters.

No Razorpay integration is claimed or implemented here. `SimulatorProvider`
is the only current adapter and is valid exclusively in demo mode.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PaymentFailureEvent:
    provider: str
    event_id: str
    tenant_id: str
    transaction_reference: str
    occurred_at: str
    payload: dict[str, Any]


class PaymentEventProvider(ABC):
    @abstractmethod
    def validate_event(
        self, headers: dict[str, str], body: bytes
    ) -> PaymentFailureEvent: ...


class RecoveryActionExecutor(ABC):
    @abstractmethod
    def execute(
        self, *, execution_id: str, action_id: str, transaction_id: str
    ) -> dict[str, Any]: ...


class RecoveryOutcomeProvider(ABC):
    @abstractmethod
    def fetch_outcome(self, provider_reference: str) -> dict[str, Any]: ...


class WebhookEventHandler(ABC):
    @abstractmethod
    def handle(self, headers: dict[str, str], body: bytes) -> str: ...


class SimulatorProvider(RecoveryActionExecutor, RecoveryOutcomeProvider):
    """Marker adapter: production configuration must never select it."""

    def execute(
        self, *, execution_id: str, action_id: str, transaction_id: str
    ) -> dict[str, Any]:
        return {
            "simulation": True,
            "execution_id": execution_id,
            "action_id": action_id,
            "transaction_id": transaction_id,
        }

    def fetch_outcome(self, provider_reference: str) -> dict[str, Any]:
        return {"simulation": True, "provider_reference": provider_reference}
