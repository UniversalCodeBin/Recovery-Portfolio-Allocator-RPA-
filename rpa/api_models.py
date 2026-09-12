"""API request/response models for RPA v1.

Strict Pydantic models with validation, consistent error responses,
and OpenAPI documentation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# =============================================================================
# Common types and enums
# =============================================================================


class StrategyName(str, Enum):
    NO_ACTION = "no_action"
    RULE_BASED = "rule_based"
    EV_GREEDY = "ev_greedy"
    RPA_OPTIMIZER = "rpa_optimizer"


class ActionType(str, Enum):
    NO_INTERVENTION = "no_intervention"
    RETRY = "retry"
    PAYMENT_LINK = "payment_link"
    CUSTOMER_MESSAGE = "customer_message"
    INCENTIVE = "incentive"
    HUMAN_ESCALATION = "human_escalation"


class ExecutionStatus(str, Enum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceType(str, Enum):
    RETRY = "retry"
    MESSAGING = "messaging"
    INCENTIVE_BUDGET = "incentive_budget"
    HUMAN_SLOTS = "human_slots"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MERCHANT_ADMIN = "MERCHANT_ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


# =============================================================================
# Error response models
# =============================================================================


class ErrorDetail(BaseModel):
    """Structured error detail."""

    code: str
    message: str
    field: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standardized error response envelope."""

    error: ErrorDetail
    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_encoders: ClassVar[dict] = {datetime: lambda v: v.isoformat()}


# =============================================================================
# Request models
# =============================================================================


class ResourceLimitsRequest(BaseModel):
    """Shared resource capacity limits for a batch."""

    retry: int | None = Field(None, ge=0, description="Max retry attempts")
    messaging: int | None = Field(None, ge=0, description="Max message sends")
    incentive_budget: float | None = Field(
        None, ge=0, description="Total incentive budget (INR)"
    )
    human_slots: int | None = Field(
        None, ge=0, description="Max human escalation slots"
    )

    @model_validator(mode="after")
    def check_at_least_one(self) -> ResourceLimitsRequest:
        # Allow empty for defaults
        return self


class BatchRequest(BaseModel):
    """Create and run a recovery batch."""

    split: str = Field("demo", min_length=1, description="Data split to use")
    batch_seed: int = Field(
        0, ge=0, description="Random seed for reproducible simulation"
    )
    resource_limits: ResourceLimitsRequest | None = None
    strategies: list[StrategyName] | None = Field(
        None,
        description="Strategies to run (default: all except rule_based)",
    )
    transaction_ids: list[str] | None = Field(
        None,
        description="Subset of transaction IDs to process",
    )

    @field_validator("transaction_ids")
    @classmethod
    def validate_txn_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            if not v:
                raise ValueError("transaction_ids must not be empty")
            if len(v) != len(set(v)):
                raise ValueError("transaction_ids must not contain duplicates")
        return v


class PreviewRequest(BaseModel):
    """Preview candidate actions (predictions + EV + policy) without execution."""

    split: str = Field("demo", min_length=1)
    transaction_ids: list[str] | None = None


class StrategyRequest(BaseModel):
    """Run a single strategy on a batch."""

    split: str = Field("demo", min_length=1)
    strategy: StrategyName
    batch_seed: int = Field(0, ge=0)
    resource_limits: ResourceLimitsRequest | None = None


class ExecuteRequest(BaseModel):
    """Execute an approved plan (simulation in demo, real in production)."""

    split: str = Field("demo", min_length=1)
    strategy: StrategyName = StrategyName.RPA_OPTIMIZER
    batch_seed: int = Field(0, ge=0)
    resource_limits: ResourceLimitsRequest | None = None
    idempotency_key: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        description="Client-generated idempotency key (required in production)",
    )


class JobCreateRequest(BaseModel):
    """Create an async recovery job."""

    split: str = Field("demo", min_length=1)
    batch_seed: int = Field(0, ge=0)
    resource_limits: ResourceLimitsRequest | None = None
    strategies: list[StrategyName] | None = None
    transaction_ids: list[str] | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=64)


class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


# =============================================================================
# Response models
# =============================================================================


class ActionSpecResponse(BaseModel):
    action_id: str
    action_type: ActionType
    action_cost: float
    resource_requirements: dict[str, float]
    enabled: bool


class ActionsResponse(BaseModel):
    actions: list[ActionSpecResponse]
    default_resource_limits: ResourceLimitsRequest
    available_splits: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    mode: Literal["demo", "production"]
    simulation_only: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VersionInfo(BaseModel):
    model: str
    policy: str
    optimizer: str
    ev_engine: str
    simulator: str
    verification: str


class ResourceUsage(BaseModel):
    retry: float = 0
    messaging: float = 0
    incentive_budget: float = 0
    human_slots: float = 0


class StrategyMetric(BaseModel):
    total_expected_net_ev: float
    resource_used: ResourceUsage
    status: str
    n_transactions: int
    n_planned: int
    n_executed: int
    n_successful: int
    n_failed: int
    n_blocked: int
    planned_total_net_ev: float
    recovered_total: float
    cost_total: float
    net_recovered_total: float
    all_verified: bool
    simulation: bool


