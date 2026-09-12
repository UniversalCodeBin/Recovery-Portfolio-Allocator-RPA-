# Revenue Recovery Portfolio Allocator (RPA)

> Portfolio-level constrained resource allocation for failed-payment recovery, using exact Mixed-Integer Linear Programming.

---

## Overview

RPA treats failed-payment recovery as a **portfolio-level optimization problem**. Instead of deciding recovery actions independently for each transaction, RPA jointly allocates shared scarce resources across the entire batch to maximize total recovered net expected value.

**Core pipeline:**

```
Payment Failure Data
  → ML Recovery Prediction (frozen Logistic Regression)
  → Expected Value Computation (deterministic)
  → Policy Gates (7 hard constraints → ALLOW/BLOCK)
  → Exact ILP Optimization (OR-Tools CBC solver)
  → Recovery Plan (portfolio allocation)
  → Simulated Execution (seeded Monte-Carlo)
  → Reconciliation (planned vs executed verification)
  → Append-Only Audit Trail
```

**Key files:** `rpa/orchestrator.py` (pipeline), `rpa/optimizer.py` (ILP solver), `rpa/policy_engine.py` (gates), `rpa/api.py` (API).

---

## Why Portfolio Optimization?

Failed-payment recovery has multiple possible actions (retry, payment link, message, incentive, human escalation) and **shared resource constraints** (retry quota, messaging capacity, incentive budget, human agent slots).

Independent per-transaction decisions can violate or under-utilize shared constraints. RPA uses an exact ILP solver to find the mathematically optimal allocation across all transactions simultaneously.

---

## Architecture

```
rpa/
  orchestrator.py           # Wires the full batch pipeline
  prediction_service.py     # Frozen-model scoring (never retrains)
  ev_engine.py              # Deterministic expected-value table
  policy_engine.py          # 7 hard gates (ALLOW/BLOCK)
  optimizer.py              # Exact ILP (OR-Tools CBC) + EV-greedy baseline
  strategies.py             # no_action | rule_based | ev_greedy | rpa_optimizer
  execution_simulator.py    # Seeded Monte-Carlo simulation (fail-closed)
  verification.py           # Plan-vs-executed reconciliation
  audit.py                  # Append-only decision trail + explain_selection()
  api.py                    # FastAPI MVP (demo + simulation endpoints)
  api_v1.py                 # Production v1 router (auth, jobs, webhooks)
  api_models.py             # Strict Pydantic request/response models
  auth.py                   # JWT HS256 + RBAC
  security.py               # Password hashing (PBKDF2), token primitives
  webhook.py                # HMAC-SHA256 signature verification + replay protection
  settings.py               # Demo/production mode validation
  database.py               # Production PostgreSQL layer with connection pooling
  ml_versioning.py          # Model artifact integrity + registry
  observability.py          # Prometheus-compatible metrics + health aggregation
  providers.py              # Provider abstraction (demo simulator only)
  execution.py              # Production execution state machine
frontend/                   # React dashboard (6 screens)
database/migrations/        # PostgreSQL DDL (V001–V004)
tests/                      # 188 tests collected — 187 passed, 1 skipped
```

---

## Recovery Actions

| Action | Resource Cost | Direct Cost |
|--------|--------------|-------------|
| `no_intervention` | 0 | ₹0 |
| `retry` | 1 retry slot | ₹1 |
| `payment_link` | 1 message | ₹2 |
| `customer_message` | 1 message | ₹0.50 |
| `incentive` | 1 message + ₹50 budget | ₹25 |
| `human_escalation` | 1 message + 1 human slot | ₹40 |

---

## Optimization Formulation

Exact Mixed-Integer Linear Program solved with OR-Tools CBC:

```
maximize   Σ_{i,a} x[i,a] × net_ev[i,a]
subject to
  Σ_a x[i,a] = 1               for every transaction i  (one action per txn)
  Σ_i x[i,a] × R[a,r] ≤ cap[r]  for every resource r    (shared capacity)
  x[i,a] ∈ {0, 1}
```

Where `R[a,r]` is action `a`'s consumption of resource `r` (retry, messaging, incentive_budget, human_slots). A dedicated no-op action guarantees feasibility.

The EV-greedy baseline processes transactions in descending EV-per-resource ratio, committing each transaction's best affordable action under remaining capacity. RPA must demonstrate value over this strong comparator when resources bind.

---

## Policy Engine

