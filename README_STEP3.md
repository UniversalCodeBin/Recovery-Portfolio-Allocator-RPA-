# RPA Step 3 — Backend Logic + MVP (Recovery Portfolio Allocator)

This document covers **Step 3 only** of the Revenue Recovery Portfolio
Allocator (RPA) build for the Razorpay AI Buildathon. Step 1 (data foundation)
and Step 2 (frozen ML model) are unchanged — see `README_STEP1.md` and
`README_STEP2.md`.

Step 3 turns Step 2's recovery probabilities into **auditable, fair,
portfolio-level allocation decisions** under shared resource budgets, and
exposes a FastAPI MVP backend for Step 4 (frontend).

> **SIMULATION ONLY.** Nothing in this backend can move real money. Every
> execution response carries `"simulation": true`. The execution layer is a
> seeded Monte-Carlo simulator.

---

## 1. Core principle: the LLM/AI never controls money directly

The decision pipeline is a strict, auditable separation of concerns:

```
frozen model (Step 2)  ->  deterministic EV  ->  policy gate (ALLOW/BLOCK)
  ->  optimizer (exact ILP)  ->  simulated execution  ->  verification  ->  audit
```

* The optimizer maximises *deterministic net expected value* — there is no
  free-form LLM output in the money path.
* The **policy engine is a hard gate**. A blocked action can never reach the
  optimizer or the simulator; the simulator also re-checks (fail-closed) and
  records any non-approved action as `blocked`.
* A dedicated no-op action (`act_no_intervention`, zero resource usage) is
  always allowed, so the problem is always feasible.

## 2. What was built

```
rpa/
  __init__.py               # package exports
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
tests/test_step3_backend.py # 42 component/integration tests
tests/test_step3_api.py     # 15 FastAPI endpoint tests

database/migrations/V002__add_rpa_backend.sql   # 7 new tables (appended to rpa_schema.sql)
```

## 3. Fairness contract

All four strategies receive **identical inputs**: the same transaction batch,
the same frozen predictions, the same action set, the same resource limits,
the same EV table, and the same policy verdicts, drawn from the same batch
seed. Strategies differ only in *how* they pick among policy-ALLOWED actions.

| strategy | policy-gated? | selection rule |
|---|---|---|
| `no_action` | yes (no-op always allowed) | no intervention on every txn |
| `rule_based` | yes | documented deterministic business rule |
| `ev_greedy` | yes | best EV-per-resource feasible action per txn |
| `rpa_optimizer` | yes | exact ILP over the whole portfolio (the differentiator) |

Every plan is normalized to a `PortfolioPlan` (per-txn action + EV, total EV,
resource usage) so strategies compare directly.

## 4. Expected-value formula (`ev_engine.py`)

Everything is deterministic and fully expanded per `(txn, action)` — no hidden
economics:

```
recoverable(txn, action) = amount * (1 - recovery_friction)
gross_expected           = P * recoverable
action_cost              = action's rupee handling cost (Step 1 recovery_actions)
incentive_cost           = incentive_budget_units * incentive_handling_fee   (0 if non-incentive)
total_cost               = action_cost + incentive_cost
net_expected             = gross_expected - total_cost
```

Tunables live in `rpa.config.EVEngineConfig` (`recovery_friction`,
`incentive_handling_fee`, probability floor/ceiling).

## 5. Policy gates (`policy_engine.py`)

Each `(txn, action)` gets an `ALLOW`/`BLOCK` verdict with the triggering rule
and relevant limit/usage. Hard gates:

1. `action_disabled` — action flagged disabled in Step 1 data
2. `action_blocked` — action on `PolicyConfig.blocked_actions`
3. `prohibited_combination` — merchant-defined type combos
4. `retry_limit` — `retry_count >= max_retries_per_transaction`
5. `min_net_ev` — any intervention with net EV below the threshold is blocked
   (no-op is never blocked by EV)
6. `max_incentive_per_txn` — incentive budget units over the per-txn cap
7. `resource_exhausted` — insufficient remaining shared capacity

The policy screen does **not** consume resources (it is pure); the cumulative
budget enforcement happens inside the optimizer. Applying a plan always goes
through these gates.

## 6. Optimizer (`optimizer.py`)

Exact Mixed-Integer Linear Program, solved with OR-Tools CBC (`CBC`):