class BatchSummary(BaseModel):
    batch_id: str
    status: str
    n_transactions: int
    n_actions: int
    strategy_metrics: dict[str, StrategyMetric]
    n_blocked_candidates: int
    error: str | None = None


class BatchListItem(BaseModel):
    batch_id: str
    status: str
    created_at: datetime | None = None
    n_transactions: int
    strategies: list[str]
    strategy_summaries: dict[str, Any] | None = None
    has_audit: bool = False


class EVTableRow(BaseModel):
    transaction_id: str
    action_id: str
    amount: float
    p_recovery: float
    recoverable_amount: float
    gross_expected: float
    action_cost: float
    incentive_cost: float
    total_cost: float
    net_expected: float
    is_no_op: bool


class PolicyVerdictResponse(BaseModel):
    transaction_id: str
    action_id: str
    action_type: str
    decision: PolicyDecision
    policy_id: str
    rule: str
    reason: str
    limit: float | None = None
    current_usage: float | None = None


class PreviewResponse(BaseModel):
    model_identifier: str
    n_transactions: int
    n_actions: int
    rows: list[EVTableRow]
    verdicts: list[PolicyVerdictResponse]


class PlanRecord(BaseModel):
    transaction_id: str
    action_id: str
    action_type: str
    net_ev: float
    name: str
    version: str
    status: str


class ExecutionRecord(BaseModel):
    transaction_id: str
    action_id: str
    action_type: str
    plan_name: str
    status: str
    attempted: int
    recovered_amount: float
    recovery_cost: float
    net_recovered_amount: float
    p_predicted: float | None = None
    seed: int | None = None
    simulation: bool


class VerificationRow(BaseModel):
    transaction_id: str
    planned_action_id: str
    planned_action_type: str
    planned_net_ev: float
    planned_index: int
    executed: bool
    executed_action_id: str | None = None
    executed_status: str | None = None
    successful: bool
    failed: bool
    blocked: bool
    recovered_amount: float
    recovery_cost: float
    net_recovered_amount: float
    verified: bool
    verification_error: str | None = None


class VerificationResponse(BaseModel):
    batch_metrics: StrategyMetric
    rows: list[VerificationRow]


class FullBatchResult(BaseModel):
    batch_id: str
    status: str
    created_at: datetime | None = None
    error: str | None = None
    ev_table: list[EVTableRow] | None = None
    verdicts: list[PolicyVerdictResponse] | None = None
    plans: dict[str, list[PlanRecord]] | None = None
    executions: dict[str, list[ExecutionRecord]] | None = None
    verifications: dict[str, VerificationResponse] | None = None
    transaction_ids: list[str] | None = None
    resource_limits: ResourceLimitsRequest | None = None
    summary: BatchSummary | None = None


class CompareResponse(BaseModel):
    batch_id: str
    batch_seed: int
    simulation: bool
    strategies: dict[str, StrategyMetric]


class ExecutionResponse(BaseModel):
    batch_id: str
    strategy: StrategyName
    simulation: bool
    batch_metrics: StrategyMetric
    executions: list[ExecutionRecord]


class AuditEventResponse(BaseModel):
    audit_id: str
    batch_id: str
    component: str
    event_type: str
    entity_id: str
    event_metadata: dict[str, Any]
    timestamp: datetime


class DecisionExplanation(BaseModel):
    batch_id: str
    transaction_id: str
    prediction: dict[str, Any] | None = None
    ev: EVTableRow | None = None
    policy: PolicyVerdictResponse | None = None
    decision: PlanRecord | None = None
    execution: ExecutionRecord | None = None
    verification: VerificationRow | None = None


# Job models
class JobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    progress: int
    created_at: datetime
    updated_at: datetime


class JobDetailResponse(JobResponse):
    request_payload: dict[str, Any]
    error_code: str | None = None
    correlation_id: UUID
    result: FullBatchResult | None = None


# Auth models
class TokenRequest(BaseModel):
    email: str
    password: str
    tenant_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int


class UserCreateRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=12)
    role: UserRole


class UserResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole
    active: bool
    created_at: datetime


# Tenant models
class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class TenantResponse(BaseModel):
    tenant_id: UUID
    name: str
    status: str
    created_at: datetime


# Resource limit models
class TenantResourceLimitRequest(BaseModel):
    resource_type: ResourceType
    limit_value: float = Field(..., ge=0)


class TenantResourceLimitResponse(BaseModel):
    tenant_id: UUID
    resource_type: ResourceType
    limit_value: float
    updated_at: datetime


# Production execution models
class ProductionExecutionCreateRequest(BaseModel):
    transaction_id: str
    idempotency_key: str = Field(..., min_length=1, max_length=64)
    policy_version: str
    model_version: str
    optimizer_version: str
    decision_expires_at: datetime
    action_id: str


class ProductionExecutionResponse(BaseModel):
    execution_id: UUID
    tenant_id: UUID
    job_id: UUID
    transaction_id: str
    idempotency_key: str
    state: ExecutionStatus
    policy_version: str
    model_version: str
    optimizer_version: str
    decision_expires_at: datetime
    provider_reference: str | None = None
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime


# Webhook models
class WebhookEventRequest(BaseModel):
    provider: str
    event_id: str
    event_type: str
    payload: dict[str, Any]
    signature: str
    timestamp: int
