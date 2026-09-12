-- Production runtime foundation. This migration is additive: legacy demo
-- tables remain intact and can continue to support synthetic demonstrations.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'MERCHANT_ADMIN', 'OPERATOR', 'VIEWER')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery_jobs (
    job_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    requested_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    request_payload JSONB NOT NULL,
    progress SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    error_code TEXT,
    correlation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_recovery_jobs_tenant_status ON recovery_jobs(tenant_id, status, created_at);

CREATE TABLE IF NOT EXISTS resource_reservations (
    reservation_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    job_id UUID NOT NULL REFERENCES recovery_jobs(job_id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('retry', 'messaging', 'incentive_budget', 'human_slots')),
    reserved_amount NUMERIC(18, 4) NOT NULL CHECK (reserved_amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'consumed', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, resource_type)
);

CREATE TABLE IF NOT EXISTS provider_events (
    provider_event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    UNIQUE (tenant_id, provider, external_event_id)
);

CREATE TABLE IF NOT EXISTS production_executions (
    execution_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    job_id UUID NOT NULL REFERENCES recovery_jobs(job_id) ON DELETE RESTRICT,
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PLANNED', 'AUTHORIZED', 'EXECUTING', 'SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED')),
    policy_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    optimizer_version TEXT NOT NULL,
    decision_expires_at TIMESTAMPTZ NOT NULL,
    provider_reference TEXT,
    correlation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (job_id, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_production_executions_tenant_state ON production_executions(tenant_id, state);

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    artifact_sha256 CHAR(64) NOT NULL,
    feature_schema_version TEXT NOT NULL,
    preprocessing_version TEXT NOT NULL,
    calibration_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    training_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ
);