```
maximize   sum_{i,a} x[i,a] * net_ev[i,a]
subject to sum_a x[i,a] == 1                 for every transaction i
           sum_i x[i,a] * R[a,r] <= cap[r]   for every shared resource r
           x[i,a] in {0,1}
```

`R[a,r]` is action `a`'s consumption of resource `r`
(`retry`, `messaging`, `incentive_budget`, `human_slots`).
One action per transaction is always enforced; the no-op guarantees
feasibility. A strong comparator, `ev_per_resource_greedy`, ranks transactions
by best EV-per-resource use and commits each txn's best affordable action.

## 7. Execution, verification, audit

* **Execution** (`execution_simulator.py`): seeded simulation. Only
  policy-approved actions are executed; anything else is recorded as
  `blocked` (fail-closed). On success the recovered amount is
  `recoverable * fraction` (fraction drawn in `[partial_low, partial_high]`).
  Outcome randomness is derived from `(batch_seed, plan.name)` so the same
  seed reproduces the same realization and strategies share draw structure.
* **Verification** (`verification.py`): reconciles every planned action
  against its execution row — executed/successful/failed/blocked, recovered
  amount, cost, net. Any mismatch or missing record fails the batch.
* **Audit** (`audit.py`): records batch, predictions (when live-scored), EV,
  policy, all plans, executions, verifications. `explain_selection(txn_id,
  strategy)` returns a self-consistent narrative: the prediction, EV, and
  policy rows shown correspond to the action actually chosen.

## 8. FastAPI endpoints (`rpa/api.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | service health (simulation_only) |
| GET | `/model/metadata` | frozen model info |
| GET | `/versions` | component versions (model/policy/optimizer/…) |
| POST | `/recovery/batch` | run a recovery batch (subset via `transaction_ids`) |
| POST | `/recovery/preview` | predictions + EV + policy screen for a batch |
| POST | `/recovery/strategy/{name}` | run one strategy |
| POST | `/recovery/compare` | fair comparison of all four strategies |
| POST | `/recovery/execute` | simulated execution of an approved plan |
| GET | `/recovery/plan/{batch_id}` | retrieve a plan |
| GET | `/recovery/metrics/{batch_id}` | batch verifications/metrics |
| GET | `/recovery/audit/{batch_id}` | full decision trail |

Unknown strategies → `400`; unknown batch/split → `404`.

## 9. Persistence

* **JSON (default):** every run is written to `rpa_runs/{batch_id}/`
  (`result.json` + `audit.json`). Persistence failures never stop the pipeline.
* **PostgreSQL (optional, best-effort):** `rpa/db.py` writes the same run into
  7 tables from `V002__add_rpa_backend.sql` (`rpa_batches`,
  `rpa_ev_table`, `rpa_policy_verdicts`, `rpa_plans`,
  `rpa_executions`, `rpa_verifications`, `rpa_audit_events`). The canonical
  schema `database/schema/rpa_schema.sql` has been updated.

## 10. Running it

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

## 11. Results on the demo split (honest picture)

Step 3 integration on the 370-transaction demo split, batch seed 42:

| strategy | total net EV (plan) | outcome (simulated) |
|---|---|---|
| `no_action` | ≈ 59,896 | baseline |
| `ev_greedy` | ≈ 60,861 | retry 9, messaging 28 |
| `rpa_optimizer` | ≈ 60,861 (optimal, verified) | same allocation |

Policy screen blocked 692 candidates (`min_net_ev` 485, `retry_limit` 207).
Because Step 2's recovery probabilities are low (~0.03–0.05) and the
incentive handling fee is `50 × 5 = ₹250`, most incentives and human
escalations are correctly blocked on EV grounds; under this data the greedy
baseline and the ILP agree. **The Step 3 result is NOT "the RPA optimizer is
demonstrably superior"** — it is an honest, verified, portfolio-constrained
allocation that currently ties its strong greedy comparator. The framework is
designed so the optimizer can show portfolio-level gains when action
economics and/or probabilities make scarce resources worth fighting over.

## 12. Limitations & simulation disclaimer

* The execution layer is a **simulation** — recovered amounts are random draws
  under explicit outcome assumptions, never real money.
* All results inherit Step 2 model quality (test ROC-AUC ≈ 0.54 on this
  synthetic data); EV improvements are expectations, not guarantees.
* PostgreSQL persistence is best-effort: without a reachable DB the file-based
  pipeline runs unchanged.
* Audits are large by design (every per-pair EV/policy row is retained) so
  every decision can be explained and re-derived.