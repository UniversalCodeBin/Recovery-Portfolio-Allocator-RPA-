# RPA Step 1 — Data Storage + Cleaning + Database + Validation

This document describes **Step 1 only** of the Revenue Recovery Portfolio
Allocator (RPA) build. The previous validation experiment (NEUTRAL verdict)
lives in the top-level modules (`config.py`, `data_generation.py`, `model.py`,
`optimizer.py`, `strategies.py`, `metrics.py`, `outcome_simulator.py`,
`feature_engineering.py`, `visualization.py`, `experiment.py`) and is
**preserved unchanged**. Step 1 adds a separate, extensible data foundation in
the `data_core/` package.

## 1. Purpose of Step 1

Build a clean, extensible, validated data foundation so that future steps can
build **feature engineering, ML recovery prediction, recovery decisioning,
optimization, backend APIs and frontend dashboards** without redesigning the
data layer. The RPA thesis was classified NEUTRAL, so this layer intentionally
makes **no assumptions** that would prevent changing the recovery model or the
optimization strategy later.

Step 1 delivers: a normalized relational schema, reproducible synthetic raw
data, a documented cleaning pipeline, a formal validation layer, a data-quality
report, a leakage-safe train/val/test/demo split, and (optional) PostgreSQL
loading.

**NOT in scope (Steps 2-5):** logistic regression, any ML training, recovery
prediction computation, feature engineering, expected-value calculation, the RPA
optimizer / OR-Tools, recovery-decision logic, FastAPI, backend APIs, frontend,
Razorpay API integration, authentication, deployment, full QA.

## 2. Data architecture

```
data_core/            Step 1 Python package (flat modules, importable with pythonpath=.)
  config.py           centralized config (seeds, sizes, paths, thresholds, DB env)
  models.py           canonical dataclasses (one per entity table)
  registry.py         recovery-actions/resources as configuration data
  generator.py        reproducible neutral synthetic data generator
  cleaning.py         policy-driven cleaning (missing/dup/invalid/dates)
  validation.py       Pydantic structural + cross-record integrity validation
  schema.py           loads canonical PostgreSQL DDL from disk
  db.py               psycopg bulk loader (COPY) — optional
  splitting.py        customer-grouped, leakage-free splits
  io.py               CSV round-trip helpers (dtypes + JSON)
  quality_report.py   data-quality report (JSON + Markdown)
  pipeline.py         end-to-end orchestrator

data/                 generated artifacts (gitignored, reproducible)
  raw/ cleaned/ validated/ splits/

database/
  schema/rpa_schema.sql      canonical DDL
  migrations/V001__create_rpa_schema.sql   executable baseline

reports/data_quality/        data-quality report outputs

scripts/
  run_step1.py               end-to-end Step 1 runner

tests/test_step1_data_foundation.py   Step 1 test suite
```

The package reuses **stable, domain-level** constants from the experiment's
`config.py` (the `Action`/`Resource` enumerations, category vocabularies, action
economics `ACTION_SPECS`, the amount distribution parameters and the master
data seed) so actions and categories have a single source of truth. It does
**not** import the hidden ground-truth model, the experiment scenarios, or any
model/strategy hyperparameters.

## 3. Database schema

PostgreSQL-compatible, normalized. Full DDL in
`database/schema/rpa_schema.sql` (mirrored by `database/migrations/V001__*.sql`).

| Table | Primary key | Foreign keys |
|---|---|---|
| `customers` | `customer_id` | — |
| `transactions` | `transaction_id` | `customer_id → customers` |
| `recovery_actions` | `action_id` | — |
| `action_outcomes` | `outcome_id` | `transaction_id → transactions`, `action_id → recovery_actions` |
| `recovery_predictions` | `prediction_id` | `transaction_id → transactions`, `action_id → recovery_actions` |
| `resource_constraints` | `constraint_id` | — |
| `recovery_decisions` | `decision_id` | `transaction_id → transactions`, `selected_action_id → recovery_actions` |
| `audit_logs` | `audit_id` | — |

