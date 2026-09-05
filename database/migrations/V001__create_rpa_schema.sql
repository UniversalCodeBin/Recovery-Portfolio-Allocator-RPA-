-- =====================================================================
-- V001: Initial RPA data-foundation schema.
-- Direct executable SQL (no psql meta-commands). Applied in lexical order by
-- data_core/db.py. This file is intentionally identical to
-- database/schema/rpa_schema.sql so the on-disk schema and the migrations
-- cannot drift.
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