Seven hard policy gates screen every (transaction, action) pair. A blocked action never reaches the optimizer:

1. **Disabled action** — action flagged disabled in data
2. **Blocked list** — action on merchant blocklist
3. **Prohibited combination** — merchant-defined type combos forbidden
4. **Retry limit** — `retry_count ≥ max_retries_per_transaction`
5. **Minimum net EV** — intervention with net EV below threshold blocked
6. **Per-transaction incentive cap** — incentive budget over per-txn limit
7. **Resource exhausted** — insufficient remaining shared capacity

Fail-closed: any system error halts the batch; no plan is produced.

---

## Security

Implemented in the current codebase:

- **JWT Authentication** — HS256 access tokens with expiry, issuer, revocation (`rpa/auth.py`, `rpa/security.py`)
- **RBAC** — roles: ADMIN, MERCHANT_ADMIN, OPERATOR, VIEWER
- **Tenant Scoping** — multi-tenant schema with `tenant_id` on all tables (`V003`, `V004` migrations)
- **Webhook Security** — HMAC-SHA256 signature verification + timestamp-based replay protection (`rpa/webhook.py`)
- **Request IDs** — every request gets a UUID correlation ID
- **Production Execution Guard** — `/recovery/execute` refuses real execution in production mode
- **CORS** — configurable allowed origins, wildcard rejected
- **SQL Injection Protection** — identifier validation, parameterized queries (`data_core/db.py`)

---

## API Endpoints

### Demo API (`rpa/api.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Service health + mode |
| GET | `/versions` | Component versions |
| GET | `/model/metadata` | Frozen model info |
| POST | `/recovery/batch` | Run full recovery batch |
| POST | `/recovery/preview` | Predictions + EV + policy screen |
| POST | `/recovery/strategy/{name}` | Run one strategy |
| POST | `/recovery/compare` | Fair 4-strategy comparison |
| POST | `/recovery/execute` | Simulated execution |
| GET | `/recovery/plan/{batch_id}` | Retrieve plan |
| GET | `/recovery/metrics/{batch_id}` | Batch verifications |
| GET | `/recovery/audit/{batch_id}` | Full decision trail |
| GET | `/recovery/batch/{batch_id}` | Full batch data |
| GET | `/recovery/batches` | List persisted runs |
| GET | `/recovery/actions` | Actions, limits, splits |
| GET | `/recovery/explain/{batch_id}/{txn_id}` | 6-stage explanation |
| POST | `/auth/token` | Issue access token (demo: synthetic) |

### Production v1 API (`rpa/api_v1.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/auth/token` | JWT token issuance |
| POST | `/v1/recovery/jobs` | Create recovery job |
| GET | `/v1/recovery/jobs/{job_id}` | Get job detail |
| GET | `/v1/recovery/jobs` | List jobs |
| POST | `/v1/webhooks/{provider}` | Webhook ingestion |
| POST | `/v1/executions` | Create execution |
| POST | `/v1/executions/{id}/authorize` | Authorize execution |
| POST | `/v1/users` | Create user |
| POST | `/v1/tenants` | Create tenant |
| GET | `/v1/tenants` | List tenants |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, OR-Tools CBC |
| Frontend | React 18.3, TypeScript 5.7, Vite 6.1, Tailwind CSS 3.4 |
| ML | scikit-learn Logistic Regression (frozen) |
| Database | PostgreSQL (optional; demo uses JSON files) |
| Auth | JWT HS256, PBKDF2 password hashing |
| Container | Docker (multi-stage), Docker Compose |
| CI/CD | GitHub Actions (lint, test, security scan, Docker build) |
| Tests | pytest (188 collected — 187 passed, 1 skipped) |

---

## ML Prediction Layer

- **Model**: Action-conditioned Logistic Regression (scikit-learn)
- **Output**: P(recovered=1 | transaction, action) per (transaction, action) pair
- **Calibration**: Selected on validation split by Brier score {none, sigmoid, isotonic}
- **Features**: 6 groups — transaction, customer, temporal, payment, action, interaction (~30 features)
- **Model artifact integrity**: SHA256 verification, registry integration (`rpa/ml_versioning.py`)

**Known metrics** (synthetic data):
- Experiment model test ROC-AUC: 0.776
- Step 2 model test ROC-AUC: 0.544

The predictive performance is modest. This is honest — the system is a research prototype, not a production ML product.

---

## Validation Results

