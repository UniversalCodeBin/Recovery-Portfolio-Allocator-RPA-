# RPA Quick User Guide

> **Revenue Portfolio Allocator** — AI-driven recovery optimization for failed payments

---

## What Is This?

The RPA is a production-grade system that optimally allocates scarce recovery resources (retry quotas, messaging capacity, incentive budgets, human agent slots) across an entire portfolio of failed payment transactions to maximize total recovered revenue.

**Key innovation**: Instead of optimizing transactions independently (heuristic), the ILP solver jointly optimizes the entire portfolio under shared resource constraints — a mathematically proven approach that outperforms greedy baselines when resources are scarce.

---

## 6-Screen Dashboard Walkthrough

### 1. Overview & Metrics
- **Revenue at Risk**: Total failed transaction value
- **Expected Net EV (RPA)**: What the ILP optimizer plans to recover
- **Simulated Net Recovery**: Actual recovery after Monte-Carlo simulation
- **Policy Gate Blocks**: Transactions blocked by business rules
- **Strategy Comparison**: Side-by-side metrics for all 4 strategies
- **Resource Budgets**: Shared capacity utilization (retry, messaging, incentive, human slots)

### 2. Strategy Comparison
- **No Action (Baseline)**: Zero interventions — natural recovery only
- **Rule-Based Heuristic**: Deterministic merchant rules
- **EV-Greedy**: Best EV-per-resource ratio (strong comparator)
- **RPA Optimizer (ILP)**: Exact Mixed-Integer Linear Programming — the recommended approach
- Fair comparison: identical batches, identical ML predictions, identical policy gates

### 3. Resource Constraints
- Shows shared portfolio budgets and how the optimizer allocates them
- **Retry Capacity**: API automated retry quota (2,000 calls)
- **Messaging Capacity**: SMS/WhatsApp/email quota (2,000 messages)
- **Incentive Budget**: Promotional discount pool (₹5,000)
- **Human Escalation**: Support desk capacity (50 slots)
- Action Consumption Matrix shows per-action resource requirements

### 4. RPA Recovery Plan
- Full allocation table: every transaction, chosen action, expected value, cost, net EV
- Filter by action type, search by transaction ID, sort by amount/EV/probability
- Click "Explain" on any row to see the full decision audit trail

### 5. Execution & Reconciliation
- **Simulated Execution Layer**: Seeded Monte-Carlo realization of planned actions
- Run simulation with different seeds for reproducibility
- Reconciliation Ledger: Planned vs Executed action cross-check
- **100% Reconciliation**: Every planned action verified against simulation log
- Fail-closed: unapproved actions are strictly blocked

### 6. Audit Trail
- Append-only decision log for every batch run
- Components: prediction → EV → policy → optimizer → execution → verification
- Filter by component, search by audit ID or event type
- Export full audit as JSON for external review

---

## How to Demo

1. **Load Demo Batch**: Click "Load Verified Demo Batch" on the Overview screen
2. **Run Simulation**: Go to Execution tab → Click "Run Simulation" with seed 0
3. **Compare Strategies**: Go to Comparison tab → Click "Re-run Comparison"
4. **Inspect Decisions**: Go to Recovery Plan → Click "Explain" on any transaction
5. **Review Audit Trail**: Go to Audit tab → Expand any event to see full metadata

---

## Architecture (30-Second Flow)

```
Payment Failure Data
    ↓ ML Model Predictions (frozen Step 2 artifact)
    ↓ Expected Value Engine (deterministic economics)
    ↓ Policy Gates (7 hard constraints → ALLOW/BLOCK)
    ↓ ILP Optimizer (OR-Tools CBC, exact Mixed-Integer LP)
    ↓ Recovery Plan (portfolio allocation)
    ↓ Seeded Monte-Carlo Execution (simulated realization)
    ↓ Reconciliation (planned vs executed verification)
    ↓ Append-Only Audit Trail (full decision transparency)
```

---

## Technical Details

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, FastAPI, OR-Tools (CBC solver) |
| Frontend | React 19, TypeScript, Vite, TailwindCSS |
| Optimizer | Exact Mixed-Integer Linear Programming |
| ML Model | Scikit-learn Logistic Regression (frozen) |
| Database | PostgreSQL (optional; demo uses JSON files) |
| Auth | JWT HS256 + RBAC (ADMIN, MERCHANT_ADMIN, OPERATOR, VIEWER) |
| Tests | 188 collected — 187 passed, 1 skipped (pytest) |
| Container | Multi-stage Docker build, non-root user |

---

## Key Files

| Purpose | Path |
|---------|------|
| Orchestrator | `rpa/orchestrator.py` |
| ILP Optimizer | `rpa/optimizer.py` |
| Policy Engine | `rpa/policy_engine.py` |
| EV Engine | `rpa/ev_engine.py` |
| Execution Simulator | `rpa/execution_simulator.py` |
| Verification Layer | `rpa/verification.py` |
| Audit Trail | `rpa/audit.py` |
| API Endpoints | `rpa/api.py`, `rpa/api_v1.py` |
| Frontend Views | `frontend/src/components/views/` |
| Config | `rpa/config.py`, `rpa/settings.py` |
| Tests | `tests/` (188 collected, 187 passed, 1 skipped) |

---

## Configuration

- **Demo Mode** (default): Uses synthetic data, no database required
- **Production Mode**: Set `RPA_MODE=production` + real PostgreSQL + Razorpay credentials
- **Resource Limits**: Configurable in `rpa/config.py` or via API
- **Policy Gates**: Tunable in `rpa/policy_engine.py`

---

*Built for Razorpay Hackathon 2026 — Production-grade architecture with honest experiment results.*
