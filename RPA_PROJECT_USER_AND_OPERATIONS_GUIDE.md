# Revenue Recovery Portfolio Allocator (RPA) — Complete User & Operations Guide

> **Version:** 0.3.0 | **Status:** Research prototype | **Mode:** Demo (default), Production (opt-in)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Quick Start](#2-quick-start)
3. [Project Structure](#3-project-structure)
4. [System Architecture](#4-system-architecture)
5. [Running Modes](#5-running-modes)
6. [Configuration](#6-configuration)
7. [Dashboard / Frontend User Guide](#7-dashboard--frontend-user-guide)
8. [Complete Demo Walkthrough](#8-complete-demo-walkthrough)
9. [Strategy Comparison](#9-strategy-comparison)
10. [Recovery Actions](#10-recovery-actions)
11. [Resource Constraints](#11-resource-constraints)
12. [Policy Engine](#12-policy-engine)
13. [API Documentation](#13-api-documentation)
14. [Authentication and RBAC](#14-authentication-and-rbac)
15. [Webhooks](#15-webhooks)
16. [ML Model Management](#16-ml-model-management)
17. [Database and Persistence](#17-database-and-persistence)
18. [Observability and Health](#18-observability-and-health)
19. [Docker](#19-docker)
20. [Testing](#20-testing)
21. [CI/CD](#21-cicd)
22. [Security](#22-security)
23. [Troubleshooting Guide](#23-troubleshooting-guide)
24. [Common User Questions](#24-common-user-questions)
25. [Developer Navigation Guide](#25-developer-navigation-guide)
26. [Production Deployment Checklist](#26-production-deployment-checklist)
27. [Demo / Presentation Checklist](#27-demo--presentation-checklist)
28. [Known Limitations](#28-known-limitations)
29. [Glossary](#29-glossary)
30. [Final "5-Minute Understanding"](#30-final-5-minute-understanding)

---

## 1. Project Overview

### What is RPA?

**Revenue Recovery Portfolio Allocator (RPA)** is a system that looks at a group of failed payments and decides how limited recovery resources (like retry attempts, SMS quotas, discount budgets, and human agent time) should be allocated to recover the most money.

### Problem Being Solved

When payments fail, businesses have limited resources to recover that revenue. They can retry the payment, send a payment link, offer a discount, escalate to a human agent, or do nothing. Each action costs money and uses shared resources. The question is: **which action should be applied to which failed payment to maximize total recovery?**

### Main Goal

RPA uses mathematical optimization (Mixed-Integer Linear Programming) to find the best allocation of limited recovery resources across a portfolio of failed payments, maximizing expected net recovery value.

### Target Users

- Revenue operations teams at payment-dependent businesses
- Data scientists building recovery optimization systems
- Engineers integrating payment recovery into their platforms

### What RPA Does

- Predicts the probability of recovering each failed payment
- Computes the expected value of each possible recovery action
- Applies policy gates (business rules) to block invalid actions
- Optimally allocates limited resources using ILP
- Simulates execution outcomes
- Verifies that planned actions match executed actions
- Records a complete audit trail of every decision

### What RPA Does NOT Do

- Execute real payment recovery actions (demo mode only)
- Integrate with live payment providers (provider abstraction exists, no live integration)
- Guarantee that optimization beats greedy heuristics (experiment shows NEUTRAL result)
- Replace human judgment in revenue recovery strategy

### Key Terminology

| Term | Simple Explanation |
|------|-------------------|
| **Transaction** | A single failed payment attempt |
| **Portfolio** | The full set of failed payments being considered together |
| **Recovery Action** | Something you can do to try to recover a failed payment (retry, send link, offer discount, etc.) |
| **Resource** | A shared limited capacity (retry quota, messaging quota, discount budget, human agent slots) |
| **Expected Value (EV)** | The estimated net money you expect to recover from an action on a transaction |
| **Policy Gate** | A business rule that blocks certain actions (e.g., "don't retry more than twice") |
| **Optimizer** | The ILP solver that finds the best allocation of actions to transactions |
| **Recovery Plan** | The output: which action to apply to which transaction |
| **Execution** | Carrying out the recovery plan (simulated in demo, real in production) |
| **Verification** | Checking that what was planned matches what was executed |
| **Audit Trail** | A permanent record of every decision made and why |

---

## 2. Quick Start

### Prerequisites

| Requirement | Version | Required? |
|-------------|---------|-----------|
| Python | 3.11+ | Yes |
| Node.js | 18+ (assumed, from Vite 6.x compatibility) | Yes (for frontend) |
| npm | Any recent | Yes (for frontend) |
| PostgreSQL | 16+ | Only for production mode |
| Redis | 7+ | Optional (caching) |
| Docker | Any recent | Optional (alternative to manual setup) |

### Fastest Start (Demo Mode)

```bash
# 1. Clone and enter the project
git clone <repository-url>
cd razorpay

# 2. Create Python virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 3. Run tests to verify installation
python -m pytest tests/ -x --tb=short
# Expected: 188 tests collected — 187 passed, 1 skipped

# 4. Start the backend API server
uvicorn rpa.api:app --host 0.0.0.0 --port 8000 --reload
# Expected: "Uvicorn running on http://0.0.0.0:8000"

# 5. Verify backend is running
curl http://localhost:8000/health
# Expected: {"status":"ok","service":"rpa-backend","step":3,"version":"0.3.0","mode":"demo","simulation_only":true}

# 6. In a new terminal, start the frontend
cd frontend
npm install
npm run dev
# Expected: "Local: http://localhost:5173/"

# 7. Open browser to http://localhost:5173
```

### Start with Docker

```bash
# 1. Clone and enter the project
git clone <repository-url>
cd razorpay

# 2. Copy environment file
cp .env.example .env

# 3. Start all services (API + PostgreSQL + Redis)
docker-compose up

# 4. Open browser to http://localhost:5173
# (You still need to run the frontend manually or build it)
```

### Verify Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "service": "rpa-backend",
  "step": 3,
  "version": "0.3.0",
  "mode": "demo",
  "simulation_only": true
}
```

---

## 3. Project Structure

```
razorpay/
├── rpa/                        # Backend decision layer (Step 3)
│   ├── api.py                  # FastAPI application, all demo endpoints
│   ├── api_v1.py               # Production v1 router (auth, jobs, webhooks)
│   ├── api_models.py           # Pydantic request/response models
│   ├── auth.py                 # JWT authentication & RBAC dependencies
│   ├── security.py             # JWT primitives, password hashing
│   ├── settings.py             # Environment variable configuration
│   ├── config.py               # Central constants, version strings, defaults
│   ├── prediction_service.py   # ML model scoring
│   ├── ev_engine.py            # Expected Value computation
│   ├── policy_engine.py        # 7 policy gates
│   ├── optimizer.py            # ILP optimizer (OR-Tools CBC)
│   ├── strategies.py           # 4 strategy implementations
│   ├── execution_simulator.py  # Monte-Carlo execution simulation
│   ├── verification.py         # Plan vs execution reconciliation
│   ├── audit.py                # Append-only audit trail
│   ├── orchestrator.py         # Batch pipeline orchestrator
│   ├── loading.py              # Data loading, model loading
│   ├── execution.py            # Production execution state machine
│   ├── providers.py            # Payment provider ABCs
│   ├── database.py             # PostgreSQL connection pool & repositories
│   ├── db.py                   # Legacy best-effort DB persistence
│   ├── ml_versioning.py        # Model artifact integrity & registry
│   ├── webhook.py              # HMAC-SHA256 webhook verification
│   └── observability.py        # Prometheus-compatible metrics
│
├── frontend/                   # React dashboard (Step 4)
│   ├── src/
│   │   ├── App.tsx             # Main app, state management, routing
│   │   ├── services/api.ts     # API client (all backend calls)
│   │   ├── types/api.ts        # TypeScript type definitions
│   │   └── components/
│   │       ├── views/          # 6 main screens
│   │       ├── modals/         # 2 modal dialogs
│   │       └── common/         # 9 shared components
│   └── package.json
│
├── ml/                         # ML prediction layer (Step 2)
├── data_core/                  # Data foundation (Step 1)
├── data/                       # Raw, cleaned, validated, split data
├── artifacts/                  # Model artifacts, predictions
├── database/migrations/        # SQL migration files (V001-V004)
├── tests/                      # 188 tests collected
├── scripts/                    # Pipeline runner scripts
├── results/                    # Experiment results & plots
├── rpa_runs/                   # Persisted batch run outputs
│
├── Dockerfile                  # Multi-stage Docker build
├── docker-compose.yml          # API + PostgreSQL + Redis
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── pytest.ini                  # Test configuration
├── README.md                   # Project overview
└── .github/workflows/ci.yml   # CI/CD pipeline
```

### Key Files by Purpose

| Need | File | Why |
|------|------|-----|
| Change API behavior | `rpa/api.py`, `rpa/api_v1.py` | All endpoint definitions |
| Modify business rules | `rpa/policy_engine.py` | 7 policy gates |
| Change optimization | `rpa/optimizer.py` | ILP solver, constraints |
| Add new strategies | `rpa/strategies.py` | Strategy runner |
| Change ML model | `rpa/prediction_service.py`, `ml/` | Model loading, scoring |
| Modify execution | `rpa/execution_simulator.py` | Monte-Carlo simulation |
| Change configuration | `rpa/settings.py`, `.env` | All env vars |
| Add new API models | `rpa/api_models.py` | Pydantic schemas |
| Modify frontend screens | `frontend/src/components/views/` | React components |
| Add database tables | `database/migrations/` | SQL migrations |
| Change Docker setup | `Dockerfile`, `docker-compose.yml` | Container config |
| Run tests | `tests/` | 21 test files, 188 collected |
| Add webhooks | `rpa/webhook.py` | HMAC verification |
| Modify auth | `rpa/auth.py`, `rpa/security.py` | JWT, RBAC |

---

## 4. System Architecture

### The Complete Pipeline

```
Payment Failure Data
        │
        ▼
┌─────────────────┐
│  ML Prediction   │  Frozen logistic regression predicts P(recovery)
│  Service         │  for each (transaction, action) pair
└────────┬────────┘
         │ probabilities (n_transactions × n_actions matrix)
         ▼
┌─────────────────┐
│ Expected Value   │  EV = P × amount - action_cost - incentive_cost
│ Engine           │  Computes net expected value for every candidate
└────────┬────────┘
         │ EV table (transaction × action → net EV)
         ▼
┌─────────────────┐
│ Policy Engine    │  7 hard gates check business rules
│ (7 Gates)        │  BLOCK or ALLOW each candidate action
└────────┬────────┘
         │ filtered EV table (blocked candidates masked)
         ▼
┌─────────────────┐
│ ILP Optimizer    │  OR-Tools CBC solver
│ (or Greedy)      │  Maximize total net EV subject to resource caps
└────────┬────────┘
         │ portfolio plan (action per transaction)
         ▼
┌─────────────────┐
│ Execution        │  Monte-Carlo simulation (demo)
│ Simulator        │  or real provider calls (production)
└────────┬────────┘
         │ execution results (recovered amounts, costs)
         ▼
┌─────────────────┐
│ Verification     │  Reconciles planned vs executed
│ Layer            │  Flags mismatches, missing executions
└────────┬────────┘
         │ verified results
         ▼
┌─────────────────┐
│ Audit Trail      │  Every decision recorded with full context
│                  │  JSON output for each batch
└─────────────────┘
```

### Stage-by-Stage Details

#### Stage 1: ML Prediction

| Aspect | Detail |
|--------|--------|
| **What enters** | Transaction data (amount, customer_id), customer features, action specs |
| **What happens** | A frozen logistic regression model scores each (transaction, action) pair |
| **What comes out** | Probability matrix: P(recovery) for each combination |
| **Implementation** | `rpa/prediction_service.py` using `ml/` package |
| **Why it exists** | Without probability estimates, you cannot compute expected value |
| **What can go wrong** | Missing features, wrong model version, NaN in probabilities |

The model is `rpa-recovery-logreg-full-v1` — a logistic regression trained on synthetic payment failure data with 6 feature groups (payment, customer, action, temporal, interaction, transaction features).

#### Stage 2: Expected Value

| Aspect | Detail |
|--------|--------|
| **What enters** | Probabilities, transaction amounts, action costs, incentive costs |
| **What happens** | `EV = P × recoverable_amount - action_cost - incentive_cost` |
| **What comes out** | EV table with net expected value for every (transaction, action) pair |
| **Implementation** | `rpa/ev_engine.py` |
| **Why it exists** | Converts raw probabilities into actionable economic signals |
| **What can go wrong** | Negative EV candidates, missing cost data |

The `recoverable_amount = amount × (1 - recovery_friction)`. Default `recovery_friction = 0.0` and `incentive_handling_fee = 5.0` INR.

#### Stage 3: Policy Engine (7 Gates)

| Aspect | Detail |
|--------|--------|
| **What enters** | EV table, transaction data, resource state |
| **What happens** | Each candidate action passes through 7 sequential gates |
| **What comes out** | Verdicts: ALLOW or BLOCK for each (transaction, action) pair |
| **Implementation** | `rpa/policy_engine.py` |
| **Why it exists** | Enforce business rules before optimization |
| **What can go wrong** | Overly restrictive rules may block all candidates |

The 7 gates are documented in detail in [Section 12: Policy Engine](#12-policy-engine).

#### Stage 4: ILP Optimizer

| Aspect | Detail |
|--------|--------|
| **What enters** | Filtered EV table (blocked candidates masked to -1e6), resource capacities |
| **What happens** | CBC solver finds optimal action assignment maximizing total net EV |
| **What comes out** | Portfolio plan: exactly one action per transaction |
| **Implementation** | `rpa/optimizer.py` using OR-Tools CBC |
| **Why it exists** | Optimal resource allocation across competing transactions |
| **What can go wrong** | Infeasible problem, solver timeout, suboptimal solution |

Decision variables: `x[i,a] ∈ {0,1}` (assign action `a` to transaction `i`).

Constraints:
- Each transaction gets exactly one action
- Total resource usage ≤ capacity for each resource

Objective: Maximize `Σ x[i,a] × net_ev[i,a]`

Solver timeout: 30 seconds (configurable via `OptimizerConfig.time_limit_seconds`).

#### Stage 5: Execution

| Aspect | Detail |
|--------|--------|
| **What enters** | Recovery plan, transaction data, probabilities |
| **What happens** | Each planned action is executed (simulated or real) |
| **What comes out** | Execution results: recovered amounts, costs, success/failure |
| **Implementation** | `rpa/execution_simulator.py` (demo), `rpa/execution.py` (production state machine) |
| **Why it exists** | Determine actual recovery outcomes |
| **What can go wrong** | Simulation randomness, provider failures (production) |

In demo mode, outcomes are drawn via seeded Monte-Carlo: success probability = predicted P(recovery). On success, a fraction of the recoverable amount is drawn uniformly from `[0, 1]`.

#### Stage 6: Verification

| Aspect | Detail |
|--------|--------|
| **What enters** | Planned actions, executed actions |
| **What happens** | Reconciles planned vs actual for every transaction |
| **What comes out** | Verification report: which actions matched, which failed |
| **Implementation** | `rpa/verification.py` |
| **Why it exists** | Ensure planned actions were actually executed correctly |
| **What can go wrong** | Missing execution records, action mismatches |

#### Stage 7: Audit

| Aspect | Detail |
|--------|--------|
| **What enters** | All events from pipeline stages |
| **What happens** | Records every decision with timestamps, versions, context |
| **What comes out** | JSON audit file per batch: `rpa_runs/{batch_id}/audit.json` |
| **Implementation** | `rpa/audit.py` |
| **Why it exists** | Traceability, debugging, compliance |
| **What can go wrong** | Disk write failures (demo), DB write failures (production) |

Recorded components: `batch`, `prediction`, `ev`, `policy`, `optimizer`, `execution`, `verification`.

---

## 5. Running Modes

### Demo Mode (Default)

| Aspect | Detail |
|--------|--------|
| **What it is** | Full pipeline using synthetic data and simulated execution |
| **Why it exists** | Safe demonstration without real money or infrastructure |
| **How to start** | `RPA_MODE=demo` (default, no configuration needed) |
| **Data used** | Synthetic transactions, customers, actions in `data/` |
| **Actions** | All simulated — no real payment retries, messages, or discounts sent |
| **Execution** | Monte-Carlo simulation with seeded randomness |
| **Database** | Not required — results stored as JSON files in `rpa_runs/` |
| **Auth** | No real authentication — returns synthetic "demo-token" |
| **Safe to demonstrate** | Yes — zero risk to real money |

**Important:** Demo execution does NOT move real money. All recovery outcomes are simulated.

### Production Mode

| Aspect | Detail |
|--------|--------|
| **How to enable** | Set `RPA_MODE=production` |
| **Required infrastructure** | PostgreSQL database, authentication secrets, webhook secrets |
| **Required configuration** | `RPA_DATABASE_URL`, `RPA_AUTH_SIGNING_KEY`, `RPA_WEBHOOK_SIGNING_SECRET` |
| **Execution** | Blocked at `/recovery/execute` — use `/v1/recovery/jobs` instead |
| **Database** | PostgreSQL with connection pooling (psycopg_pool) |
| **Auth** | Real JWT authentication with role-based access control |
| **Webhooks** | HMAC-SHA256 signature verification with replay protection |
| **Provider integration** | Abstract provider interfaces exist (`rpa/providers.py`) but no live payment provider is integrated |

**Important:** Even in production mode, no live Razorpay payment execution is integrated. The provider abstraction (`RecoveryActionExecutor`, `PaymentEventProvider`) exists as interfaces ready for integration, with only `SimulatorProvider` implemented.

---

## 6. Configuration

### Environment Variables

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

| Variable | Required? | Default | Purpose | Demo | Production |
|----------|-----------|---------|---------|------|------------|
| `RPA_MODE` | Yes | `demo` | `demo` or `production` mode | `demo` | `production` |
| `RPA_DATABASE_URL` | Production only | `None` | PostgreSQL connection string | Not needed | `postgresql://user:pass@host:5432/dbname` |
| `RPA_DB_POOL_MIN_SIZE` | No | `1` | Min DB connections | Not used | `1`-`10` |
| `RPA_DB_POOL_MAX_SIZE` | No | `10` | Max DB connections | Not used | `10` |
| `RPA_DB_POOL_ACQUIRE_TIMEOUT_SECONDS` | No | `5` | DB pool timeout | Not used | `5` |
| `RPA_AUTH_SIGNING_KEY` | Production only | `None` | HS256 JWT signing key (min 32 chars) | Not needed | Generate: `openssl rand -base64 32` |
| `RPA_AUTH_ISSUER` | No | `rpa` | JWT issuer claim | `rpa` | `rpa` |
| `RPA_ACCESS_TOKEN_TTL_SECONDS` | No | `900` | Token TTL (60-86400) | `900` | `900` |
| `RPA_WEBHOOK_SIGNING_SECRET` | Production only | `None` | HMAC secret for webhooks (min 32 chars) | Not needed | Generate: `openssl rand -base64 32` |
| `RPA_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` | No | `300` | Replay protection window (seconds) | `300` | `300` |
| `RPA_CORS_ORIGINS` | No | `http://localhost:5173` | Comma-separated allowed origins | `http://localhost:5173` | Explicit origins only, no `*` |
| `RPA_REQUEST_MAX_BYTES` | No | `1048576` | Max request body size (bytes) | `1048576` | `1048576` |
| `RPA_MODEL_ARTIFACT_PATH` | No | `artifacts/models/rpa-recovery-logreg-full-v1` | Model artifact directory | Works | Must exist |
| `RPA_DEMO_DATA_PATH` | No | `data` | Demo data directory | `data` | Not used |

### Frontend Environment

| File | Variable | Default | Purpose |
|------|----------|---------|---------|
| `frontend/.env` | `VITE_API_BASE_URL` | `http://localhost:8000` | Backend API base URL |

### Generating Secrets

```bash
# JWT signing key (min 32 characters)
openssl rand -base64 32

# Webhook HMAC secret (min 32 characters)
openssl rand -base64 32
```

### Production Validation

When `RPA_MODE=production`, the application will refuse to start if:
- `RPA_DATABASE_URL` is not set
- `RPA_AUTH_SIGNING_KEY` is not set or is shorter than 32 characters
- `RPA_WEBHOOK_SIGNING_SECRET` is not set or is shorter than 32 characters
- `RPA_CORS_ORIGINS` does not contain at least one explicit origin

---

## 7. Dashboard / Frontend User Guide

The frontend is a React 18.3 + TypeScript + Vite + Tailwind CSS single-page application with a tab-based navigation. There is no React Router — state drives which view is displayed.

### Screen 1: Overview (Command Center)

**Location:** Default view when the app loads.

**Purpose:** High-level summary of the current recovery batch.

**What You See:**
- 4 KPI Cards: Revenue at Risk (total INR of failed payments), Expected Net EV (RPA), Simulated Net Recovery, Policy Gate Blocks
- Strategy Comparison Table: 3 strategies (No Action, EV-Greedy, RPA Optimizer) with their selection logic, expected EV, simulated net, cost, and status
- Resource Budgets Panel: 4 progress bars showing consumed vs capacity for Retry, Messaging, Incentive Budget, Human Slots
- Empty state with "Load Demo Batch" button when no batch is loaded

**How To Use It:**
1. Click "Load Demo Batch" if no batch is loaded
2. Review KPIs at the top
3. Scroll down to see strategy comparison and resource usage
4. Click "Full Comparison" to go to the Comparison tab
5. Click "Inspect Recovery Plan" to go to the Plan tab

**When To Use It:** First thing when opening the dashboard — gives a quick health check of the recovery batch.

### Screen 2: Strategy Comparison

**Location:** Sidebar → "Strategy Comparison" (tab 2)

**Purpose:** Fair side-by-side comparison of all 4 strategies on the same batch.

**What You See:**
- Batch Seed input + "Re-run Comparison" button
- Comparison table with 4 rows: No Action (Baseline), Rule-Based Heuristic, EV-Greedy Comparator, RPA Optimizer (ILP)
- Columns: Strategy description, Planned Net EV, Simulated Gross, Cost, Simulated Net, Success/Total, Resource Usage (retry + messaging), Verification status
- Scientific Transparency Card explaining why EV-Greedy and RPA achieve similar results

**How To Use It:**
1. View the current comparison (auto-loaded from the batch)
2. Change the Batch Seed number to test different random seeds
3. Click "Re-run Comparison" to regenerate with a new seed

**When To Use It:** To evaluate whether optimization provides value over simpler heuristics.

### Screen 3: Resource Constraints

**Location:** Sidebar → "Resources" (tab 3)

**Purpose:** Visualize shared resource constraints and how actions consume them.

**What You See:**
- 4 Resource Meter cards (2×2 grid): Smart Retry Limit, Customer Messaging Quota, Incentive Discount Budget, Human Escalation Desk
- Action Resource Requirements Matrix: table showing how each action consumes resources

**Resource Matrix (verified from code):**

| Action | Direct Cost | Retry | Messaging | Incentive Budget | Human Slots |
|--------|------------|-------|-----------|-----------------|-------------|
| No Intervention | INR 0.00 | 0 | 0 | 0 | 0 |
| Smart Retry | INR 1.00 | 1 | 0 | 0 | 0 |
| Payment Link | INR 2.00 | 0 | 1 | 0 | 0 |
| Customer Message | INR 0.50 | 0 | 1 | 0 | 0 |
| Incentive | INR 25.00 | 0 | 1 | 50.0 | 0 |
| Human Escalation | INR 40.00 | 0 | 1 | 0 | 1 |

**When To Use It:** To understand why certain actions were blocked (resource exhaustion).

### Screen 4: Recovery Plan

**Location:** Sidebar → "Recovery Plan" (tab 4)

**Purpose:** Detailed view of which action was assigned to each transaction.

**What You See:**
- Strategy tabs (switch between strategies)
- Search by Transaction ID, Action Filter dropdown, Sort options
- Table: Transaction ID, Amount, Chosen Action (color-coded badge), P(Recovery)%, Gross EV, Cost, Net EV, Policy Gate status, "Explain" button
- Pagination (50 records per page)

**How To Use It:**
1. Select a strategy tab (default: `rpa_optimizer`)
2. Search or filter to find specific transactions
3. Click "Explain" on any row to open the Decision Explanation modal

**When To Use It:** To inspect individual transaction decisions and understand why a specific action was chosen.

### Screen 5: Execution

**Location:** Sidebar → "Execution" (tab 5)

**Purpose:** Run simulated execution and view reconciliation results.

**What You See:**
- Strategy selector dropdown, Seed input, "Run Simulation" button
- 4 KPI Cards: Recovered (Gross), Execution Costs, Net Realized Amount, Success/Failed count
- Reconciliation Ledger table: Transaction ID, Planned Action, Executed Action, Planned EV, Recovered, Cost, Net Realized, Outcome, Verified status
- Simulation disclaimer banner

**How To Use It:**
1. Select a strategy from the dropdown
2. Enter a simulation seed (or leave default)
3. Click "Run Simulation"
4. Review the results — look for any "Failed" or unverified rows

**When To Use It:** To test how a recovery plan would perform under Monte-Carlo simulation.

### Screen 6: Audit Trail

**Location:** Sidebar → "Audit Trail" (tab 6)

**Purpose:** View the complete append-only decision log for the current batch.

**What You See:**
- Search bar (by Audit ID or Event Type)
- Component filter dropdown (ALL, batch, prediction, ev, policy, optimizer, execution, verification)
- "Export Audit JSON" button
- Timeline of expandable event cards showing: event number, event type, component badge, entity ID, audit ID, timestamp
- Expanded view shows full JSON metadata

**When To Use It:** To trace exactly why a specific decision was made, or for debugging.

### Modals

#### Decision Explanation Modal

**Trigger:** Click "Explain" on any row in the Recovery Plan view.

**Shows 6 stages:**
1. Revenue at Risk — transaction amount + chosen action
2. Frozen ML Prediction — P(Recovery) %, model identifier
3. Deterministic Expected Value — formula breakdown (Gross EV, Cost, Net EV)
4. Policy Gate Screen — ALLOW/BLOCK, which rule triggered
5. Portfolio ILP Decision — which action was selected
6. Verification — execution status, recovered amount, reconciliation result

#### Configure Batch Modal

**Trigger:** Click the Settings gear icon in the Navbar.

**Form Fields:**
- Dataset Split (demo, val, test, train)
- Simulation Random Seed
- 4 Resource Limit inputs: Retry Quota, Messaging Quota, Incentive Budget (INR), Human Slots
- Strategy checkboxes: no_action, rule_based, ev_greedy, rpa_optimizer

### Common Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `Navbar` | Top bar | Brand name, batch selector, Load Demo button, Settings gear, versions info, health badge |
| `Sidebar` | Left panel | 6 navigation tabs with tags, pipeline flow diagram |
| `KPICard` | Various views | Metric card with title, value, subtitle, icon |
| `ActionBadge` | Plan/Execution views | Color-coded action type badges (blue=retry, purple=payment_link, etc.) |
| `StatusBadge` | Various views | Status indicators (green=allow/success, red=block/fail, amber=pending) |
| `ResourceMeter` | Overview/Resources | Progress bar showing consumed/capacity with percentage |
| `SimulationDisclaimer` | Execution view | Amber warning banner: "Simulation Mode Active — Zero-Risk Money Path" |
| `ErrorBanner` | Top of main area | Red alert banner with dismiss |
| `LoadingSpinner` | Various | Animated loader with configurable message |

---

## 8. Complete Demo Walkthrough

### Step 1: Start the Application

```bash
# Terminal 1: Backend
source .venv/bin/activate
uvicorn rpa.api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open browser to `http://localhost:5173`.

### Step 2: Load the Demo Batch

1. Click **"Load Demo Batch"** button in the Navbar (or the Overview empty state)
2. Wait for the loading spinner to complete
3. Expected result: Overview tab shows 4 KPI cards populated with data

### Step 3: Review the Overview

1. Note the **Revenue at Risk** — total INR value of all failed transactions in the batch
2. Note the **Expected Net EV** — what the optimizer predicts it can recover minus costs
3. Note the **Simulated Net Recovery** — actual simulated recovery after Monte-Carlo execution
4. Note the **Policy Gate Blocks** — how many candidates were blocked by policy rules
5. Review the **Strategy Comparison Table** — see how No Action, EV-Greedy, and RPA Optimizer compare
6. Review the **Resource Budgets** — see how much of each resource was consumed

### Step 4: Compare Strategies

1. Click **"Strategy Comparison"** in the sidebar
2. Review the 4-strategy comparison table
3. Note the Planned Net EV, Simulated Net, and Verification status for each
4. Read the Scientific Transparency Card at the bottom

### Step 5: Inspect Resource Constraints

1. Click **"Resources"** in the sidebar
2. Review the 4 resource meters
3. Study the Action Resource Requirements Matrix

### Step 6: Inspect the Recovery Plan

1. Click **"Recovery Plan"** in the sidebar
2. Ensure the `rpa_optimizer` tab is selected
3. Browse the table — each row is a transaction with its assigned action
4. Notice some transactions get `no_intervention` (when resources are exhausted or EV is too low)

### Step 7: Open Decision Explanation

1. Click the **"Explain"** button on any row in the Recovery Plan
2. Review the 6-stage decision chain in the modal
3. Close the modal

### Step 8: Run Simulated Execution

1. Click **"Execution"** in the sidebar
2. Ensure strategy is set to `rpa_optimizer`
3. Click **"Run Simulation"**
4. Review the KPIs and Reconciliation Ledger
5. Check that verification shows PASS for all rows

### Step 9: Review Audit Trail

1. Click **"Audit Trail"** in the sidebar
2. Browse the event timeline
3. Click on any event to expand and see full JSON metadata
4. Use the component filter to see only policy events, for example
5. Click **"Export Audit JSON"** to download the full audit

---

## 9. Strategy Comparison

### Available Strategies

| Strategy | How It Works | Resource-Aware? | Advantages | Limitations |
|----------|-------------|----------------|------------|-------------|
| `no_action` | Selects `no_intervention` for every transaction | No | Baseline — shows what happens with zero intervention | No recovery attempted |
| `rule_based` | Deterministic rules based on amount, overdue days, and success probability | No | Simple, explainable, no optimization needed | Doesn't consider shared resources; not included in default batch runs |
| `ev_greedy` | Picks the action with highest EV-per-resource-unit for each transaction, respects caps | Yes | Fast, near-optimal for many scenarios | Greedy — may miss globally optimal allocation |
| `rpa_optimizer` | Exact ILP (Mixed-Integer Linear Programming) via OR-Tools CBC | Yes | Mathematically optimal allocation | Slower (up to 30s solver timeout); on synthetic data, similar to greedy |

### Default Batch Strategies

When no strategies are specified, the batch runs: `["no_action", "ev_greedy", "rpa_optimizer"]`. The `rule_based` strategy is excluded by default.

### Strategy Selection Logic (Rule-Based)

The `RuleBasedEngine` in `rpa/strategies.py` uses these rules (in priority order):

1. **Human Escalation** if: amount ≥ 5000 AND overdue ≥ 30 days AND success probability ≤ 0.4
2. **Incentive** if: amount ≥ 1500 AND overdue ≥ 7 days
3. **Payment Link** if: amount ≥ 1500
4. **Retry** if: retries < 2
5. **Customer Message** if: success probability ≥ 0.6
6. **No Action** (fallback)

### Experiment Result (Honest Assessment)

The project ran a 20-seed × 5-scenario experiment (`experiment.py`). The result: **NEUTRAL** — RPA does not demonstrate consistent statistical superiority over the greedy baseline on synthetic data.

This is because:
- Synthetic data has uniform characteristics
- With homogeneous transactions, greedy allocation is near-optimal
- The ILP advantage appears when transactions have diverse resource requirements and costs
- The project acknowledges this honestly in the README and in the Comparison view's "Scientific Transparency Card"

**Do NOT claim RPA always beats greedy.** The experiment shows neutral results.

---

## 10. Recovery Actions

| Action | Purpose | When Selected | Direct Cost | Resources Used | Simulated? |
|--------|---------|---------------|-------------|----------------|------------|
| `no_intervention` | Do nothing | Default fallback, when resources exhausted or EV too low | INR 0 | None | N/A |
| `retry` | Retry the failed payment | When retry count < 2 and action has positive EV | INR 1 | 1 retry capacity | Yes |
| `payment_link` | Send a payment link to the customer | When amount ≥ 1500 or has positive EV | INR 2 | 1 messaging quota | Yes |
| `customer_message` | Send a reminder/notification message | When success probability ≥ 0.6 | INR 0.50 | 1 messaging quota | Yes |
| `incentive` | Offer a discount to incentivize payment | When amount ≥ 1500 and overdue ≥ 7 days | INR 25 + 50 budget | 1 messaging + 50 incentive_budget | Yes |
| `human_escalation` | Escalate to a human agent | When amount ≥ 5000, overdue ≥ 30 days, low success probability | INR 40 | 1 messaging + 1 human_slot | Yes |

**About "incentive":** This action offers the customer a discount (e.g., 50 INR off) to encourage them to complete the payment. It costs INR 25 in handling fees plus INR 50 from the shared incentive budget.

**Important:** All execution is simulated in demo mode. No real discounts, messages, or retries are sent.

---

## 11. Resource Constraints

### The Four Resource Types

| Resource | What It Limits | Default Capacity | Consumed By |
|----------|---------------|-----------------|-------------|
| `retry` | Number of payment retry attempts | 2,000 | Smart Retry |
| `messaging` | Number of messages/links that can be sent | 2,000 | Payment Link, Customer Message, Incentive, Human Escalation |
| `incentive_budget` | Total discount budget in INR | 5,000 INR | Incentive (50 INR per use) |
| `human_slots` | Number of human escalation cases | 50 | Human Escalation |

### How Resources Affect Optimization

The optimizer treats these as hard constraints. If 2,000 retries are available and 370 transactions need action, the optimizer must decide which 2,000 (or fewer) retries to use and which transactions to assign other actions or no action.

### Example

Consider 100 failed transactions with these limits:
- 30 retries available
- 20 messages available
- 5,000 INR incentive budget
- 5 human escalation slots

The optimizer might:
1. Assign 5 high-value, low-probability transactions to human escalation (using 5 slots + 5 messages)
2. Assign 20 high-EV transactions to retry (using 20 retries)
3. Assign 15 medium-EV transactions to payment links (using 15 messages)
4. Assign 5 high-EV transactions to incentives (using 5 messages + 250 INR)
5. Assign the remaining 55 transactions to no_intervention (resources exhausted or EV too low)

Total: 30 retries used (limit: 30), 20 messages used (limit: 20), 250 INR used (limit: 5,000), 5 human slots used (limit: 5).

### Resource Accounting

Resource consumption is tracked from `ActionSpec.resource_requirements` loaded from action definitions (e.g., `recovery_actions.csv`). The optimizer sums `_resource_consumption(action)` for each selected action per resource type. The `resource_used` field in `BatchResult.to_dict()` is populated from the actual selected actions — not from capacity defaults.

The frontend Resource Constraints view displays a reference matrix showing per-action resource requirements. This matrix is documentation only; actual consumption is computed in the backend optimizer (`rpa/optimizer.py`).

---

## 12. Policy Engine

### All 7 Gates (in evaluation order)

| # | Gate Name | Rule String | What It Checks | What Happens When It Fails |
|---|-----------|-------------|----------------|---------------------------|
| 1 | Disabled action | `action_disabled` | Is the action marked as disabled in the action spec? | BLOCK — action cannot be used |
| 2 | Blocked action list | `action_blocked` | Is the action_id or action_type on the `blocked_actions` list? | BLOCK — action is explicitly banned |
| 3 | Prohibited combination | `prohibited_combination` | Is this action type in a prohibited combination pair? | BLOCK — action combination not allowed |
| 4 | Retry limit | `retry_limit` | Has this transaction already been retried ≥ `max_retries_per_transaction` times? | BLOCK — cannot retry more |
| 5 | Min net EV | `min_net_ev` | Is the net expected value below `min_net_ev_threshold`? | BLOCK — not worth the cost |
| 6 | Per-transaction incentive cap | `max_incentive_per_txn` | Does the incentive amount exceed `max_incentive_per_transaction`? | BLOCK — too much discount |
| 7 | Resource exhaustion | `resource_exhausted` | Is there remaining capacity for this action's resource requirements? | BLOCK — out of shared resources |

If none of these triggers, the verdict is **ALLOW** with `rule="ok"`.

### Default Policy Configuration

From `rpa/config.py`:
- `min_net_ev_threshold`: 0.0 (block negative EV)
- `max_incentive_per_transaction`: 5,000.0 INR
- `max_retries_per_transaction`: 2
- `blocked_actions`: [] (none blocked by default)
- `prohibit_combination`: [] (no combinations prohibited)

### Fail-Closed Behavior

The policy engine evaluates every (transaction, action) pair independently. If a transaction has no ALLOWed actions, it defaults to `no_intervention`. This is fail-closed: the system never forces an invalid action through.

---

## 13. API Documentation

### Demo API Endpoints (api.py)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | No | Service health check |
| GET | `/versions` | No | Component version info |
| GET | `/model/metadata` | No | ML model metadata |
| GET | `/recovery/actions` | No | Available actions, default limits, splits |
| GET | `/recovery/batches` | No | List all persisted batch runs |
| GET | `/recovery/batch/{batch_id}` | No | Full batch data |
| GET | `/recovery/plan/{batch_id}` | No | Recovery plan for a batch |
| GET | `/recovery/metrics/{batch_id}` | No | Batch verification metrics |
| GET | `/recovery/audit/{batch_id}` | No | Audit trail JSON |
| GET | `/recovery/explain/{batch_id}/{transaction_id}` | No | 6-stage decision explanation (query: `?strategy=rpa_optimizer`) |
| POST | `/recovery/batch` | No | Create and run a recovery batch |
| POST | `/recovery/preview` | No | Preview EV + policy screening |
| POST | `/recovery/strategy/{strategy_name}` | No | Run a single strategy |
| POST | `/recovery/compare` | No | Run all strategies for comparison |
| POST | `/recovery/execute` | No | Execute plan (simulation only; blocked in production) |
| POST | `/auth/token` | No | Get access token (demo returns synthetic token) |

### Production v1 API Endpoints (api_v1.py)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/v1/auth/token` | No | Authenticate and get JWT |
| POST | `/v1/recovery/jobs` | JWT | Create async recovery job |
| GET | `/v1/recovery/jobs` | JWT | List recovery jobs |
| GET | `/v1/recovery/jobs/{job_id}` | JWT | Get job status and results |
| POST | `/v1/webhooks/{provider}` | HMAC sig | Ingest payment provider webhook |
| POST | `/v1/executions` | JWT | Create production execution |
| POST | `/v1/executions/{id}/authorize` | MERCHANT_ADMIN+ | Authorize execution |
| POST | `/v1/users` | ADMIN | Create user |
| POST | `/v1/tenants` | ADMIN | Create tenant |
| GET | `/v1/tenants` | ADMIN | List tenants |

### Key Request/Response Examples

#### Run a Batch

```bash
curl -X POST http://localhost:8000/recovery/batch \
  -H "Content-Type: application/json" \
  -d '{
    "split": "demo",
    "batch_seed": 0,
    "strategies": ["no_action", "ev_greedy", "rpa_optimizer"]
  }'
```

Response:
```json
{
  "batch_id": "batch_abc123",
  "summary": {
    "status": "completed",
    "n_transactions": 370,
    "strategy_metrics": { ... }
  }
}
```

#### Get Batch Data

```bash
curl http://localhost:8000/recovery/batch/batch_abc123
```

#### List Batches

```bash
curl http://localhost:8000/recovery/batches
```

#### Get Decision Explanation

```bash
curl "http://localhost:8000/recovery/explain/batch_abc123/txn_001?strategy=rpa_optimizer"
```

#### CSV Batch Import

The CSV workflow allows importing transaction data and recovery actions from a file, enabling bulk batch processing without a database.

```bash
curl -X POST http://localhost:8000/recovery/batch/csv \
  -F "file=@recovery_actions.csv" \
  -F "batch_seed=0" \
  -F "strategies=no_action,ev_greedy,rpa_optimizer"
```

The CSV file must follow the `recovery_actions.csv` schema with columns:
- `transaction_id` — unique transaction identifier
- `amount` — transaction amount in INR
- `action_type` — recovery action (retry, payment_link, customer_message, incentive, human_escalation, no_intervention)
- `resource_requirements` — JSON string of resource consumption (e.g., `{"retry": 1, "messaging": 0, "incentive_budget": 0, "human_slots": 0}`)
- `direct_cost` — direct cost of the action in INR

CSV ingestion validates each row, maps to the internal `ActionSpec` model, and persists results to `rpa_runs/{batch_id}/`. Resource consumption is calculated from `action.resource_requirements` and summed in the optimizer backend (`optimizer.py`), not from capacity defaults.

---

## 14. Authentication and RBAC

### How Authentication Works

```
User → POST /v1/auth/token (email + password + tenant_id)
     → Server validates credentials against database
     → Server issues JWT (HS256, signed with RPA_AUTH_SIGNING_KEY)
     → JWT contains: sub (user_id), tid (tenant_id), role, jti (token_id), iss, iat, nbf, exp
     → User includes JWT as Authorization: Bearer <token> on subsequent requests
     → Server validates JWT signature, expiry, revocation status
     → RBAC checks role permissions per endpoint
```

### Roles

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| `ADMIN` | Everything: create tenants, users, view all data, manage resources | — |
| `MERCHANT_ADMIN` | Manage their tenant's users, authorize executions, view data | Create tenants, view other tenants |
| `OPERATOR` | View data, run recovery batches, create jobs | Manage users, authorize executions |
| `VIEWER` | View data only | Modify anything |

### Protected Endpoints

| Endpoint | Minimum Role |
|----------|-------------|
| `POST /v1/recovery/jobs` | Any authenticated user |
| `POST /v1/executions` | Any authenticated user |
| `POST /v1/executions/{id}/authorize` | `MERCHANT_ADMIN` or `ADMIN` |
| `POST /v1/users` | `ADMIN` |
| `POST /v1/tenants` | `ADMIN` |
| `GET /v1/tenants` | `ADMIN` |
| All `/recovery/*` demo endpoints | No auth required (demo mode) |

### Demo Mode Behavior

In demo mode (`RPA_MODE=demo`), all authentication is bypassed. The `get_current_principal` dependency returns a synthetic principal:
```python
Principal(user_id="demo-user", tenant_id="demo-tenant", role="ADMIN", token_id="demo-token")
```

No real login is needed. The `/auth/token` endpoint returns a synthetic token.

### JWT Token Lifetime

Default: 900 seconds (15 minutes). Configurable via `RPA_ACCESS_TOKEN_TTL_SECONDS` (range: 60-86400).

---

## 15. Webhooks

### Provider-Agnostic Design

The webhook system (`rpa/webhook.py`) is designed to work with multiple payment providers. It recognizes headers from:

- **Razorpay:** `x-razorpay-signature`, `x-razorpay-timestamp`, `x-razorpay-event-id`, `x-razorpay-event`
- **Stripe:** `stripe-signature`
- **Generic:** `x-webhook-signature`, `x-webhook-timestamp`, `x-webhook-id`, `x-webhook-event-type`

### HMAC-SHA256 Signature Verification

1. The webhook sender signs the raw request body with a shared secret
2. RPA receives the webhook and recomputes the HMAC
3. If signatures don't match, the webhook is rejected with HTTP 401

### Replay Protection

- Each webhook includes a timestamp
- RPA checks that the timestamp is within `RPA_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` (default: 300 seconds = 5 minutes)
- Too-old or future-dated webhooks are rejected

### Webhook Endpoint

```
POST /v1/webhooks/{provider}
```

Where `{provider}` is the payment provider name (e.g., `razorpay`, `stripe`).

### Example (Safe — Uses Placeholder Values)

```bash
curl -X POST http://localhost:8000/v1/webhooks/razorpay \
  -H "Content-Type: application/json" \
  -H "x-razorpay-signature: <computed-hmac>" \
  -H "x-razorpay-timestamp: $(date +%s)" \
  -d '{
    "event": "payment.failed",
    "payload": { ... }
  }'
```

### Current Limitation

No real Razorpay webhook integration exists. The provider abstraction (`rpa/providers.py`) has `PaymentEventProvider` as an abstract base class, but only `SimulatorProvider` is implemented. The webhook endpoint will reject requests without a valid `RPA_WEBHOOK_SIGNING_SECRET` configured.

---

## 16. ML Model Management

| Aspect | Detail |
|--------|--------|
| **Model type** | Logistic Regression (scikit-learn) |
| **Model identifier** | `rpa-recovery-logreg-full-v1` |
| **Model directory** | `artifacts/models/rpa-recovery-logreg-full-v1/` |
| **Model file format** | `.joblib` (scikit-learn serialized) |
| **Feature groups** | 6 groups: payment, customer, action, temporal, interaction, transaction |
| **Calibration** | Platt scaling (logistic calibration) |
| **Integrity check** | SHA-256 hash of model artifact |
| **Feature schema version** | `v1-{N}groups` (computed from enabled feature flags) |
| **Preprocessing version** | `v1` |
| **Registry** | Database-backed (`model_registry` table) in production |

### Model Loading

The `PredictionService` in `rpa/prediction_service.py` lazily loads the model on first use:
1. Reads `artifacts/models/rpa-recovery-logreg-full-v1/model_metadata.json`
2. Validates SHA-256 hash if available
3. Loads the `.joblib` file via `joblib.load()`
4. Scores each (transaction, action) pair

### What Happens When Model Integrity Fails

If the SHA-256 hash doesn't match, `ModelIntegrityError` is raised. The system will refuse to score predictions with a corrupted model.

### Precomputed Predictions

For faster demo operation, precomputed predictions exist in `artifacts/predictions/`:
- `predictions_demo_rpa-recovery-logreg-full-v1.csv`
- `predictions_test_rpa-recovery-logreg-full-v1.csv`

The system uses these when available instead of running the model live.

---

## 17. Database and Persistence

### Demo Mode Persistence

In demo mode, no database is required. Batch results are stored as JSON files:
```
rpa_runs/
  batch_{id}/
    result.json     # Full batch result (plans, executions, verifications, ev_table, verdicts)
    audit.json      # Audit trail events
```

### Production Database

Production mode requires PostgreSQL with the following tables (defined in `database/migrations/`):

| Migration | Tables Created |
|-----------|---------------|
| V001 | `customers`, `transactions`, `recovery_actions`, `action_outcomes`, `recovery_predictions`, `resource_constraints`, `recovery_decisions`, `audit_logs` |
| V002 | `recovery_runs`, `candidate_actions`, `policy_decisions`, `recovery_plans`, `executions`, `verifications`, `audit_events` |
| V003 | `tenants`, `users`, `revoked_tokens`, `recovery_jobs`, `resource_reservations`, `provider_events`, `production_executions`, `model_registry` |
| V004 | Adds `tenant_id` columns to existing tables + `tenant_resource_limits` |

### Connection Pooling

Production uses `psycopg_pool.ConnectionPool` with configurable min/max connections.

### Migration Runner

```python
from rpa.database import run_migrations
run_migrations()  # Applies all pending V*.sql files
```

### Redis

Redis is defined in `docker-compose.yml` as an optional caching service. It is not currently used by the application code.

---

## 18. Observability and Health

### Health Endpoint

```bash
curl http://localhost:8000/health
```

Returns: `{status, service, step, version, mode, simulation_only}`

In production mode, the health endpoint also checks database connectivity.

### Request IDs

Every request gets a unique ID:
- Client can send `X-Request-ID` header
- Server generates UUID4 if not provided
- Returned in response header `X-Request-ID`
- Included in all error responses
- Logged with every request

### Metrics (Prometheus-Compatible)

The `rpa/observability.py` module provides an in-memory metrics collector that exports in Prometheus text format.

| Metric | Type | Description |
|--------|------|-------------|
| `rpa_operations_total` | counter | Total operations by type and status |
| `rpa_operation_duration_seconds` | histogram | Operation duration |
| `rpa_batches_total` | counter | Total batches by strategy |
| `rpa_batch_n_transactions` | gauge | Transactions per batch |
| `rpa_batch_n_planned` | gauge | Planned actions per batch |
| `rpa_batch_n_executed` | gauge | Executed actions per batch |
| `rpa_batch_n_successful` | gauge | Successful recoveries per batch |
| `rpa_batch_n_failed` | gauge | Failed recoveries per batch |
| `rpa_batch_total_net_ev` | gauge | Total net EV per batch |
| `rpa_predictions_total` | counter | Total predictions |
| `rpa_executions_total` | counter | Total executions by strategy/status |
| `rpa_execution_duration_seconds` | histogram | Execution duration |
| `rpa_policy_decisions_total` | counter | Policy decisions by ALLOW/BLOCK |
| `rpa_webhooks_total` | counter | Webhooks received by provider |

### Structured Logging

Request ID middleware logs every request with: method, path, status code, duration, request ID.

### Troubleshooting Flow

1. Check `/health` endpoint first
2. Look for `X-Request-ID` in the response headers
3. Search logs for that request ID
4. Check the specific endpoint response body for error details
5. Check audit trail if it's a batch-related issue

---

## 19. Docker

### Dockerfile

Multi-stage build:
1. **Builder stage:** Python 3.12-slim, installs dependencies
2. **Runtime stage:** Python 3.12-slim, non-root `rpa` user, copies installed packages and app code

Runs: `uvicorn rpa.api:app --host 0.0.0.0 --port 8000 --workers 4`

Health check: `httpx` GET to `/health` every 30 seconds.

### Docker Compose Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `db` | `postgres:16-alpine` | 5432 | PostgreSQL database |
| `api` | Built from Dockerfile | 8000 | RPA backend API |
| `redis` | `redis:7-alpine` | 6379 | Optional caching |

### Docker Commands

```bash
# Start all services
docker-compose up

# Start in background
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose build api
docker-compose up api

# Run database migrations manually
docker-compose exec api python -c "from rpa.database import run_migrations; run_migrations()"
```

### Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `postgres_data` | PostgreSQL data directory | Persistent database storage |
| `./rpa_runs` | `/app/rpa_runs` | Batch run outputs |
| `./artifacts` | `/app/artifacts` | Model artifacts |
| `./data` | `/app/data` | Demo data |

---

## 20. Testing

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_step3_api.py

# Run with coverage
python -m pytest tests/ --cov=rpa --cov-report=html

# Run a single test
python -m pytest tests/test_step3_api.py::test_health
```

### Test Results

```
188 tests collected — 187 passed, 1 skipped in ~7s
```

### Test Organization

| File | Tests | What It Covers |
|------|-------|---------------|
| `test_step3_api.py` | 18 | All API endpoints, error codes, CORS |
| `test_step3_backend.py` | 52 | EV engine, policy gates, optimizer, strategies, execution, verification, audit, orchestration |
| `test_step2_features.py` | 11 | Feature engineering |
| `test_step2_model.py` | 6 | Model training |
| `test_step2_predictions.py` | 6 | Prediction alignment |
| `test_step2_leakage.py` | 5 | Data leakage checks |
| `test_step1_data_foundation.py` | 19 | Data schema, cleaning, validation, splitting |
| `test_strategies.py` | 14 | All 4 strategies, rule-based logic |
| `test_optimizer.py` | 11 | ILP solver, constraints, greedy |
| `test_actions.py` | 7 | Action specs, loading |
| `test_metrics.py` | 7 | Metric computation |
| `test_expected_value.py` | 6 | EV formula |
| `test_data_generation.py` | 10 | Synthetic data generation |
| `test_model.py` | 5 | Model training |
| `test_outcome_simulator.py` | 5 | Simulation outcomes |
| `test_reproducibility.py` | 4 | Seed reproducibility |
| `test_feature_engineering.py` | 5 | Feature pipeline |
| `test_security.py` | 3 | JWT, passwords, execution state machine |
| `test_step5_qa.py` | 3 | Quality assurance |

### Frontend Tests

There is one Playwright test file (`frontend/tests/example.spec.ts`) which is a boilerplate. A comprehensive Playwright E2E script exists at `scripts/test_playwright_complete.cjs` (629 lines) but it uses a mock API dataset and in-process HTTP server — it is not a live E2E test.

---

## 21. CI/CD

### GitHub Actions Pipeline (`.github/workflows/ci.yml`)

| Job | Trigger | What It Does |
|-----|---------|-------------|
| `lint` | push/PR to main | `ruff check`, `ruff format --check`, `mypy` |
| `test` | After lint passes | `pytest` with coverage, uploads to Codecov |
| `security` | After lint passes | `bandit` (security scan), `safety` (dependency vulnerabilities) |
| `docker` | After test+security pass, main branch only | Builds Docker image, pushes to `ghcr.io` |
| `deploy-staging` | After docker, main branch | Placeholder for staging deployment |
| `deploy-production` | After docker, main branch | Placeholder for production deployment |

### When CI Runs

- On every push to `main` or `develop`
- On every pull request targeting `main`

### What Must Pass

1. All lint checks (ruff + mypy) — ruff configured via `ruff.toml` (ignores `EXE002` for executable files without shebang)
2. All 188 tests (187 passed, 1 skipped)
3. Security scans (bandit + safety)
4. Docker build

---

## 22. Security

### Implemented Security Controls

| Control | Implementation | Location |
|---------|---------------|----------|
| JWT authentication | HS256 JWT with expiry, issuer, revocation | `rpa/security.py`, `rpa/auth.py` |
| Role-based access control | 4 roles: ADMIN, MERCHANT_ADMIN, OPERATOR, VIEWER | `rpa/auth.py` |
| Webhook HMAC-SHA256 | Signature verification with shared secret | `rpa/webhook.py` |
| Replay protection | Timestamp tolerance (default 300s) | `rpa/webhook.py` |
| Production execution guard | `/recovery/execute` returns 400 in production mode | `rpa/api.py` |
| Non-root Docker user | `rpa` user in Dockerfile | `Dockerfile` |
| CORS configuration | Explicit origins, wildcard stripped | `rpa/api.py`, `rpa/settings.py` |
| Input validation | Pydantic models, field validators | `rpa/api_models.py` |
| Request size limits | `RPA_REQUEST_MAX_BYTES` (default 1MB) | `rpa/settings.py` |
| Password hashing | PBKDF2-HMAC-SHA256 (600k iterations) | `rpa/security.py` |
| Policy gates | 7 hard gates prevent invalid actions | `rpa/policy_engine.py` |
| Audit trail | Append-only decision log | `rpa/audit.py` |
| Tenant isolation | tenant_id on all production queries | `rpa/database.py` |
| Idempotency keys | Unique constraint on idempotency_key | `rpa/database.py` |
| Atomic resource reservation | SELECT FOR UPDATE | `rpa/database.py` |

### Required Before Real Production Deployment

| Item | Status | Notes |
|------|--------|-------|
| HTTPS/TLS | Not implemented | Must be added via reverse proxy (nginx, etc.) |
| Secrets management | Not implemented | Must use vault/KMS, not `.env` files |
| Encryption at rest | Not implemented | Database-level encryption needed |
| Rate limiting | Not implemented | Add via middleware or API gateway |
| External identity provider | Not implemented | Current auth is database-only |
| Production payment provider | Not integrated | Provider interfaces exist, no live Razorpay integration |
| Immutable audit storage | Not implemented | Current audit is append-only JSON files |
| Monitoring/alerting | Partially implemented | Metrics exist, no alerting system |
| Backup/recovery | Not implemented | Database backup strategy needed |

---

## 23. Troubleshooting Guide

### Backend Won't Start

**Problem:** `uvicorn rpa.api:app` fails to start.

**Check:**
1. Are you in the project root directory?
2. Is the virtual environment activated?
3. Are all dependencies installed?

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**Verification:** Run `python -c "import rpa.api; print('OK')"` — should print "OK".

### Frontend Won't Start

**Problem:** `npm run dev` fails.

**Check:**
1. Are you in the `frontend/` directory?
2. Are node_modules installed?

```bash
cd frontend
npm install
npm run dev
```

**Verification:** Open `http://localhost:5173` — should show the RPA dashboard.

### Port Already in Use

**Problem:** `Address already in use` error.

**Fix:**
```bash
# Find process using port 8000
lsof -i :8000
# Kill it
kill <PID>

# Or use a different port
uvicorn rpa.api:app --port 8001
```

### PostgreSQL Unavailable

**Problem:** Database connection errors in production mode.

**Check:**
1. Is PostgreSQL running?
2. Is `RPA_DATABASE_URL` correct?
3. Can you connect manually?

```bash
psql $RPA_DATABASE_URL -c "SELECT 1"
```

### Missing Environment Variable

**Problem:** `RuntimeError: production configuration missing: RPA_AUTH_SIGNING_KEY`

**Fix:** Set the required variable in your `.env` file:
```bash
RPA_AUTH_SIGNING_KEY=$(openssl rand -base64 32)
```

### Invalid JWT

**Problem:** HTTP 401 "Invalid bearer token".

**Check:**
1. Is the token expired? (default TTL: 900 seconds)
2. Is `RPA_AUTH_SIGNING_KEY` the same on the server that issued the token?
3. Is the token revoked?

**Fix:** Re-authenticate to get a new token.

### Webhook Signature Rejected

**Problem:** HTTP 401 "Invalid webhook signature".

**Check:**
1. Is `RPA_WEBHOOK_SIGNING_SECRET` configured?
2. Is it the same secret the webhook sender uses?
3. Is the timestamp within tolerance?

### Model Artifact Missing

**Problem:** `ModelNotFoundError: Model directory not found`.

**Check:**
1. Does `artifacts/models/rpa-recovery-logreg-full-v1/` exist?
2. Does it contain a `.joblib` file?

```bash
ls artifacts/models/rpa-recovery-logreg-full-v1/
```

### Tests Fail

**Problem:** Some tests fail after changes.

**Check:**
1. Run `python -m pytest tests/ -x --tb=short` to see the first failure
2. Check if the failure is in a specific module
3. Ensure you haven't modified core pipeline behavior

### Demo Batch Does Not Load

**Problem:** Frontend shows "No Active Recovery Batch".

**Check:**
1. Is the backend running?
2. Can you reach `http://localhost:8000/recovery/batches`?
3. Does the response contain any batches?

```bash
curl http://localhost:8000/recovery/batches
```

---

## 24. Common User Questions

**Q: How do I start the project?**
A: See [Quick Start](#2-quick-start). Backend: `uvicorn rpa.api:app --port 8000`. Frontend: `cd frontend && npm run dev`.

**Q: How do I run only the backend?**
A: `uvicorn rpa.api:app --host 0.0.0.0 --port 8000`

**Q: How do I run only the frontend?**
A: `cd frontend && npm run dev`

**Q: How do I load demo data?**
A: Click "Load Demo Batch" in the Navbar, or use the API: `curl -X POST http://localhost:8000/recovery/batch -H "Content-Type: application/json" -d '{"split": "demo"}'`

**Q: How do I compare strategies?**
A: Go to the "Strategy Comparison" tab in the sidebar, or use: `curl -X POST http://localhost:8000/recovery/compare -H "Content-Type: application/json" -d '{"split": "demo"}'`

**Q: How do I create a recovery plan?**
A: Run a batch via the "Configure Batch" modal or API endpoint. The plan is generated automatically as part of the batch pipeline.

**Q: How do I execute a recovery plan?**
A: In demo mode: go to the "Execution" tab, select a strategy, click "Run Simulation". In production: use `POST /v1/recovery/jobs`.

**Q: Is execution real?**
A: No. In demo mode, execution is Monte-Carlo simulation. In production mode, the `/recovery/execute` endpoint is blocked — you must use `/v1/recovery/jobs`. Even then, no real payment provider is integrated.

**Q: Where can I see the result?**
A: Overview tab (KPIs), Recovery Plan tab (per-transaction details), Execution tab (simulated outcomes).

**Q: Where can I see why an action was selected?**
A: Click "Explain" on any row in the Recovery Plan tab. This opens the 6-stage Decision Explanation modal.

**Q: Where is the audit trail?**
A: "Audit Trail" tab in the sidebar. Also available via `GET /recovery/audit/{batch_id}`.

**Q: How do I configure resources?**
A: Use the "Configure Batch" modal (Settings gear in Navbar) or pass `resource_limits` in the API request.

**Q: How do I change policies?**
A: Modify `PolicyConfig` in `rpa/config.py`. The 7 gates are implemented in `rpa/policy_engine.py`.

**Q: How do I use production mode?**
A: Set `RPA_MODE=production` and configure `RPA_DATABASE_URL`, `RPA_AUTH_SIGNING_KEY`, `RPA_WEBHOOK_SIGNING_SECRET` in `.env`.

**Q: How do I configure webhooks?**
A: Set `RPA_WEBHOOK_SIGNING_SECRET` in `.env` and send webhooks to `POST /v1/webhooks/{provider}`.

**Q: How do I run tests?**
A: `python -m pytest tests/ -x --tb=short`

**Q: How do I use Docker?**
A: `docker-compose up` — starts API + PostgreSQL + Redis.

---

## 25. Developer Navigation Guide

### "Where is everything?"

| Need | File/Directory |
|------|---------------|
| **Configuration** | `rpa/settings.py`, `.env`, `.env.example` |
| **Authentication** | `rpa/auth.py`, `rpa/security.py` |
| **API endpoints (demo)** | `rpa/api.py` |
| **API endpoints (production)** | `rpa/api_v1.py` |
| **API models** | `rpa/api_models.py` |
| **Webhooks** | `rpa/webhook.py` |
| **ML prediction** | `rpa/prediction_service.py`, `ml/` |
| **Expected value** | `rpa/ev_engine.py` |
| **Policy engine** | `rpa/policy_engine.py` |
| **Optimizer (ILP)** | `rpa/optimizer.py` |
| **Strategies** | `rpa/strategies.py` |
| **Execution** | `rpa/execution_simulator.py` (demo), `rpa/execution.py` (production) |
| **Verification** | `rpa/verification.py` |
| **Audit** | `rpa/audit.py` |
| **Orchestrator** | `rpa/orchestrator.py` |
| **Database** | `rpa/database.py` |
| **Observability** | `rpa/observability.py` |
| **Model versioning** | `rpa/ml_versioning.py` |
| **Provider interfaces** | `rpa/providers.py` |
| **Central config** | `rpa/config.py` |
| **Frontend app** | `frontend/src/App.tsx` |
| **Frontend API client** | `frontend/src/services/api.ts` |
| **Frontend types** | `frontend/src/types/api.ts` |
| **Frontend views** | `frontend/src/components/views/` |
| **Frontend modals** | `frontend/src/components/modals/` |
| **Frontend shared components** | `frontend/src/components/common/` |
| **Tests** | `tests/` |
| **Database migrations** | `database/migrations/` |
| **Docker** | `Dockerfile`, `docker-compose.yml` |
| **CI/CD** | `.github/workflows/ci.yml` |
| **Scripts** | `scripts/` |
| **Demo data** | `data/` |
| **Model artifacts** | `artifacts/` |
| **Batch outputs** | `rpa_runs/` |
| **Experiment results** | `results/` |

---

## 26. Production Deployment Checklist

### Implemented in This Repository

- [x] Environment configuration validation (`rpa/settings.py`)
- [x] JWT authentication (`rpa/security.py`, `rpa/auth.py`)
- [x] Role-based access control (4 roles)
- [x] PostgreSQL database layer with connection pooling (`rpa/database.py`)
- [x] Database migrations (V001-V004)
- [x] Webhook HMAC-SHA256 verification (`rpa/webhook.py`)
- [x] Replay protection with timestamp tolerance
- [x] Request ID tracking
- [x] Global exception handling with structured errors
- [x] Production execution guard (blocks `/recovery/execute`)
- [x] Model artifact integrity verification (SHA-256)
- [x] Model registry (database-backed)
- [x] Feature schema versioning
- [x] Prometheus-compatible metrics
- [x] Structured operation tracking
- [x] Health endpoint with database check
- [x] CORS configuration
- [x] Input validation (Pydantic)
- [x] Request size limits
- [x] Password hashing (PBKDF2, 600k iterations)
- [x] Non-root Docker user
- [x] Docker multi-stage build
- [x] Docker Compose with PostgreSQL + Redis
- [x] CI/CD pipeline (lint, test, security, Docker build)
- [x] Audit trail (append-only)
- [x] Tenant isolation (tenant_id on queries)
- [x] Idempotency key support
- [x] Atomic resource reservation (SELECT FOR UPDATE)
- [x] Provider abstraction interfaces

### Required Before Real Production Deployment

- [ ] HTTPS/TLS termination (reverse proxy)
- [ ] Secrets management (vault/KMS, not .env files)
- [ ] Database encryption at rest
- [ ] Rate limiting (middleware or API gateway)
- [ ] External identity provider integration
- [ ] Live payment provider integration (Razorpay)
- [ ] Immutable audit storage
- [ ] Monitoring and alerting (Prometheus + Grafana, PagerDuty, etc.)
- [ ] Database backup and recovery strategy
- [ ] Log aggregation (ELK, Datadog, etc.)
- [ ] Load testing and capacity planning
- [ ] Security penetration testing
- [ ] Compliance review (PCI-DSS if handling payment data)

---

## 27. Demo / Presentation Checklist

### Recommended Presentation Sequence

1. **Overview** — Show the 4 KPI cards, explain the problem
2. **Load Demo Batch** — Click "Load Demo Batch", show the pipeline running
3. **Portfolio KPIs** — Review Revenue at Risk, Expected EV, Net Recovery
4. **Strategy Comparison** — Go to Comparison tab, explain all 4 strategies
5. **Resource Constraints** — Go to Resources tab, explain shared budgets
6. **Recovery Plan** — Go to Plan tab, show per-transaction allocations
7. **Decision Explanation** — Click "Explain" on a transaction, walk through 6 stages
8. **Simulated Execution** — Go to Execution tab, run simulation, show reconciliation
9. **Verification** — Show PASS status for all rows
10. **Audit Trail** — Go to Audit tab, show the event timeline
11. **Experiment Result** — Show `results/experiment_report.md` (NEUTRAL verdict)
12. **Limitations** — Acknowledge synthetic data, simulation-only, no live integration
13. **Future Work** — Discuss provider integration, production readiness

### Key Points to Emphasize

- The optimizer uses exact ILP (not heuristic)
- The system is fail-closed (policy blocks invalid actions)
- Every decision is traceable via audit trail
- The codebase has 188 tests collected — 187 passed, 1 skipped
- Production infrastructure is ready (auth, database, webhooks, Docker)
- Honest about experiment results (NEUTRAL, not a silver bullet)

---

## 28. Known Limitations

| Limitation | Impact | Notes |
|------------|--------|-------|
| Synthetic data | All transaction data is generated, not real payment failures | Results may not transfer to real-world scenarios |
| Simulated execution | No real money moves, no real recovery actions sent | Monte-Carlo simulation only |
| Weak ML model | Logistic regression on synthetic data may not generalize | Model is a placeholder for a real production model |
| No live payment provider integration | Provider interfaces exist but no Razorpay/live integration | `SimulatorProvider` is the only implementation |
| No live webhook processing | Webhook verification exists but no real Razorpay webhooks are processed | End-to-end flow not connected |
| Neutral experiment result | RPA does not demonstrate consistent superiority over greedy | Honest assessment — ILP advantage needs diverse transactions |
| No browser E2E tests | Playwright test file is boilerplate; comprehensive CJS script uses mock data | Frontend testing is manual |
| No HTTPS | Application runs on HTTP only | Must add TLS via reverse proxy |
| No rate limiting | API has no request rate limits | Must add via middleware or API gateway |
| No external auth provider | Authentication is database-only | Must integrate with OAuth/OIDC provider |
| In-memory metrics | Metrics are lost on server restart | Must add persistent metrics backend |
| No log aggregation | Logs go to stdout only | Must add centralized logging |
| No load testing | Performance under load not validated | Must add load testing |

---

## 29. Glossary

| Term | Definition |
|------|-----------|
| **Transaction** | A single failed payment attempt, identified by a transaction ID |
| **Failed payment** | A payment that was attempted but did not complete successfully |
| **Recovery** | The process of getting a customer to complete a failed payment |
| **Recovery action** | A specific intervention applied to a failed payment (retry, send link, offer discount, escalate to human, or do nothing) |
| **Portfolio** | The complete set of failed payments being considered together for recovery |
| **Allocator** | The system that allocates limited resources across the portfolio |
| **Expected Value (EV)** | The estimated net money you expect to recover: `EV = P × amount - cost` |
| **Policy Gate** | A business rule that blocks certain actions (e.g., retry limit, minimum EV threshold) |
| **Constraint** | A limitation on available resources (retry quota, messaging quota, budget, human slots) |
| **ILP / MILP** | Integer Linear Programming / Mixed-Integer Linear Programming — mathematical optimization where some variables must be integers |
| **Optimization** | Finding the best allocation of resources to maximize total expected recovery |
| **Retry** | Attempting to process the failed payment again |
| **Payment Link** | Sending the customer a new link to complete the payment |
| **Incentive** | Offering a discount to encourage the customer to pay |
| **Human Escalation** | Assigning the case to a human agent for manual follow-up |
| **Webhook** | An HTTP callback from a payment provider when something happens (e.g., payment failed) |
| **JWT** | JSON Web Token — a compact, URL-safe token for authentication |
| **RBAC** | Role-Based Access Control — permissions based on user roles |
| **Tenant** | An isolated organizational unit (e.g., a merchant account) |
| **Audit Trail** | A permanent, append-only log of every decision made by the system |
| **Verification** | Checking that planned recovery actions match what was actually executed |
| **Simulation** | Using random sampling to estimate recovery outcomes (Monte-Carlo) |
| **Provider** | A payment processing service (e.g., Razorpay, Stripe) |

---

## 30. Final "5-Minute Understanding"

### If you only remember five things about RPA:

1. **The Problem:** When payments fail, businesses have limited resources (retries, messages, discounts, human time) to recover revenue. RPA decides how to allocate these resources across all failed payments.

2. **The Core Idea:** RPA uses mathematical optimization (ILP) to find the allocation that maximizes expected net recovery — instead of applying the same action to every failed payment.

3. **The Decision Process:** Predict recovery probability → compute expected value → apply business rules (7 policy gates) → optimize resource allocation → execute → verify → audit every decision.

4. **Safety and Explainability:** Every decision is explainable (6-stage decision chain), every action passes through policy gates, and the complete audit trail can be traced. The system is fail-closed — it never forces an invalid action through.

5. **Current Scope:** This is a research prototype with synthetic data and simulated execution. The production infrastructure (auth, database, webhooks, Docker) is built, but no live payment provider is integrated. The experiment shows neutral results — optimization does not always beat simpler heuristics on homogeneous data.

---

*Document generated from repository inspection. All commands, endpoints, and configuration verified against the actual codebase.*
