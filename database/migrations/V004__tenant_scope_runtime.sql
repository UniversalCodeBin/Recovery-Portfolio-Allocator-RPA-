ALTER TABLE recovery_runs
    ADD COLUMN IF NOT EXISTS tenant_id UUID,
    ADD COLUMN IF NOT EXISTS actor_user_id UUID,
    ADD COLUMN IF NOT EXISTS correlation_id UUID,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS result_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE candidate_actions ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE policy_decisions ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE recovery_plans ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE executions ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_id UUID;

CREATE TABLE IF NOT EXISTS tenant_resource_limits (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('retry', 'messaging', 'incentive_budget', 'human_slots')),
    limit_value NUMERIC(18, 4) NOT NULL CHECK (limit_value >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, resource_type)
);

CREATE INDEX IF NOT EXISTS idx_recovery_runs_tenant_created ON recovery_runs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_actions_tenant ON candidate_actions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_policy_decisions_tenant ON policy_decisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_recovery_plans_tenant ON recovery_plans(tenant_id);
CREATE INDEX IF NOT EXISTS idx_executions_tenant ON executions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_verifications_tenant ON verifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id);
