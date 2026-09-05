# RPA Step 2 — Core Features + AI Features + Feature Engineering

This document covers **Step 2 only** of the Revenue Recovery Portfolio
Allocator (RPA) build. Step 1 (data foundation) is unchanged and lives
under `data_core/`, `database/`, `data/`, `scripts/run_step1.py`,
`tests/test_step1_data_foundation.py`. See `README_STEP1.md` for Step 1.

Step 2 implements a defensible, leakage-safe ML prediction layer for
**P(recovered = 1 | transaction, customer, action)** using a single
action-conditioned Logistic Regression, with optional calibration, ablation
across four feature groups, and action-conditioned prediction persistence
into the `recovery_predictions` table from Step 1.

The previous validation experiment (`experiment.py` and friends) and the
prior `model.py` / `feature_engineering.py` modules are **preserved
unchanged** — Step 2 adds a parallel `ml/` package that does not depend on
the hidden ground-truth model or the experiment's optimizer.

## 1. What was built

```
ml/
  __init__.py
  config.py                   # seeds, paths, ablation specs, calibration candidates
  data_io.py                  # Step 1 split/aux loaders + label builder (leakage-safe)
  features/
    __init__.py
    transaction_features.py   # amount / log_amount / retry / overdue / status / amount_over_ltv
    customer_features.py      # static per-customer attributes from Step 1 customers
    temporal_features.py      # day_of_week / hour / weekend / buckets / txn_age_days
    payment_features.py       # payment_method / bank / failure_reason (cat) + is_retry_exhausted / is_long_overdue
    action_features.py        # action_type (cat) + cost / resource flags / is_no_op
    interaction_features.py   # 7 plausible (feature × action) interactions
    pipeline.py               # FeatureSpec + build_step2_feature_frame
  preprocessing.py            # fit-on-train FittedPreprocessor (z-score + one-hot), pickleable
  model.py                    # TrainedLogisticModel (frozen action-conditioned logreg + metadata)
  calibration.py              # {none, sigmoid (Platt), isotonic}; chosen on val by Brier
  evaluation.py               # EvalMetrics: ROC-AUC, AP, P/R/F1@0.5, Brier, ECE, slope/intercept
  prediction.py               # generate_predictions, save CSV, insert into recovery_predictions
  versioning.py               # model identifier parsing + canonical artifact paths
  ablation.py                 # A_basic / B_customer / C_action / D_interactions runner
  pipeline.py                 # end-to-end run_step2 orchestrator

scripts/run_step2.py          # CLI entry point

tests/
  test_step2_features.py      # expected columns, ranges, no-NaN, determinism, flag toggles
  test_step2_leakage.py       # split isolation, preprocessing fit-excludes-test, no future info
  test_step2_model.py         # probabilities in [0,1], every-action scored, calibration, save/reload
  test_step2_predictions.py   # one pred per (txn, action), valid IDs, version recorded, DB cols

artifacts/
  models/<model_id>/          # model.pkl, preprocessor.pkl, calibrator.pkl,
                              # feature_spec.json, feature_names.json,
                              # coefficients.csv, metadata.json
  predictions/                # predictions_{split}_<model_id>.csv

reports/
  step2_report.md             # human-readable run summary
  step2_report.json           # machine-readable
  model_metrics/              # per-split metrics (raw + calibrated)
  feature_ablation/           # ablation_results.csv
```

The `recovery_predictions` table (created in Step 1's `V001__*.sql`
migration) is populated when `scripts/run_step2.py --save-db` is invoked.
Otherwise predictions are written to `artifacts/predictions/*.csv` only.

## 2. Design choices (and the things we deliberately did not do)

### 2.1 A single action-conditioned model

A single Logistic Regression is trained across all candidate actions. The
candidate action enters as a categorical feature (`action_type`) plus
numeric action features (cost, resource flags). This:

* lets the model share signal across actions,
* avoids the data-fragmentation that comes with per-action models,
* keeps the calibration story uniform across actions,
* means **one model identifier** covers all action-conditioned predictions.