Key constraints: `amount > 0`, `amount <= 100000`, `retry_count >= 0`,
`days_overdue >= 0`, `created_at <= updated_at`, every rate in `[0,1]`,
`predicted_recovery_probability` in `[0,1]`, `transaction_timestamp <= due_date`,
`outcome_timestamp >= attempted_at`, `recovered_amount >= 0`. JSON columns
(`resource_requirements`, `metadata`, `event_metadata`) are `jsonb` for future
extensibility without schema changes. IDs are stable string ids (`cust_*`,
`txn_*`, `act_*`, `out_*`, `pred_*`, `rc_*`, `dec_*`, `aud_*`).

`recovery_predictions` and `recovery_decisions` exist as empty tables — they are
populated by Step 2 and Step 3 respectively.

## 4. Data flow

```
generator (raw) -> data/raw/*.csv
        |
        v
cleaning          -> data/cleaned/*.csv  (+ rejected/*.csv, in report)
        |
        v
validation        -> data/validated/*.csv  (accepted only)
        |
        v
splitting         -> data/splits/split_{train,val,test,demo}.csv  + manifest
        |
        v
quality report    -> reports/data_quality/data_quality_report.{json,md}
        |
        v
(optional) DB      -> PostgreSQL (env-driven connection)
```

## 5. Cleaning rules

Operates per-entity on pandas DataFrames via explicit field policies in
`data_core/cleaning.py` (required / optional / imputed per field). Detected
issues are **recorded, never silently fixed**:

* **Missing values** — required fields reject the row; optional fields are kept
  as null; imputed fields are filled with a configured default (each imputation
  is logged as a transformation).
* **Duplicates** — duplicate primary keys are detected and the row is rejected
  (first occurrence kept); count recorded.
* **Invalid values** — out-of-range numerics (`amount<=0`, `retry<0`,
  `days_overdue<0`, `recovered_amount<0`, rates/probabilities out of `[0,1]`,
  `amount>100000`) and invalid categoricals reject the row (or null an optional
  field).
* **Date consistency** — `updated_at < created_at` or
  `transaction_timestamp > due_date` reject the row; an inconsistent
  `days_overdue` (vs. `due_date` + reference date) is **imputed** from the dates
  and recorded as a transformation (documented, not silent).

## 6. Validation rules

Applied **after cleaning, before DB insertion** (`data_core/validation.py`),
using **Pydantic v2** for per-record structural checks and explicit cross-record
functions. Pydantic was chosen because the model is row/relational, it gives
strict typed fields with bounded-numeric constraints and enum validation with
minimal boilerplate, the models double as documentation, and per-record errors
are trivial to unit test. Pydantic cannot express cross-record invariants, so
those are explicit functions:

* **Referential integrity** — `transactions.customer_id → customers`,
  `action_outcomes.transaction_id → transactions`,
  `action_outcomes.action_id → recovery_actions`,
  `recovery_predictions.{transaction_id,action_id} → ...`,
  `recovery_decisions.selected_action_id → recovery_actions`.
* **Domain** — `amount>0`, `retry_count>=0`, `recovered_amount>=0`,
  `recovered_amount <= transaction.amount` (cross-record join),
  probability in `[0,1]`, valid enums.
* **Uniqueness** — primary keys unique (defense-in-depth; cleaning already
  de-duplicated).
* **Required fields** — pydantic rejects missing mandatory fields.
* **Temporal integrity** — `updated_at >= created_at`,
  `transaction_timestamp <= due_date`, `outcome_timestamp >= attempted_at`,
  and (cross-record) `action_outcomes.attempted_at >= transactions.transaction_timestamp`
  (an outcome cannot precede the payment).

## 7. Dataset generation

`data_core/generator.py` (`SyntheticDataGenerator`) produces a realistic,
**neutral** relational dataset (no hidden model copied from the experiment, no
tuning to make any strategy "win"):

* customers carry consistent historical metrics used across all of their
  transactions;
* amount is lognormal (shared params with the experiment) and weakly correlates
  with customer LTV;
