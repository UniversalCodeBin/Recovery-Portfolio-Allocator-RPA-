# Revenue Recovery Portfolio Allocator (RPA) — Validation Experiment

Research-grade validation experiment answering:

> Does constrained multi-resource portfolio optimization (RPA) consistently
> outperform a strong per-transaction EV-ratio greedy baseline when multiple
> shared recovery resources bind simultaneously?

This is a **validation experiment, not a product.** It is designed to be
honest: any outcome (RPA wins / ties / loses) is possible.

> **Project roadmap.** This repository is built incrementally. The experiment
> below is the prior validation work. Step 1 — a reusable **data foundation**
> (schema, cleaning, validation, splitting, PostgreSQL loading) — now lives in
> the `data_core/` package and `database/`, `data/`, `scripts/`,
> `tests/test_step1_data_foundation.py`. See
> [README_STEP1.md](README_STEP1.md) for full Step-1 documentation and run it
> with `python scripts/run_step1.py`.

## Install & run (single command)

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
bash run_experiment.sh          # installs, tests, runs full 20-seed experiment
```

or run manually:

```bash
.venv/bin/python -m pytest                      # run the test suite
.venv/bin/python experiment.py                  # full 20-seed x 5-scenario run
.venv/bin/python experiment.py --scenarios C D  # subset
.venv/bin/python experiment.py --seeds 5        # quick smoke run
```

### Outputs (written to `results/`)

- `experiment_report.md` — full report: model metrics, binding analysis,
  per-scenario strategy tables, RPA-vs-greedy lift + significance, verdict.
- `strategy_comparison.csv` — machine-readable aggregated results.
- `plots/*.png` — boxplots, RPA lift distributions, calibration curve,
  utilization bars, action-allocation heatmaps.

## Module layout

| Module | Responsibility |
|---|---|
| `config.py` | All constants: datasets, seeds, actions, costs, resources, scenarios |
| `data_generation.py` | Synthetic data + hidden ground-truth recovery model |
| `feature_engineering.py` | Fit-on-train-only feature transforms (no leakage) |
| `model.py` | Frozen action-conditioned Logistic Regression (+ calibration) |
| `actions.py` | Action economics, resource consumption, capacity state |
| `expected_value.py` | EV = amount·p − cost; EV-ratio scores |
| `optimizer.py` | OR-Tools CBC exact ILP (one action per txn + capacity constraints) |
| `strategies.py` | Four strategies on identical inputs |
| `outcome_simulator.py` | Shared uniform-draw outcome realization (fair seeds) |
| `metrics.py` | Batch metrics + cross-seed aggregation + significance |
| `visualization.py` | Plots & markdown tables |
| `experiment.py` | Orchestrator (single entry point) |
| `tests/` | 72 tests incl. reproducibility, edge cases, ILP vs brute force |

## Fair-comparison guarantees implemented

1. One global train/val/test split; model trained once and frozen; demo pool
   fully held out (no leakage).
2. All four strategies consume the **identical** frozen predictions, action
   set, costs, capacities and transaction batch.
3. `simulate_outcomes_from_draws` draws a single shared U(0,1)^n per batch;
   every strategy evaluates *its own* actions against the *same* realization.
4. Greedy baseline is a strong capacity-rationed EV greedy: in fully relaxed
   scenarios it exactly matches the unconstrained optimum (ties with RPA),
   so any RPA edge is attributable to global multi-resource coupling.
5. Scenario capacities are set from design fractions (not tuned on results)
   and verified at runtime: A binds 1, B binds 2, C binds 3, D binds 4,
   E binds 0 resources (see binding table in the report).# Recovery-Portfolio-Allocator-RPA-