The label per row is `recovered ∈ {0,1}`, derived from
`data/validated/action_outcomes.csv` (Step 1's historical attempts):

* `recovered = 1` if there is an outcomes row for `(txn, action)` with
  `recovery_status ∈ {"recovered", "partial"}` and `recovered_amount > 0`;
* `recovered = 0` otherwise (no attempt, or a failed attempt).

`action_outcomes` was produced by Step 1 deterministically ahead of any
modeling and respects the dataset reference date — it is a valid supervision
signal with no temporal leakage (no outcome occurs after the dataset's
reference date).

### 2.2 Calibration

Three candidates are evaluated on the **validation** split only:

* `none`     — raw logistic probabilities
* `sigmoid`  — Platt scaling (1-parameter logistic on the logit of raw probs)
* `isotonic` — isotonic regression on raw probabilities

The candidate with the lowest validation Brier is chosen and frozen. Test
data is never used for calibration selection.

### 2.3 Interaction features

The Step 0 RPA thesis was NEUTRAL. Step 2 does **not** manufacture
interactions to make RPA look better. We define a small, defensible set:

| Interaction | Rationale |
|---|---|
| `retry_count × action_cost` | retry-pricing interaction |
| `days_overdue × action_cost` | overdue-pricing interaction |
| `log_ltv × action_cost` | value-pricing interaction |
| `historical_recovery_rate × action_cost` | historical-yield-pricing interaction |
| `behavior × action_cost` | risk-pricing interaction |
| `failure_insufficient × uses_retry` | retry specifically for insufficient-funds failures |
| `payment_upi × uses_messaging` | messaging reach on UPI |

The ablation report tells us whether they actually improve the validation
Brier — we report that **honestly**, even if they do not.

### 2.4 What is NOT in Step 2

* No optimizer (OR-Tools ILP) — Step 3.
* No EV calculation / decision policy — Step 3.
* No FastAPI, no backend APIs, no frontend — Steps 4.
* No authentication, no deployment.
* No Razorpay API integration.
* No tuning against the test set.

## 3. Reproducibility

```bash
.venv/bin/python scripts/run_step2.py            # generate features + train + predict + artifacts
.venv/bin/python scripts/run_step2.py --save-db  # also write to PostgreSQL (recovery_predictions)
.venv/bin/python -m pytest tests/test_step2_*    # 28 Step 2 tests
.venv/bin/python -m pytest                       # full suite (121 tests)
```

Identical inputs (data, seed, config) → identical feature matrices,
identical predictions, identical metric values. Verified by running the
pipeline twice and comparing metrics + artifact hashes.

## 4. Outputs

After running, the following artifacts are written:

```
artifacts/models/rpa-recovery-logreg-full-v1/
  model.pkl                       # frozen sklearn LogisticRegression
  preprocessor.pkl                # fit-on-train FittedPreprocessor
  calibrator.pkl                  # chosen on val (isotonic / sigmoid / none)
  feature_spec.json               # {numeric, categorical, interaction, enabled_groups}
  feature_names.json              # ordered feature names after preprocessing
  coefficients.csv                # feature, coefficient, abs_coefficient (sorted)
  metadata.json                   # model_identifier, metrics (train/val/test), seed, etc.

artifacts/predictions/
  predictions_test_rpa-recovery-logreg-full-v1.csv
  predictions_demo_rpa-recovery-logreg-full-v1.csv

reports/
  step2_report.md                 # human-readable report
  step2_report.json               # machine-readable
  model_metrics/
    model_metrics.json
    model_metrics.csv
  feature_ablation/
    ablation_results.csv
```

## 5. Known limitations

* Synthetic data only (Step 1's neutral generator).
* Test ROC-AUC is modest (≈ 0.54); this is reported honestly and reflects
  the NEUTRAL finding from Step 0 — the available features carry limited
  discriminative signal beyond the prior. **This is not a Step 2 failure**;
  Step 2 reports it accurately so Step 3 (optimizer) can be evaluated
  against a defensible probability layer.
* Action probabilities for `no_intervention` are heavily imbalanced (no
  attempt row → label 0); calibration handles this via the prior.
* Customer-history features are the *static* per-customer properties from
  Step 1; we do **not** recompute per-customer aggregates over the
  transaction set (that would risk within-customer leakage across splits).
* The DB loader is best-effort: if PostgreSQL is not reachable, predictions
  are still written to disk and a skip message is printed.
