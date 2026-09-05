# PROJECT QUICK REFERENCE — Revenue Recovery Portfolio Allocator (RPA)

**Repository:** `/run/media/white/New Volume/Projects/2K26/razorpay`
**Extraction Date:** 2026-09-05

---

## ESSENTIAL FACTS

| Field | Value |
|---|---|
| **Project Name** | Revenue Recovery Portfolio Allocator (RPA) |
| **Problem** | Payment recovery for failed transactions under shared resource constraints |
| **User** | Razorpay merchants / operations teams |
| **Innovation** | Exact ILP portfolio optimization of recovery actions under multiple shared resource constraints |
| **Architecture** | Frontend (React) → API (FastAPI) → Orchestrator → [Prediction → EV → Policy → Optimizer → Execution → Verification → Audit] → JSON persistence |
| **Tech Stack** | React 18, TypeScript, Vite, Tailwind, FastAPI, OR-Tools CBC, scikit-learn, NumPy, Pandas, pytest |
| **Database** | PostgreSQL schema (defined, not runtime); JSON files (runtime persistence) |
| **AI/ML** | Action-conditioned Logistic Regression (no LLMs) |
| **Optimizer** | Exact ILP (OR-Tools CBC) + EV-per-resource greedy baseline |
| **Policy Engine** | 7 hard gates: disabled action, blocked list, prohibited combination, retry limit, min EV threshold, per-txn incentive cap, batch resource availability |
| **APIs** | 13 FastAPI endpoints (health, batch, compare, execute, plan, metrics, audit, explain, etc.) |
| **Frontend Screens** | 6 views (Overview, Comparison, Resource Constraints, Recovery Plan, Execution, Audit Trail) + 2 modals (Decision Explanation, Configure Batch) |
| **Actual Metrics** | Constrained-scenario mean lift: +0.15%; Best p-value: 0.0580; Verdict: NEUTRAL |
| **Testing** | 185 backend tests (184 passed, 1 skipped); 0 frontend tests |
| **Limitations** | Synthetic data, simulation only, neutral result, no production integration, no auth |
| **Demo Workflow** | Load demo batch → view KPIs → compare strategies → inspect resources → review plan → explain transaction → execute simulation → verify → audit trail |

---

## WHAT IS IMPLEMENTED

| Component | Status | Notes |
|---|---|---|
| Data foundation (schema, cleaning, validation, splitting) | ✅ Implemented | `data_core/`, `database/`, `data/` |
| Frozen ML model (Logistic Regression + calibration) | ✅ Implemented | `ml/model.py`, `artifacts/models/` |
| Expected value engine | ✅ Implemented | Explicit formula: EV = amount × p − cost |
| Policy engine (7 hard gates) | ✅ Implemented | `rpa/policy_engine.py` |
| Exact ILP optimizer | ✅ Implemented | OR-Tools CBC, `rpa/optimizer.py` |
| Greedy baseline | ✅ Implemented | EV-per-resource greedy |
| 4 strategies (no_action, rule_based, ev_greedy, rpa) | ✅ Implemented | `rpa/strategies.py` |
| Execution simulator | ✅ Implemented | Seeded Monte-Carlo, simulation only |
| Verification layer | ✅ Implemented | Planned vs executed reconciliation |
| Audit trail + explainability | ✅ Implemented | `rpa/audit.py`, `explain_selection()` |
| FastAPI backend (13 endpoints) | ✅ Implemented | `rpa/api.py` |
| React frontend (6 views + 2 modals) | ✅ Implemented | `frontend/src/` |
| Backend tests (185 tests) | ✅ Implemented | 184 passed, 1 skipped |
| Experiment orchestrator (20 seeds × 5 scenarios) | ✅ Implemented | `experiment.py` |
| Honest experimental results | ✅ Implemented | Neutral verdict documented |

---

## WHAT IS SIMULATED

| Component | Status | Notes |
|---|---|---|
| Execution outcomes | 🎲 Simulated | Seeded Monte-Carlo draws from hidden ground-truth model |
| Partial recovery fractions | 🎲 Simulated | Uniform draw in [0, 1] on success |
| Customer responses | 🎲 Simulated | No real customer contact |
| Incentives/messages/retries | 🎲 Simulated | No real actions taken |
| Revenue recovery | 🎲 Simulated | Computed from simulated outcomes |

---

## ACTUAL MEASURED NUMBERS

| Metric | Value | Source |
|---|---|---|
| Constrained-scenario mean lift | +0.15% | `results/experiment_report.md` |
| Best Wilcoxon p-value | 0.0580 | `results/experiment_report.md` |
| Experiment verdict | NEUTRAL | `results/experiment_report.md` |
| Model test ROC-AUC (Step 2) | 0.544 | `reports/model_metrics/model_metrics.json` |
| Model test ROC-AUC (experiment) | 0.776 | `results/experiment_report.md` |
| Total tests | 185 | `pytest.ini`, test files |
| Tests passed | 184 | pytest output |
| Tests skipped | 1 | pytest output |
| Demo batch size | 120 transactions | `config.py` |
| Demo pool size | 150 transactions | `config.py` |
| Train/val/test split | 280/80/100 | `config.py` |
| Experiment seeds per scenario | 20 | `config.py` |
| Scenarios | A, B, C, D, E | `config.py` |
| Shared resources | 4 (retry, messaging, incentive, human) | `config.py` |
| Candidate actions | 6 | `config.py` |

---

## UNPROVEN / DO NOT CLAIM

- ❌ RPA outperforms greedy baselines (result is NEUTRAL)
- ❌ Strong ML predictive performance (test AUC ≤ 0.776 on synthetic data)
- ❌ Real Razorpay integration (no live API calls)
- ❌ Production readiness (synthetic data, simulation only, no auth)
- ❌ Revenue recovery in production (all numbers simulated)
- ❌ Generalizability to real payment data (not tested)

