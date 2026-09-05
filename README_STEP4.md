# RPA Step 4 — Frontend Dashboard & API Integration (Recovery Portfolio Allocator)

This document covers **Step 4 only** of the Revenue Recovery Portfolio Allocator (RPA) build for the Razorpay AI Buildathon (Track 03: AI Revenue Recovery). Steps 1–3 (data storage, frozen ML model, backend ILP optimization) are unchanged and fully preserved.

Step 4 delivers a polished, high-information-density React frontend connected to the live FastAPI backend, allowing a judge to understand the complete 8-stage recovery pipeline in ~30 seconds:

```
REVENUE AT RISK → AI PREDICTION → EXPECTED VALUE → POLICY GATE → 
PORTFOLIO OPTIMIZATION → RECOVERY PLAN → SIMULATION → VERIFICATION → AUDIT
```

> **SIMULATION NOTICE**: All recovery execution metrics and outcomes are produced by a seeded Monte-Carlo simulation layer. No real money moves and no actual payments are processed.

---

## 1. Frontend Architecture

### Technology Stack
- **Framework**: React 18.3 (TypeScript)
- **Bundler & Dev Server**: Vite 6.1
- **Styling**: Tailwind CSS 3.4 (with custom Razorpay fintech palette)
- **Icons**: Lucide React
- **HTTP Client**: Centralized typed `fetch` client with timeout, error handling, and AbortController

### Directory Structure
```
frontend/
├── index.html                   # HTML entry point with dark theme and typography
├── package.json                 # Dependencies and scripts
├── postcss.config.js            # PostCSS configuration
├── tailwind.config.js           # Tailwind configuration (custom fintech theme)
├── tsconfig.json                # TypeScript compiler configuration (strict mode)
├── vite.config.ts               # Vite configuration (port 5173, host enabled)
├── .env.example                 # Environment variable template
├── .env                         # Local environment configuration
└── src/
    ├── main.tsx                 # React DOM mount point
    ├── App.tsx                  # Master application controller & state orchestrator
    ├── index.css                # Tailwind directives, fonts, custom scrollbars
    ├── types/
    │   └── api.ts               # Complete TypeScript interfaces matching backend models
    ├── services/
    │   └── api.ts               # Centralized typed API client (zero scattered fetch calls)
    ├── components/
    │   ├── common/
    │   │   ├── Navbar.tsx                # Brand header, health badge, batch switcher, demo CTA
    │   │   ├── Sidebar.tsx               # 6-view navigation & 30-second pipeline summary
    │   │   ├── SimulationDisclaimer.tsx  # Persistent zero-risk Monte-Carlo notice
    │   │   ├── KPICard.tsx               # Metric cards with status badges & accents
    │   │   ├── StatusBadge.tsx           # ALLOW/BLOCK, optimal, verified status badges
    │   │   ├── ActionBadge.tsx           # Smart Retry, Payment Link, Incentive, etc.
    │   │   ├── ResourceMeter.tsx         # Knapsack capacity progress meters with warnings
    │   │   ├── LoadingSpinner.tsx        # Non-blocking loading indicator
    │   │   └── ErrorBanner.tsx           # Dismissible error alerts
    │   ├── views/
    │   │   ├── OverviewView.tsx          # View 1: Revenue at Risk, KPI grid, strategy summary
    │   │   ├── ComparisonView.tsx        # View 2: 4-Strategy fair comparison benchmarks
    │   │   ├── ResourceConstraintsView.tsx # View 3: Knapsack shared capacity & action matrix
    │   │   ├── RecoveryPlanView.tsx      # View 4: Transaction-level allocations with filtering
    │   │   ├── ExecutionView.tsx         # View 5: Simulated execution & verification ledger
    │   │   └── AuditTrailView.tsx        # View 6: Append-only decision trail & JSON export
    │   └── modals/
    │       ├── DecisionExplanationModal.tsx # View 7: 6-stage explainable decision chain
    │       └── ConfigureBatchModal.tsx   # Custom split, seed, & budget tuning modal
```

---

## 2. API Integration & Backend Endpoints

The frontend communicates with the FastAPI backend exclusively through `src/services/api.ts`:

| Method | Endpoint | Frontend Usage | Purpose |
|---|---|---|---|
| `GET` | `/health` | `Navbar.tsx` | Backend connectivity & `simulation_only` flag |
| `GET` | `/versions` | `Navbar.tsx` | Component pipeline versions (model, policy, optimizer, etc.) |
| `GET` | `/recovery/actions` | `App.tsx`, `ConfigureBatchModal.tsx` | Candidate action specs, default caps, and splits |
| `GET` | `/recovery/batches` | `Navbar.tsx`, `App.tsx` | Lists persisted runs from `rpa_runs/` for instant demo |
| `GET` | `/recovery/batch/{id}` | `App.tsx`, All Views | Retrieves complete batch result (EV table, plans, verdicts) |
| `POST` | `/recovery/batch` | `App.tsx`, `ConfigureBatchModal.tsx` | Runs ILP batch on split (demo/val/test/train) |
| `POST` | `/recovery/compare` | `ComparisonView.tsx` | Fair benchmark of all 4 recovery strategies |
| `POST` | `/recovery/execute` | `ExecutionView.tsx` | Seeded Monte-Carlo simulated execution of plans |
| `GET` | `/recovery/audit/{id}` | `AuditTrailView.tsx` | Append-only event history with export capability |
| `GET` | `/recovery/explain/{batch_id}/{txn_id}` | `DecisionExplanationModal.tsx` | 6-stage chain-of-reasoning for chosen action |