**Experiment design:** 100 runs = 20 seeds × 5 scenarios (A–E with 0–4 binding resources).

| Scenario | Binding Resources | RPA Mean Lift | p-value |
|----------|------------------|---------------|---------|
| A | incentive | +0.23% | 0.0580 |
| B | incentive + human | +0.05% | 0.2164 |
| C | incentive + human + messaging | −0.06% | 0.3575 |
| D | all four | +0.40% | 0.3774 |
| E | none (relaxed) | +0.00% | 1.0 |

**Constrained-scenario mean lift**: +0.15%
**Best Wilcoxon p**: 0.0580
**Verdict**: **NEUTRAL** — the experiment did not establish a statistically significant advantage over the greedy baseline.

RPA ties with greedy in relaxed scenarios (expected) and shows small, statistically insignificant positive lift in some constrained scenarios.

---

## Simulation Notice

**The current implementation uses synthetic data and simulated execution.** The provider layer is designed for integration, but there is no live Razorpay payment execution. No real money moves. No actual customer payments are processed.

---

## Quick Start

```bash
# Create virtual environment and install
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Run tests
.venv/bin/python -m pytest

# Run experiment
.venv/bin/python experiment.py

# Start backend server
.venv/bin/python -m uvicorn rpa.api:app --reload --port 8000

# Start frontend
cd frontend && npm run dev
```

### Docker Compose

```bash
docker-compose up
```

Starts PostgreSQL, Redis, and the RPA API server.

---

## Demo Flow

1. Open `http://localhost:5173`
2. Click **Load Demo Batch** — loads 120 synthetic failed transactions
3. **Overview** — Revenue at Risk, Expected Net EV, Policy Blocks, Resource Budgets
4. **Strategy Comparison** — side-by-side No Action / EV-Greedy / RPA Optimizer
5. **Resource Constraints** — shared capacity visualization and action matrix
6. **Recovery Plan** — transaction-level allocations, click **Explain** on any row
7. **Execution** — click **Run Simulation**, review realized outcomes, verify reconciliation
8. **Audit Trail** — filter by component, inspect JSON payloads, export audit

---

## Project Structure

```
├── config.py                    # Experiment constants
├── data_generation.py           # Synthetic data generator
├── feature_engineering.py       # Feature transforms
├── model.py                     # Experiment model
├── actions.py                   # Action economics
├── expected_value.py            # EV calculations
├── optimizer.py                 # ILP + greedy solvers
├── strategies.py                # 4 strategies
├── outcome_simulator.py         # Seeded simulation
├── metrics.py                   # Metrics + significance
├── experiment.py                # Experiment orchestrator
├── data_core/                   # Step 1: data foundation
├── ml/                          # Step 2: ML package
├── rpa/                         # Step 3: backend decision layer
├── frontend/                    # Step 4: React dashboard
├── database/migrations/         # PostgreSQL DDL (V001–V004)
├── tests/                       # 188 tests
├── Dockerfile                   # Multi-stage container build
├── docker-compose.yml           # PostgreSQL + Redis + API
├── .github/workflows/ci.yml     # CI/CD pipeline
└── .env.example                 # Configuration template
```

---

## Known Limitations

1. **Synthetic data only** — no real Razorpay data
2. **Simulation-only execution** — no real payments, messages, or incentives
3. **Modest ML performance** — test ROC-AUC ≈ 0.544 (Step 2) / 0.776 (experiment) on synthetic data
4. **Neutral experiment result** — no consistent statistical advantage over greedy
5. **No live Razorpay integration** — provider abstraction exists but no real API connection
6. **Demo mode is default** — production mode requires explicit configuration and real database/credentials
7. **File-based persistence in demo** — JSON files in `rpa_runs/`; PostgreSQL is optional
8. **No model monitoring** — no drift detection, retraining pipeline, or A/B testing
9. **Small batch sizes** — tested on 120-transaction batches
10. **No load testing, penetration testing, or compliance validation**

---

## Documentation

- [README.md](README.md) — this file
- [RPA_PROJECT_USER_AND_OPERATIONS_GUIDE.md](RPA_PROJECT_USER_AND_OPERATIONS_GUIDE.md) — comprehensive 30-section user and operations guide
- [RPA_QUICK_USER_GUIDE.md](RPA_QUICK_USER_GUIDE.md) — concise quick-start and demo guide

---

## License

This project is a research prototype built for the Razorpay AI Buildathon. No real Razorpay integration exists. All execution is simulated.
