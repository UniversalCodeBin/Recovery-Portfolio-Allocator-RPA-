-- =====================================================================
-- RPA data foundation schema (PostgreSQL-compatible)
-- Source of truth for the relational model (mirrors data_core/models.py).
-- =====================================================================
-- Convention: PK ids are stable string ids (cust_*, txn_*, act_*, out_*,
-- pred_*, rc_*, dec_*, aud_*). All timestamps are UTC timestamptz.

CREATE TABLE customers (
    customer_id              TEXT PRIMARY KEY,
    customer_segment         TEXT NOT NULL,
    customer_ltv             DOUBLE PRECISION NOT NULL CHECK (customer_ltv >= 0),
    historical_success_rate  DOUBLE PRECISION NOT NULL CHECK (historical_success_rate >= 0 AND historical_success_rate <= 1),
    historical_recovery_rate DOUBLE PRECISION NOT NULL CHECK (historical_recovery_rate >= 0 AND historical_recovery_rate <= 1),
    customer_behavior_score  DOUBLE PRECISION NOT NULL,
    customer_tenure_days     INTEGER NOT NULL CHECK (customer_tenure_days >= 0),
    created_at               TIMESTAMPTZ NOT NULL,
    updated_at               TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at)
);

CREATE TABLE transactions (
    transaction_id        TEXT PRIMARY KEY,
    customer_id           TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    amount                DOUBLE PRECISION NOT NULL CHECK (amount > 0 AND amount <= 100000),
    currency              TEXT NOT NULL,
    payment_method        TEXT NOT NULL,
    bank                  TEXT NOT NULL,
    failure_reason        TEXT NOT NULL,
    transaction_status    TEXT NOT NULL,
    retry_count           INTEGER NOT NULL CHECK (retry_count >= 0),
    days_overdue          INTEGER NOT NULL CHECK (days_overdue >= 0),
    due_date              TIMESTAMPTZ NOT NULL,
    transaction_timestamp TIMESTAMPTZ NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    CHECK (transaction_timestamp <= due_date)
);

CREATE TABLE recovery_actions (
    action_id               TEXT PRIMARY KEY,
    action_type             TEXT NOT NULL UNIQUE,
    description             TEXT,
    action_cost             DOUBLE PRECISION NOT NULL CHECK (action_cost >= 0),
    resource_requirements   JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE action_outcomes (
    outcome_id          TEXT PRIMARY KEY,
    transaction_id      TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id           TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE RESTRICT,
    attempted_at        TIMESTAMPTZ NOT NULL,
    recovery_status     TEXT NOT NULL,
    recovered_amount    DOUBLE PRECISION NOT NULL CHECK (recovered_amount >= 0),
    outcome_timestamp   TIMESTAMPTZ NOT NULL CHECK (outcome_timestamp >= attempted_at),
    response_reason     TEXT
);

CREATE TABLE recovery_predictions (
    prediction_id                    TEXT PRIMARY KEY,
    transaction_id                   TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    action_id                        TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE CASCADE,
    model_identifier                 TEXT NOT NULL,
    predicted_recovery_probability   DOUBLE PRECISION NOT NULL CHECK (predicted_recovery_probability >= 0 AND predicted_recovery_probability <= 1),
    prediction_timestamp             TIMESTAMPTZ NOT NULL
);

CREATE TABLE resource_constraints (
    constraint_id  TEXT PRIMARY KEY,
    resource_type  TEXT NOT NULL UNIQUE,
    limit_value    DOUBLE PRECISION NOT NULL CHECK (limit_value >= 0),
    description    TEXT
);

CREATE TABLE recovery_decisions (
    decision_id          TEXT PRIMARY KEY,
    transaction_id       TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    selected_action_id   TEXT NOT NULL REFERENCES recovery_actions(action_id) ON DELETE RESTRICT,
    decision_status      TEXT NOT NULL,
    decision_timestamp   TIMESTAMPTZ NOT NULL,
    decision_source      TEXT NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE audit_logs (
    audit_id       TEXT PRIMARY KEY,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp      TIMESTAMPTZ NOT NULL
);

-- Indexes to support the queries Step 2/3/4/5 will build on this foundation.
CREATE INDEX idx_transactions_customer_id       ON transactions(customer_id);
CREATE INDEX idx_transactions_status_overdue    ON transactions(transaction_status, days_overdue DESC);
CREATE INDEX idx_action_outcomes_transaction    ON action_outcomes(transaction_id);
CREATE INDEX idx_action_outcomes_action         ON action_outcomes(action_id);
CREATE INDEX idx_action_outcomes_attempted      ON action_outcomes(attempted_at);
CREATE INDEX idx_recovery_predictions_txn       ON recovery_predictions(transaction_id);
CREATE INDEX idx_recovery_decisions_txn         ON recovery_decisions(transaction_id);
CREATE INDEX idx_audit_logs_entity              ON audit_logs(entity_type, entity_id);
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