### Backend Changes Made (Step 4 Integration Prerequisite)
To support standard browser SPA requirements without modifying core ML or ILP logic:
1. **FastAPI CORSMiddleware**: Added to `rpa/api.py` with configurable `CORS_ORIGINS` (defaults to `http://localhost:5173`, `http://localhost:3000`).
2. **Read-Only Helper Endpoints**:
   - `GET /recovery/batch/{batch_id}`: returns full batch data from existing `load_batch_result`.
   - `GET /recovery/batches`: lists existing persisted runs in `rpa_runs/`.
   - `GET /recovery/actions`: exposes action specs, default caps, and available splits.
   - `GET /recovery/explain/{batch_id}/{transaction_id}`: calls backend `AuditTrail.explain_selection(...)` directly.
3. **Regression Tests**: Added in `tests/test_step3_api.py`. The full test suite passes with 181 passed, 1 skipped.

---

## 3. Quick Start & Execution Commands

### Prerequisites
- Node.js >= 18 (verified on v24.19.0)
- Python 3.11 with existing virtual environment (`.venv`)

### 1. Start the FastAPI Backend
```bash
# From repository root:
.venv/bin/python -m uvicorn rpa.api:app --host 127.0.0.1 --port 8000
```
Verify backend health:
```bash
curl http://127.0.0.1:8000/health
# Output: {"status":"ok","service":"rpa-backend","step":3,"simulation_only":true}
```

### 2. Start the Frontend
```bash
# In a new terminal from repository root:
cd frontend
npm run dev
```
Or to run the optimized production preview build:
```bash
cd frontend
npm run build
npm run preview -- --port 5173 --host 127.0.0.1
```
Open your browser at: **`http://localhost:5173`**

---

## 4. Judging Demo Workflow (~30 Seconds to 2 Minutes)

To experience the complete product flow:

1. **Open Dashboard (`http://localhost:5173`)**:
   - The top bar confirms `API Connected` with a green pulse and displays the current batch ID (automatically loading pre-computed run `batch_c6c09722d5` or recent run).
   - Click **"Load Demo Batch"** if no batch is active.
2. **Examine Command Center (Overview)**:
   - Observe **Revenue at Risk** (₹1,444,224 on 370 failed transactions).
   - Observe **Expected Net EV** (₹60,861 via Exact ILP).
   - Observe **Policy Gate Blocks** (692 action candidates screened out).
   - Observe **Resource Utilization** progress bars.
3. **Compare Strategies (`Strategy Comparison` tab)**:
   - View the fair side-by-side benchmark of:
     - `No Action`: ₹59,896 Net EV (baseline, zero cost)
     - `Rule-Based`: Merchant heuristics
     - `EV-Greedy`: ₹60,861 Net EV (greedy comparator)
     - `RPA Optimizer`: ₹60,861 Net EV (exact ILP solution)
   - Read the scientific honesty note regarding synthetic validation economics.
   - Adjust the **Batch Seed** input and click **"Re-run Comparison"** to see live parallel evaluation.
4. **Inspect Resource Constraints (`Resource Constraints` tab)**:
   - Inspect the 4 organizational knapsack budgets: Smart Retry, Customer Messaging, Incentive Budget, Human Escalation Desk.
   - Review the action consumption matrix.
5. **Inspect RPA Recovery Plan (`RPA Recovery Plan` tab)**:
   - Search for a transaction (e.g. `txn_0000016`).
   - Filter by assigned action (e.g. `Smart Retry`, `Customer Message`, `No Intervention`).
   - Click **"Explain"** on any transaction.
6. **Understand Decision Chain (Decision Modal)**:
   - Follow the 6-stage chain:
     1. Revenue at Risk (Txn Amount)
     2. Frozen Model Calibrated Recovery Probability
     3. Deterministic Expected Value (`Gross - Handling Cost = Net EV`)
     4. Policy Gate Verdict (`ALLOW` or `BLOCK` with triggering rule)
     5. Shared Resource Allocation
     6. Portfolio ILP Decision & Verification Outcome
7. **Simulate Execution (`Execution & Verify` tab)**:
   - Click **"Run Simulation"**.
   - Review realized outcomes: Attempted, Successful, Failed, Blocked, Net Realized ₹.
   - Verify that all 370 rows achieve 100% reconciliation (`VERIFIED`).
8. **Inspect Audit Trail (`Audit Trail` tab)**:
   - Filter by component (`optimizer`, `policy`, `execution`, `verification`).
   - Click on any event to inspect full JSON audit payloads.
   - Click **"Export Audit JSON"** to download the auditable decision record.

---

## 5. Data Honesty & Simulation Disclaimers

1. **Simulation Guarantee**: The dashboard explicitly tags all execution screens with amber alert banners indicating that outcomes are simulated via seeded Monte-Carlo trials. No real payments are processed.
2. **Zero Fabricated Lift**: All metrics are bound to actual API responses. When the RPA optimizer and greedy comparator produce identical allocations under synthetic unit economics, the dashboard presents the exact parity honestly.

---

## 6. Verification Results

- **Backend Pytest**: `181 passed, 1 skipped in 7.07s`
- **Frontend TypeScript Check**: `0 errors`
- **Vite Production Build**: Succeeded (`dist/assets/index-WK4LSkzd.css: 25.99 kB`, `dist/assets/index-D0fVnVs1.js: 245.65 kB`)
- **End-to-End API Connectivity**: Verified against live FastAPI endpoints (`/health`, `/versions`, `/recovery/actions`, `/recovery/batches`, `/recovery/batch/{id}`, `/recovery/explain/{batch_id}/{txn_id}`, `/recovery/compare`, `/recovery/execute`).