* payment method / bank / failure reason / status use realistic weights;
* each customer has multiple transactions (Poisson per-customer count);
* `days_overdue` is derived from `due_date` and the reference date — internally
  consistent;
* `action_outcomes` are realized from a simple neutral logistic baseline;
  `recovered_amount` is bounded by the transaction amount;
* outcomes are NOT guaranteed to favour any allocator.

Reproducible: same seed → identical dataset. Defaults (seed `42`, 200 customers,
~2000 transactions). Override via `SyntheticDataGenerator(seed)` and
`generate(n_customers=, target_total=)`.

## 8. Dataset splitting

Customer-grouped, leakage-free. All transactions of a customer go to exactly one
split, so:

* no customer appears in two splits (no customer-history leakage),
* no transaction_id appears in two splits,
* the `demo` split is fully disjoint from train/val/test.

Customer historical metrics are static, per-customer properties materialized at
generation — they are **not** derived from the transaction set, so they cannot
leak. The customer grouping additionally prevents Step-2 engineers from
accidentally building customer aggregates across the train/test boundary.

Default fractions (from a single master split seed, independent of the data
seed): train 40%, val 20%, test 20%, demo 20%. Actual counts vary slightly
because transactions are assigned by customer. Split is **reproducible** for a
fixed seed (deterministic permutation of customer ids).

## 9. How to run the pipeline

```bash
# 1. create venv + install (once)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 2. run Step 1 end-to-end (writes data/ + reports/; no DB needed)
.venv/bin/python scripts/run_step1.py

# 3. (optional) also load into PostgreSQL
#    set env vars (see .env.example), then:
RPA_DB_HOST=localhost RPA_DB_USER=rpa RPA_DB_PASSWORD=change_me RPA_DB_SCHEMA=rpa \
  .venv/bin/python scripts/run_step1.py --load-db
```

Artifacts: `data/raw/`, `data/cleaned/`, `data/validated/`,
`data/splits/split_{train,val,test,demo}.csv` + `data/splits/split_manifest.json`,
`reports/data_quality/data_quality_report.{json,md}`.

## 10. How to run the tests

```bash
# full suite (includes the preserved Step 2-5 experiment tests + Step 1 tests)
.venv/bin/python -m pytest

# Step 1 only
.venv/bin/python -m pytest tests/test_step1_data_foundation.py -v

# Step 1 + PostgreSQL round-trip (requires a reachable DB)
RPA_DB_HOST=localhost RPA_DB_USER=rpa RPA_DB_PASSWORD=change_me RPA_DB_SCHEMA=rpa \
  .venv/bin/python -m pytest tests/test_step1_data_foundation.py -v
```

The 13 mandated Step 1 acceptance tests: reproducibility of same seed; duplicate
transaction detection; invalid amount / retry / recovery-amount / categorical
rejection; missing required field rejection; foreign-key validity; date
inconsistency detection; clean records pass validation; cleaning preserves valid
records; split reproducibility; train/test leakage prevention.

## 11. Known limitations

* Synthetic data only — no real Razorpay data yet.
* `recovery_predictions` and `recovery_decisions` are empty placeholders (Step
  2/3 fill them).
* Outcome probabilities are a neutral synthetic baseline, not the experiment's
  hidden ground-truth model.
* CSV is used for artifacts (no parquet engine dependency) to match the existing
  experiment convention; large datasets may want parquet later.
* Customer-grouped splits are approximate on the target counts (can't split a
  customer); acceptable for a data foundation.
* DB loading requires a reachable PostgreSQL and the `RPA_DB_*` env vars; it is
  skipped automatically by tests otherwise.

## 12. What belongs to Step 2 (and must NOT be implemented yet)

* ML recovery prediction (logistic regression / action-conditioned model).
* Feature engineering transforms.
* Training/validation of any model; computing `predicted_recovery_probability`.
* The optimizer / OR-Tools ILP / recovery-decision policy / expected-value
  calculation. Backend APIs, frontend, authentication, deployment.

The data layer exposes clean, validated, split frames and a relational schema so
these can be added without touching Step 1.
