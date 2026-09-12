"""Observability module for RPA production.

Provides:
- Structured logging with correlation IDs
- Metrics collection (Prometheus-compatible)
- Health check aggregation
- Audit trail integration
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rpa.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class MetricsCollector:
    """Simple in-memory metrics collector (Prometheus-compatible format)."""

    _counters: dict[str, int] = field(default_factory=dict)
    _histograms: dict[str, list] = field(default_factory=dict)
    _gauges: dict[str, float] = field(default_factory=dict)

    def inc_counter(
        self, name: str, value: int = 1, labels: dict[str, str] | None = None
    ) -> None:
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def observe_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)

    def set_gauge(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_histogram(
        self, name: str, labels: dict[str, str] | None = None
    ) -> dict[str, float]:
        key = self._make_key(name, labels)
        values = self._histograms.get(key, [])
        if not values:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "avg": 0}
        return {
            "count": len(values),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        }

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        return self._gauges.get(key, 0.0)

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []

        for key, value in self._counters.items():
            name, labels = self._parse_key(key)
            label_str = self._format_labels(labels) if labels else ""
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{label_str} {value}")

        for key, values in self._histograms.items():
            name, labels = self._parse_key(key)
            label_str = self._format_labels(labels) if labels else ""
            if values:
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{name}_count{label_str} {len(values)}")
                lines.append(f"{name}_sum{label_str} {sum(values):.6f}")

        for key, gval in self._gauges.items():
            name, labels = self._parse_key(key)
            label_str = self._format_labels(labels) if labels else ""
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name}{label_str} {gval:.6f}")

        return "\n".join(lines) + "\n"

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name

    def _parse_key(self, key: str) -> tuple:
        if "{" in key:
            name, label_str = key.split("{", 1)
            label_str = label_str.rstrip("}")
            labels = dict(item.split("=") for item in label_str.split(","))
            return name, labels
        return key, None

    def _format_labels(self, labels: dict[str, str]) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"


# Global metrics collector
metrics = MetricsCollector()


@contextmanager
def track_operation(
    operation: str,
    labels: dict[str, str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Track an operation with timing and metrics."""
    start_time = time.monotonic()
    context = {
        "operation": operation,
        "labels": labels or {},
        "start_time": start_time,
    }

    try:
        yield context
    except Exception as exc:
        context["error"] = str(exc)
        metrics.inc_counter(
            "rpa_operations_total",
            labels={**(labels or {}), "status": "error", "operation": operation},
        )
        raise
    finally:
        duration = time.monotonic() - start_time
        context["duration_seconds"] = duration

        metrics.observe_histogram(
            "rpa_operation_duration_seconds",
            duration,
            labels={**(labels or {}), "operation": operation},
        )
        metrics.inc_counter(
            "rpa_operations_total",
            labels={**(labels or {}), "status": "success", "operation": operation},
        )


def record_batch_metrics(
    batch_id: str,
    strategy: str,
    n_transactions: int,
    n_planned: int,
    n_executed: int,
    n_successful: int,
    n_failed: int,
    total_net_ev: float,
) -> None:
    """Record batch execution metrics."""
    labels = {"batch_id": batch_id, "strategy": strategy}

    metrics.set_gauge("rpa_batch_n_transactions", n_transactions, labels)
    metrics.set_gauge("rpa_batch_n_planned", n_planned, labels)
    metrics.set_gauge("rpa_batch_n_executed", n_executed, labels)
    metrics.set_gauge("rpa_batch_n_successful", n_successful, labels)
    metrics.set_gauge("rpa_batch_n_failed", n_failed, labels)
    metrics.set_gauge("rpa_batch_total_net_ev", total_net_ev, labels)

    metrics.inc_counter("rpa_batches_total", labels={"strategy": strategy})


def record_prediction_metrics(
    model_identifier: str,
    n_transactions: int,
    n_actions: int,
) -> None:
    """Record prediction service metrics."""
    labels = {"model": model_identifier}

    metrics.set_gauge("rpa_prediction_n_transactions", n_transactions, labels)
    metrics.set_gauge("rpa_prediction_n_actions", n_actions, labels)
    metrics.inc_counter("rpa_predictions_total", labels=labels)


def record_execution_metrics(
    strategy: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record execution metrics."""
    labels = {"strategy": strategy, "status": status}

    metrics.observe_histogram(
        "rpa_execution_duration_seconds", duration_seconds, labels
    )
    metrics.inc_counter("rpa_executions_total", labels=labels)


def record_policy_metrics(
    decision: str,
    rule: str,
) -> None:
    """Record policy engine metrics."""
    labels = {"decision": decision, "rule": rule}
    metrics.inc_counter("rpa_policy_decisions_total", labels=labels)


def record_webhook_metrics(
    provider: str,
    event_type: str,
    status: str,
) -> None:
    """Record webhook ingestion metrics."""
    labels = {"provider": provider, "event_type": event_type, "status": status}
    metrics.inc_counter("rpa_webhooks_total", labels=labels)


def get_health_status() -> dict[str, Any]:
    """Get aggregated health status."""
    settings = get_settings()

    health: dict[str, Any] = {
        "status": "ok",
        "service": "rpa-backend",
        "version": "0.3.0",
        "mode": settings.mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    # Database check
    if settings.mode == "production":
        try:
            from rpa.database import get_pool

            pool = get_pool()
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            health["checks"]["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            health["checks"]["database"] = f"error: {exc}"
            health["status"] = "degraded"

    # Model check
    try:
        from rpa.prediction_service import PredictionService

        PredictionService()
        health["checks"]["model"] = "ok"
    except Exception as exc:  # noqa: BLE001
        health["checks"]["model"] = f"error: {exc}"
        health["status"] = "degraded"

    return health


__all__ = [
    "MetricsCollector",
    "get_health_status",
    "metrics",
    "record_batch_metrics",
    "record_execution_metrics",
    "record_policy_metrics",
    "record_prediction_metrics",
    "record_webhook_metrics",
    "track_operation",
]
