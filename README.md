# Revenue Recovery Portfolio Allocator (RPA)

> **Research-grade validation experiment for portfolio-level payment recovery optimization under shared resource constraints.**

This repository answers:

> Does constrained multi-resource portfolio optimization (RPA) consistently
> outperform a strong per-transaction EV-ratio greedy baseline when multiple
> shared recovery resources bind simultaneously?

This is a **validation experiment, not a product.** It is designed to be
honest: any outcome (RPA wins / ties / loses) is possible.

**Project roadmap:** The repository is built incrementally across 4 steps:

- **Step 1** — reusable data foundation (schema, cleaning, validation, splitting, PostgreSQL loading)
- **Step 2** — frozen ML model (action-conditioned Logistic Regression + calibration + predictions)
- **Step 3** — backend decision layer (FastAPI, policy gates, exact ILP optimizer, execution simulator, audit trail)
- **Step 4** — React dashboard for judges/merchants (strategy comparison, explainability, audit trail)

> **SIMULATION NOTICE:** All recovery execution metrics and outcomes are produced by a seeded Monte-Carlo simulation layer. No real money moves and no actual payments are processed.

---

## Table of Contents

1. [Install & Run](#1-install--run)
2. [Module Layout](#2-module-layout)
3. [Fair-Comparison Guarantees](#3-fair-comparison-guarantees)
4. [Step 1: Data Foundation](#4-step-1-data-foundation)
5. [Step 2: ML Prediction Layer](#5-step-2-ml-prediction-layer)
6. [Step 3: Backend Decision Layer](#6-step-3-backend-decision-layer)
7. [Step 4: Frontend Dashboard](#7-step-4-frontend-dashboard)
8. [Experiment Results](#8-experiment-results)
9. [Technology Stack](#9-technology-stack)
10. [Testing](#10-testing)
11. [Known Limitations](#11-known-limitations)

---

## 1. Install & Run

```bash
# Create venv + install (once)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Run full test suite
.venv/bin/python -m pytest

# Run full 20-seed x 5-scenario experiment
.venv/bin/python experiment.py

# Run experiment subset
.venv/bin/python experiment.py --scenarios C D
.venv/bin/python experiment.py --seeds 5        # quick smoke run

# Run Step 1 data pipeline
.venv/bin/python scripts/run_step1.py

# Run Step 2 ML pipeline
.venv/bin/python scripts/run_step2.py

# Run Step 3 backend server
.venv/bin/python scripts/run_step3.py server --port 8000

# Run frontend dev server
cd frontend && npm run dev
```

### Outputs

- `results/experiment_report.md` — full report: model metrics, binding analysis, per-scenario strategy tables, RPA-vs-greedy lift + significance, verdict.
- `results/strategy_comparison.csv` — machine-readable aggregated results.
- `results/plots/*.png` — boxplots, RPA lift distributions, calibration curve, utilization bars, action-allocation heatmaps.
- `artifacts/models/<model_id>/` — frozen model artifacts (model.pkl, preprocessor.pkl, calibrator.pkl, metadata.json)
- `artifacts/predictions/` — prediction CSVs for test and demo splits
- `reports/` — data quality reports, model metrics, ablation results, step reports
- `rpa_runs/<batch_id>/` — persisted batch execution results and audit trails

---

## 2. Module Layout

| Module | Responsibility |
|---|---|
| `config.py` | All constants: datasets, seeds, actions, costs, resources, scenarios, ground-truth params |
| `data_generation.py` | Synthetic data + hidden ground-truth recovery model |
| `feature_engineering.py` | Fit-on-train-only feature transforms (no leakage) |
| `model.py` | Frozen action-conditioned Logistic Regression (+ calibration) — experiment version |
| `actions.py` | Action economics, resource consumption, capacity state |
| `expected_value.py` | EV = amount·p − cost; EV-ratio scores |
| `optimizer.py` | OR-Tools CBC exact ILP (one action per txn + capacity constraints) |
| `strategies.py` | Four strategies on identical inputs |
| `outcome_simulator.py` | Shared uniform-draw outcome realization (fair seeds) |
| `metrics.py` | Batch metrics + cross-seed aggregation + significance |
| `visualization.py` | Plots & markdown tables |
| `experiment.py` | Orchestrator (single entry point) |
| `data_core/` | Step 1: reusable data foundation package |
| `ml/` | Step 2: ML package (preprocessing, model, calibration, evaluation, prediction, ablation) |
| `rpa/` | Step 3: backend decision layer (FastAPI, orchestrator, policy, optimizer, simulator, audit) |
| `frontend/` | Step 4: React dashboard |
| `database/` | PostgreSQL schema + migrations |
| `tests/` | 185 backend tests (184 passed, 1 skipped) |
| `scripts/` | Step 1-3 run scripts |

---

## 3. Fair-Comparison Guarantees

1. One global train/val/test split; model trained once and frozen; demo pool fully held out (no leakage).
2. All four strategies consume the **identical** frozen predictions, action set, costs, capacities and transaction batch.
3. `simulate_outcomes_from_draws` draws a single shared U(0,1)^n per batch; every strategy evaluates *its own* actions against the *same* realization.
4. Greedy baseline is a strong capacity-rationed EV greedy: in fully relaxed scenarios it exactly matches the unconstrained optimum (ties with RPA), so any RPA edge is attributable to global multi-resource coupling.
5. Scenario capacities are set from design fractions (not tuned on results) and verified at runtime: A binds 1, B binds 2, C binds 3, D binds 4, E binds 0 resources.

---

## 4. Step 1: Data Foundation

### Purpose
Build a clean, extensible, validated data foundation so that future steps can build feature engineering, ML recovery prediction, recovery decisioning, optimization, backend APIs and frontend dashboards without redesigning the data layer. The RPA thesis was classified NEUTRAL, so this layer intentionally makes no assumptions that would prevent changing the recovery model or the optimization strategy later.

### What was built

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
  migrations/V002__add_rpa_backend.sql     Step 3 backend tables

reports/data_quality/        data-quality report outputs

scripts/
  run_step1.py               end-to-end Step 1 runner
  run_step2.py               Step 2 ML pipeline runner
  run_step3.py               Step 3 backend/server runner

tests/
  test_step1_data_foundation.py   Step 1 test suite
  test_step2_*.py                 Step 2 tests
  test_step3_*.py                 Step 3 tests
  test_*.py                       Core module tests
```

### Database Schema
PostgreSQL-compatible, normalized. Full DDL in `database/schema/rpa_schema.sql`.

**Step 1 tables:** customers, transactions, recovery_actions, action_outcomes, recovery_predictions, resource_constraints, recovery_decisions, audit_logs.

**Step 3 tables:** recovery_runs, candidate_actions, policy_decisions, recovery_plans, executions, verifications, audit_events.

Key constraints: `amount > 0`, `amount <= 100000`, `retry_count >= 0`, `days_overdue >= 0`, `created_at <= updated_at`, every rate in `[0,1]`, `predicted_recovery_probability` in `[0,1]`, `transaction_timestamp <= due_date`, `outcome_timestamp >= attempted_at`, `recovered_amount >= 0`. JSON columns are `jsonb` for future extensibility.

### Data Flow
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

### Cleaning Rules
Operates per-entity on pandas DataFrames via explicit field policies. Detected issues are recorded, never silently fixed:

- **Missing values** — required fields reject the row; optional fields are kept as null; imputed fields are filled with a configured default.
- **Duplicates** — duplicate primary keys are detected and the row is rejected (first occurrence kept).
- **Invalid values** — out-of-range numerics and invalid categoricals reject the row.
- **Date consistency** — inconsistent dates reject the row or are imputed and recorded as a transformation.

### Validation Rules
Applied after cleaning, before DB insertion, using Pydantic v2 for per-record structural checks and explicit cross-record functions:

- **Referential integrity** — foreign key checks across all related tables.
- **Domain** — numeric bounds, probability ranges, valid enums.
- **Uniqueness** — primary keys unique.
- **Required fields** — pydantic rejects missing mandatory fields.
- **Temporal integrity** — timestamp ordering constraints.

### Dataset Splitting
Customer-grouped, leakage-free. All transactions of a customer go to exactly one split:

- No customer appears in two splits (no customer-history leakage).
- No transaction_id appears in two splits.
- The `demo` split is fully disjoint from train/val/test.

Default fractions: train 40%, val 20%, test 20%, demo 20%. Split is reproducible for a fixed seed.

### How to Run Step 1
```bash
# End-to-end (writes data/ + reports/; no DB needed)
.venv/bin/python scripts/run_step1.py

# Also load into PostgreSQL
RPA_DB_HOST=localhost RPA_DB_USER=rpa RPA_DB_PASSWORD=change_me RPA_DB_SCHEMA=rpa \
  .venv/bin/python scripts/run_step1.py --load-db
```

---

## 5. Step 2: ML Prediction Layer

### What was built
Step 2 implements a defensible, leakage-safe ML prediction layer for **P(recovered = 1 | transaction, customer, action)** using a single action-conditioned Logistic Regression, with optional calibration, ablation across four feature groups, and action-conditioned prediction persistence into the `recovery_predictions` table from Step 1.

The previous validation experiment modules are **preserved unchanged** — Step 2 adds a parallel `ml/` package that does not depend on the hidden ground-truth model or the experiment's optimizer.

### Feature Engineering
The feature pipeline builds a per-(transaction, action) feature frame from 6 groups:

| Group | Features |
|---|---|
| Transaction | amount, log_amount, retry_count, days_overdue, transaction_status, amount_over_ltv |
| Customer | customer_ltv, historical_success_rate, historical_recovery_rate, customer_behavior_score, customer_segment, customer_tenure_days |
| Temporal | day_of_week, hour, is_weekend, txn_age_days |
| Payment | payment_method (cat), bank (cat), failure_reason (cat), is_retry_exhausted, is_long_overdue |
| Action | action_type (cat), action_cost, resource flags |
| Interaction | 7 plausible (feature × action) interactions |

Preprocessing: fit-on-train-only z-score normalization + one-hot encoding. No target information is used.

### Model
- **Type**: Action-conditioned Logistic Regression (scikit-learn)
- **Training**: Train on train split, validate on val split, test on test split
- **Calibration**: Chosen on validation split by minimum Brier score among {none, sigmoid (Platt), isotonic}
- **Outputs**: P(recovered=1 | transaction, action) per (transaction, action) pair
- **Artifacts**: model.pkl, preprocessor.pkl, calibrator.pkl, feature_spec.json, feature_names.json, coefficients.csv, metadata.json

### Design Choices
1. **Single action-conditioned model** — shares signal across actions, avoids data fragmentation, keeps calibration uniform.
2. **Calibration on validation only** — test data is never used for calibration selection.
3. **Interaction features** — 7 defensible interactions (not manufactured to make RPA look better).
4. **No optimizer in Step 2** — pure prediction layer only.

### How to Run Step 2
```bash
# Generate features + train + predict + artifacts
.venv/bin/python scripts/run_step2.py

# Also write to PostgreSQL (recovery_predictions)
.venv/bin/python scripts/run_step2.py --save-db

# Step 2 tests
.venv/bin/python -m pytest tests/test_step2_* -v
```

---

## 6. Step 3: Backend Decision Layer

### Core Principle
The LLM/AI never controls money directly. The decision pipeline is a strict, auditable separation of concerns:

```
frozen model (Step 2)  ->  deterministic EV  ->  policy gate (ALLOW/BLOCK)
  ->  optimizer (exact ILP)  ->  simulated execution  ->  verification  ->  audit
```

- The optimizer maximises deterministic net expected value — there is no free-form LLM output in the money path.
- The **policy engine is a hard gate**. A blocked action can never reach the optimizer or the simulator.
- A dedicated no-op action is always allowed, so the problem is always feasible.

### What was built

```
rpa/
  config.py                 # ALL Step 3 tunables: paths, versions, formulas, defaults
  loading.py                # Step 1/2 -> Step 3 bridge (actions, splits, frozen model, CSV)
  prediction_service.py     # frozen-model scoring, input/output validation, never re-trains
  ev_engine.py              # deterministic expected-value table (explicit formula)
  policy_engine.py          # hard-gate policy (ALLOW/BLOCK) + resource-state accounting
  optimizer.py              # exact ILP (OR-Tools CBC) + EV-per-resource greedy baseline
  strategies.py             # no_action | rule_based | ev_greedy | rpa_optimizer
  execution_simulator.py    # seeded, simulation-only execution (fail-closed)
  verification.py           # plan-vs-executed reconciliation
  audit.py                  # full decision trail + explain_selection()
  orchestrator.py           # wires the whole batch pipeline; persists results
  db.py                     # best-effort optional PostgreSQL persistence
  api.py                    # FastAPI MVP (Step 4 contract)

scripts/run_step3.py        # CLI: batch | server | report
tests/test_step3_backend.py # backend tests
tests/test_step3_api.py     # FastAPI endpoint tests

database/migrations/V002__add_rpa_backend.sql   # 7 new tables
```

### Expected-Value Formula
Everything is deterministic and fully expanded per (txn, action):

```
recoverable(txn, action) = amount * (1 - recovery_friction)
gross_expected           = P * recoverable
action_cost              = action's rupee handling cost (Step 1 recovery_actions)
incentive_cost           = incentive_budget_units * incentive_handling_fee   (0 if non-incentive)
total_cost               = action_cost + incentive_cost
net_expected             = gross_expected - total_cost
```

Tunables live in `rpa.config.EVEngineConfig`.

### Policy Gates
Each (txn, action) gets an ALLOW/BLOCK verdict with the triggering rule and relevant limit/usage. Hard gates:

1. `action_disabled` — action flagged disabled in Step 1 data
2. `action_blocked` — action on blocked list
3. `prohibited_combination` — merchant-defined type combos
4. `retry_limit` — retry_count >= max_retries_per_transaction
5. `min_net_ev` — any intervention with net EV below threshold is blocked
6. `max_incentive_per_txn` — incentive budget units over per-txn cap
7. `resource_exhausted` — insufficient remaining shared capacity

The policy screen does not consume resources (it is pure); cumulative budget enforcement happens inside the optimizer.

### Optimizer
Exact Mixed-Integer Linear Program, solved with OR-Tools CBC:

```
maximize   sum_{i,a} x[i,a] * net_ev[i,a]
subject to sum_a x[i,a] == 1                 for every transaction i
           sum_i x[i,a] * R[a,r] <= cap[r]   for every shared resource r
           x[i,a] in {0,1}
```

R[a,r] is action a's consumption of resource r (retry, messaging, incentive_budget, human_slots). One action per transaction is always enforced; the no-op guarantees feasibility.

### Execution, Verification, Audit
- **Execution**: seeded simulation. Only policy-approved actions are executed; anything else is recorded as blocked (fail-closed). On success the recovered amount is recoverable * fraction (fraction drawn in [partial_low, partial_high]).
- **Verification**: reconciles every planned action against its execution row — executed/successful/failed/blocked, recovered amount, cost, net. Any mismatch or missing record fails the batch.
- **Audit**: records batch, predictions, EV, policy, all plans, executions, verifications. `explain_selection(txn_id, strategy)` returns a self-consistent narrative.

### FastAPI Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | service health (simulation_only) |
| GET | `/model/metadata` | frozen model info |
| GET | `/versions` | component versions |
| POST | `/recovery/batch` | run a recovery batch |
| POST | `/recovery/preview` | predictions + EV + policy screen |
| POST | `/recovery/strategy/{name}` | run one strategy |
| POST | `/recovery/compare` | fair comparison of all four strategies |
| POST | `/recovery/execute` | simulated execution of an approved plan |
| GET | `/recovery/plan/{batch_id}` | retrieve a plan |
| GET | `/recovery/metrics/{batch_id}` | batch verifications/metrics |
| GET | `/recovery/audit/{batch_id}` | full decision trail |
| GET | `/recovery/batch/{batch_id}` | retrieve full batch data |
| GET | `/recovery/batches` | list persisted runs |
| GET | `/recovery/actions` | get actions, limits, splits |
| GET | `/recovery/explain/{batch_id}/{txn_id}` | 6-stage explanation |

### Persistence
- **JSON (default):** every run is written to `rpa_runs/{batch_id}/` (`result.json` + `audit.json`). Persistence failures never stop the pipeline.
- **PostgreSQL (optional, best-effort):** writes the same run into 7 tables from `V002__add_rpa_backend.sql`.

### How to Run Step 3
```bash
# Full test suite (Steps 1+2+3)
.venv/bin/python -m pytest -q

# Run one batch end-to-end on the demo split
.venv/bin/python scripts/run_step3.py batch --split demo --seed 42

# Boot the FastAPI server
.venv/bin/python scripts/run_step3.py server --port 8000

# Print a persisted run
.venv/bin/python scripts/run_step3.py report --batch-id <id>
```

---

## 7. Step 4: Frontend Dashboard

### Technology Stack
- **Framework**: React 18.3 (TypeScript)
- **Bundler & Dev Server**: Vite 6.1
- **Styling**: Tailwind CSS 3.4 (custom Razorpay fintech palette)
- **Icons**: Lucide React
- **HTTP Client**: Centralized typed `fetch` client with timeout, error handling, and AbortController

### Views & Components
- **OverviewView**: Revenue at Risk KPI, Expected Net EV, Simulated Net Recovery, Policy Gate Blocks, Strategy Comparison table, Resource Budgets
- **ComparisonView**: 4-strategy fair comparison with metrics table
- **ResourceConstraintsView**: Knapsack capacity visualization, action resource matrix
- **RecoveryPlanView**: Transaction-level allocations with filtering
- **ExecutionView**: Simulated execution ledger, verification results
- **AuditTrailView**: Append-only decision trail, JSON export
- **DecisionExplanationModal**: 6-stage explainable decision chain
- **ConfigureBatchModal**: Custom split, seed, & budget tuning

### Backend Changes for Step 4
To support standard browser SPA requirements:
1. **FastAPI CORSMiddleware**: Added with configurable `CORS_ORIGINS`.
2. **Read-Only Helper Endpoints**: `/recovery/batch/{batch_id}`, `/recovery/batches`, `/recovery/actions`, `/recovery/explain/{batch_id}/{transaction_id}`.
3. **Regression Tests**: Added in `tests/test_step3_api.py`.

### How to Run Step 4
```bash
# Terminal 1: Start FastAPI backend
.venv/bin/python -m uvicorn rpa.api:app --host 127.0.0.1 --port 8000

# Terminal 2: Start frontend dev server
cd frontend
npm run dev
```

Open browser at `http://localhost:5173`.

### Judging Demo Workflow (~30 Seconds to 2 Minutes)
1. **Open Dashboard**: Confirm API connected with green pulse. Click "Load Demo Batch" if no batch is active.
2. **Examine Command Center (Overview)**: Revenue at Risk, Expected Net EV, Policy Gate Blocks, Resource Utilization.
3. **Compare Strategies**: View fair side-by-side benchmark of No Action, Rule-Based, EV-Greedy, RPA Optimizer.
4. **Inspect Resource Constraints**: Review 4 organizational knapsack budgets and action consumption matrix.
5. **Inspect Recovery Plan**: Search/filter transactions. Click "Explain" on any transaction.
6. **Understand Decision Chain**: Follow the 6-stage chain: Revenue at Risk → Model Probability → Expected Value → Policy Gate → Resource Allocation → ILP Decision.
7. **Simulate Execution**: Click "Run Simulation", review realized outcomes, verify 100% reconciliation.
8. **Inspect Audit Trail**: Filter by component, inspect JSON payloads, export audit JSON.

---

## 8. Experiment Results

### Experiment Design
- **Dataset**: Synthetic, 150 demo pool transactions, 120 per batch
- **Scenarios**: A (1 binding resource), B (2 binding), C (3 binding), D (4 binding stress), E (relaxed)
- **Seeds**: 20 independent seeded demo batches per scenario
- **Fair comparison**: All strategies receive identical inputs, same frozen predictions, same outcome realization

### Actual Results

| Scenario | Binding Resources | RPA Mean Lift | Wins/Ties/Losses | 95% CI | p-value (Wilcoxon) |
|---|---|---|---|---|---|
| A | incentive | +0.23% | 10/8/2 | [-0.10, +0.54]% | 0.0580 |
| B | incentive + human | +0.05% | 8/8/4 | [-0.34, +0.39]% | 0.2164 |
| C | incentive + human + messaging | -0.06% | 3/16/1 | [-0.81, +0.48]% | 0.3575 |
| D | all four | +0.40% | 9/5/6 | [-1.39, +2.24]% | 0.3774 |
| E | none (relaxed) | +0.00% | 0/20/0 | [0.00, 0.00]% | 1.0 (all ties) |

**Constrained-scenario mean lift**: +0.15% (wins 30 / ties 37 / losses 13)
**Best paired-test p-value**: 0.0580
**Verdict**: **RPA thesis is NEUTRAL (no consistent statistical advantage)**

### What the Experiment Proves
- The experiment infrastructure is sound and honest (it can detect wins, ties, OR losses)
- RPA ties with greedy in relaxed scenario (E) as expected
- RPA shows small, statistically insignificant positive lift in some constrained scenarios
- The result is NEUTRAL — do not claim RPA outperforms greedy

### What It Does Not Prove
- RPA does not demonstrate consistent statistical superiority over the strong greedy baseline
- No proof of generalizability to real payment data
- No proof of revenue recovery in production

---

## 9. Technology Stack

### Frontend
| Technology | Where Used |
|---|---|
| React 18.3 | `frontend/src/` — all components |
| TypeScript 5.7 | `frontend/src/` — all source files |
| Vite 6.1 | `frontend/vite.config.ts` — dev server and build |
| Tailwind CSS 3.4 | `frontend/src/index.css`, all components |
| Lucide React | All components — icons |
| clsx + tailwind-merge | `components/common/` — className composition |

### Backend
| Technology | Where Used |
|---|---|
| Python 3.11 | All backend modules |
| FastAPI 0.110+ | `rpa/api.py` — REST API |
| Uvicorn | ASGI server |
| Pydantic 2.5+ | Request/response validation |
| OR-Tools 9.8+ | `rpa/optimizer.py` — CBC ILP solver |
| NumPy 1.26+ | All numerical computation |
| Pandas 2.0+ | Data frames throughout |
| scikit-learn 1.3+ | `ml/model.py` — Logistic Regression |
| SciPy 1.11+ | `metrics.py` — Wilcoxon test |

### Database
| Technology | Where Used |
|---|---|
| PostgreSQL (schema) | `database/schema/rpa_schema.sql` |
| psycopg 3.3+ | `data_core/db.py` — optional DB connection |
| JSON files (runtime) | `rpa_runs/` — actual persistence layer |

### Testing
| Technology | Where Used |
|---|---|
| pytest 8.0+ | `tests/` — 185 tests |
| pytest-cov 4.1+ | Coverage |
| FastAPI TestClient | `test_step3_api.py` |
| Playwright 1.63+ | `frontend/tests/example.spec.ts` (boilerplate only) |

---

## 10. Testing

### Total Tests
**185 tests collected. 184 passed, 1 skipped in 11.40s.**

### Backend Tests
- `test_actions.py` — 7 tests
- `test_data_generation.py` — 10 tests
- `test_expected_value.py` — 6 tests
- `test_feature_engineering.py` — 5 tests
- `test_metrics.py` — 7 tests
- `test_model.py` — 5 tests
- `test_optimizer.py` — 11 tests (including ILP vs brute force)
- `test_outcome_simulator.py` — 5 tests
- `test_reproducibility.py` — 4 tests
- `test_step1_data_foundation.py` — 19 tests (1 skipped)
- `test_step2_features.py` — 11 tests
- `test_step2_leakage.py` — 5 tests
- `test_step2_model.py` — 6 tests
- `test_step2_predictions.py` — 6 tests
- `test_step3_api.py` — 18 tests
- `test_step3_backend.py` — 52 tests (prediction, EV, policy, optimizer, strategies, execution, verification, audit, orchestration)
- `test_step5_qa.py` — 3 tests
- `test_strategies.py` — 14 tests

### Frontend/Browser Tests
- **Playwright**: 1 boilerplate test (NOT app-specific)
- **No app-specific Playwright tests exist**
- TypeScript check: 0 errors
- Vite production build: succeeded

---

## 11. Known Limitations

1. **Synthetic data only** — no real Razorpay data yet.
2. **Simulation-only execution** — no real payments, messages, or incentives.
3. **Weak ML performance** — test ROC-AUC ≈ 0.544 (Step 2) / 0.776 (experiment) on synthetic data.
4. **Neutral experiment result** — RPA does not demonstrate consistent statistical superiority over greedy.
5. **No production integration** — no Razorpay API, no webhooks, no real-time event processing.
6. **File-based persistence** — JSON files in `rpa_runs/` are not production-grade.
7. **No authentication/authorization** — API has no auth.
8. **No frontend tests** — only boilerplate Playwright test exists.
9. **Small batch sizes** — tested on 120-transaction batches.
10. **No model monitoring** — no drift detection, retraining pipeline, or A/B testing.
11. **PostgreSQL optional** — schema exists but runtime uses JSON files.
12. **No containerization/CI/CD** — not production-deployed.

---

## Quick Start

```bash
# Install
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Run tests
.venv/bin/python -m pytest

# Run full experiment
.venv/bin/python experiment.py

# Run backend
.venv/bin/python -m uvicorn rpa.api:app --reload --port 8000

# Run frontend
cd frontend && npm run dev
```

---

## Project Structure

```
razorpay/
├── config.py                    # Master config (experiment constants)
├── data_generation.py           # Synthetic data + hidden ground-truth model
├── feature_engineering.py       # Fit-on-train preprocessing
├── model.py                     # Experiment model (Logistic Regression)
├── actions.py                   # Action economics
├── expected_value.py            # EV calculations
├── optimizer.py                 # ILP + greedy solvers
├── strategies.py                # 4 strategies
├── outcome_simulator.py         # Seeded simulation
├── metrics.py                   # Metrics + significance
├── experiment.py                # Experiment orchestrator
├── visualization.py             # Plots and tables
├── data_core/                   # Step 1: data foundation
├── ml/                          # Step 2: ML package
├── rpa/                         # Step 3: FastAPI backend
│   ├── api.py                   # 13 endpoints
│   ├── orchestrator.py          # Pipeline orchestrator
│   ├── prediction_service.py    # Frozen model serving
│   ├── ev_engine.py             # EV calculator
│   ├── policy_engine.py         # Hard gates
│   ├── optimizer.py             # ILP solver
│   ├── strategies.py            # Strategy runner
│   ├── execution_simulator.py   # Simulation
│   ├── verification.py          # Reconciliation
│   └── audit.py                 # Audit trail
├── frontend/                    # Step 4: React dashboard
├── database/                    # PostgreSQL schema + migrations
├── tests/                       # 185 tests
├── scripts/                     # Run scripts
├── artifacts/                   # Model + predictions (gitignored)
├── reports/                     # Generated reports (gitignored)
├── results/                     # Experiment results (gitignored)
├── rpa_runs/                    # Batch runs (gitignored)
└── data/                        # Data artifacts (gitignored)
```

---

## License

This project is a prototype built for the Razorpay AI Buildathon. No real Razorpay integration exists. All execution is simulated.

---

*For complete technical analysis, see `PROJECT_FULL_EXTRACTION.md` and `PROJECT_QUICK_REFERENCE.md`.*
