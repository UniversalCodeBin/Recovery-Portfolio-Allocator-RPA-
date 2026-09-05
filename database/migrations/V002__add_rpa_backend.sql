-- =====================================================================
-- RPA Step 3 backend schema (recovery decision pipeline)
-- Added on top of V001 (Step 1 data foundation) — V001 stays untouched.
--
-- New logical entities (only what Step 3 needs; reuse of Step 1 schema):
--   recovery_runs           one row per recovery batch run
--   candidate_actions       per-(txn, action) prediction + EV rows
--   policy_decisions        per-candidate allow/block verdicts
--   recovery_plans          per-batch strategy plan (chosen action per txn)
--   executions              simulated execution rows
--   verifications           verification rows
--   audit_events            full decision trail (component-level events)
--
-- FKs reference the Step 1 tables (transactions, recovery_actions) and Step 3
-- tables. All timestamps are UTC timestamptz. JSONB columns hold rich metadata
-- so the decision trail stays queryable without schema churn.
-- =====================================================================

CREATE TABLE IF NOT EXISTS recovery_runs (
    run_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    batch_seed          INTEGER NOT NULL,
    model_identifier    TEXT,
    resource_limits     JSONB NOT NULL DEFAULT '{}'::jsonb,
    strategies          JSONB NOT NULL DEFAULT '[]'::jsonb,
    simulation          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_actions (
    candidate_id                   TEXT PRIMARY KEY,
    run_id                         TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    transaction_id                 TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id                      TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE CASCADE,
    predicted_recovery_probability DOUBLE PRECISION NOT NULL CHECK (predicted_recovery_probability >= 0 AND predicted_recovery_probability <= 1),
    recoverable_amount             DOUBLE PRECISION NOT NULL CHECK (recoverable_amount >= 0),
    gross_expected                 DOUBLE PRECISION NOT NULL CHECK (gross_expected >= 0),
    action_cost                    DOUBLE PRECISION NOT NULL CHECK (action_cost >= 0),
    incentive_cost                 DOUBLE PRECISION NOT NULL CHECK (incentive_cost >= 0),
    total_cost                     DOUBLE PRECISION NOT NULL CHECK (total_cost >= 0),
    net_expected                   DOUBLE PRECISION NOT NULL,
    UNIQUE (run_id, transaction_id, action_id)
);
CREATE INDEX IF NOT EXISTS idx_candidate_actions_run  ON candidate_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_actions_txn  ON candidate_actions(run_id, transaction_id);

CREATE TABLE IF NOT EXISTS policy_decisions (
    decision_id         TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    transaction_id      TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id           TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE CASCADE,
    decision            TEXT NOT NULL CHECK (decision IN ('ALLOW', 'BLOCK')),
    policy_id           TEXT NOT NULL,
    rule                TEXT,
    reason              TEXT,
    limit_value         DOUBLE PRECISION,
    current_usage       DOUBLE PRECISION,
    UNIQUE (run_id, transaction_id, action_id)
);
CREATE INDEX IF NOT EXISTS idx_policy_decisions_run ON policy_decisions(run_id);

CREATE TABLE IF NOT EXISTS recovery_plans (
    plan_id             TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    strategy            TEXT NOT NULL,
    transaction_id      TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id           TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE CASCADE,
    net_ev              DOUBLE PRECISION NOT NULL,
    status              TEXT,
    UNIQUE (run_id, strategy, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_recovery_plans_run ON recovery_plans(run_id, strategy);

CREATE TABLE IF NOT EXISTS executions (
    execution_id          TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    strategy              TEXT NOT NULL,
    transaction_id        TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id             TEXT,
    status                TEXT NOT NULL CHECK (status IN ('attempted','successful','failed','blocked')),
    recovered_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    recovery_cost         DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_recovered_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    p_predicted           DOUBLE PRECISION,
    simulation            BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_executions_run ON executions(run_id, strategy);

CREATE TABLE IF NOT EXISTS verifications (
    verification_id       TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    strategy              TEXT NOT NULL,
    transaction_id        TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    planned_action_id     TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE CASCADE,
    executed             BOOLEAN NOT NULL,
    executed_status       TEXT,
    successful            BOOLEAN NOT NULL,
    failed                BOOLEAN NOT NULL,
    blocked               BOOLEAN NOT NULL,
    recovered_amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_recovered_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    verified              BOOLEAN NOT NULL,
    verification_error    TEXT,
    UNIQUE (run_id, strategy, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_verifications_run ON verifications(run_id, strategy);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES recovery_runs(run_id) ON DELETE CASCADE,
    component       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    entity_id       TEXT,
    event_metadata  JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp       TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_run ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_txn ON audit_events(run_id, entity_id);