---

## KEY JUDGE TALKING POINTS

1. **Honest science**: The experiment is designed to detect wins, ties, AND losses. The neutral result is valid and demonstrates research integrity.

2. **Complete pipeline**: 8 stages from prediction to audit, all implemented and tested.

3. **Exact optimization**: Not a heuristic — OR-Tools CBC finds the provably optimal solution (or proves infeasibility).

4. **Fair comparison**: All strategies receive identical inputs and share outcome realization. The greedy baseline is strong (ties with RPA in relaxed scenarios).

5. **Production-ready design**: PostgreSQL schema, frozen model artifacts, API, frontend, test coverage — architecture supports real deployment.

6. **Transparency**: Full audit trail, transaction-level explainability, open-source code, reproducible experiment.

---

## REPOSITORY STRUCTURE (ESSENTIAL)

```
razorpay/
├── config.py                    # Master config
├── data_generation.py           # Synthetic data + hidden model
├── feature_engineering.py       # Fit-on-train preprocessing
├── model.py                     # Experiment model
├── actions.py                   # Action economics
├── expected_value.py            # EV calculations
├── optimizer.py                 # ILP + greedy
├── strategies.py                # 4 strategies
├── outcome_simulator.py         # Seeded simulation
├── metrics.py                   # Metrics + significance
├── experiment.py                # Experiment orchestrator
├── data_core/                   # Step 1: data foundation
├── ml/                          # Step 2: ML package
├── rpa/                         # Step 3: backend
│   ├── api.py                   # FastAPI app
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
├── tests/                       # 185 tests
├── artifacts/                   # Model + predictions
├── reports/                     # Generated reports
├── results/                     # Experiment results
└── rpa_runs/                    # Persisted batch runs
```

---

## QUICK START

```bash
# Install
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Run tests
.venv/bin/python -m pytest

# Run full experiment (20 seeds × 5 scenarios)
.venv/bin/python experiment.py

# Run API server
cd frontend && npm run dev  # Terminal 1
.venv/bin/python -m uvicorn rpa.api:app --reload --port 8000  # Terminal 2
```

---

## API ENDPOINTS (ESSENTIAL)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/recovery/batch` | Run full batch |
| POST | `/recovery/compare` | Compare all strategies |
| POST | `/recovery/execute` | Execute simulation |
| GET | `/recovery/plan/{id}` | Get recovery plan |
| GET | `/recovery/audit/{id}` | Get audit trail |
| GET | `/recovery/explain/{id}/{txn}` | Explain decision |

---

## STRATEGIES

| Strategy | Description | Type |
|---|---|---|
| `no_action` | Do nothing | Baseline |
| `rule_based` | Deterministic documented rule | Fixed baseline |
| `ev_greedy` | Best EV/resource per transaction, greedy ordering | Strong baseline |
| `rpa_optimizer` | Exact ILP portfolio optimization | Proposed method |

---

## RESOURCES

| Resource | Description | Unit |
|---|---|---|
| `retry` | Retry attempt capacity | count |
| `messaging` | Message send capacity | count |
| `incentive_budget` | Incentive rupee budget | INR |
| `human_slots` | Human escalation slots | count |

---

## ACTIONS

| Action | Cost (INR) | Retry | Messaging | Incentive | Human |
|---|---|---|---|---|---|
| no_intervention | 0 | 0 | 0 | 0 | 0 |
| retry | 1 | 1 | 0 | 0 | 0 |
| payment_link | 2 | 0 | 1 | 0 | 0 |
| customer_message | 0.5 | 0 | 1 | 0 | 0 |
| incentive | 25 | 0 | 1 | 50 | 0 |
| human_escalation | 40 | 0 | 1 | 0 | 1 |

---

## EXPERIMENT SCENARIOS

| Scenario | Binding Resources | Description |
|---|---|---|
| A | incentive | Single resource constraint |
| B | incentive + human | Two simultaneous binding resources |
| C | incentive + human + messaging | Three simultaneous binding resources |
| D | all four | Tight-resource stress test |
| E | none | Relaxed resources (control) |

---

## MODEL METRICS (FROM ARTIFACTS)

| Split | n | ROC-AUC | Brier | ECE |
|---|---|---|---|---|
| Train (Step 2) | 4200 | 0.621 | 0.0477 | 0.0013 |
| Val (Step 2) | 2124 | 0.611 | 0.0469 | 0.0000 |
| Test (Step 2) | 2190 | 0.544 | 0.0508 | 0.0089 |
| Train (Exp) | 1680 | 0.820 | 0.1463 | 0.0553 |
| Val (Exp) | 480 | 0.848 | 0.1354 | 0.0624 |
| Test (Exp) | 600 | 0.776 | 0.1438 | 0.0418 |

---

## TRUTH CHECK SUMMARY

| Category | Status |
|---|---|
| **IMPLEMENTED** | Complete data foundation, ML model, EV engine, policy gates, ILP optimizer, simulator, verifier, audit trail, API, frontend, 185 tests, experiment |
| **SIMULATED** | All execution outcomes, no real payments/messages/incentives, synthetic data |
| **MEASURED** | Model metrics (AUC 0.544-0.776), experiment results (neutral, +0.15% mean lift, p=0.058) |
| **UNPROVEN** | RPA superiority over greedy, strong predictive performance, production generalizability |
| **REMAINING** | Synthetic data, simulation only, weak ML performance, neutral result, no production integration, no auth |

---

*End of quick reference. For complete details, see `PROJECT_FULL_EXTRACTION.md`.*
