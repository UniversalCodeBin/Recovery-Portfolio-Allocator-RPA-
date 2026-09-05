"""Main experiment orchestrator.

Runs the full reproducible validation experiment:
  1. Generate synthetic data (fixed seed), split into train/val/test.
  2. Train + freeze the logistic recovery model; evaluate model quality.
  3. For each scenario (A..E) and each seed (default 20):
       - sample a fresh out-of-sample demo batch
       - compute frozen per-action predictions
       - run all 4 strategies on identical inputs
       - simulate actual outcomes with a shared uniform realization
       - record metrics
  4. Aggregate across seeds, produce comparison tables, plots and report.

Run:
    python experiment.py                      # full experiment
    python experiment.py --seeds 5 --scenarios A B C
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from actions import capacity_dict_from_scenario
from config import (
    DATA_SEED,
    MIN_BINDING_RESOURCES,
    N_DEMO_BATCH,
    N_DEMO_POOL,
    N_EXPERIMENT_SEEDS,
    N_TEST,
    N_TRAIN,
    N_VAL,
    PROB_EPS,
    RESULTS_DIR,
    SCENARIOS,
    Action,
    Resource,
)
from data_generation import (
    SyntheticDataGenerator,
    build_demo_pool,
    logit_recovery_probability,
    sample_batch,
    split_dataset,
)
from model import ActionAwareLogistic, evaluate_model_on_split
from metrics import (
    BatchMetrics,
    aggregate_metrics,
    compare_lift,
    compute_batch_metrics,
    paired_wilcoxon,
)
from outcome_simulator import generate_uniform_draws, simulate_outcomes_from_draws
from strategies import run_all_strategies
from visualization import (
    markdown_table_from_df,
    markdown_table_from_rows,
    plot_action_allocation_heatmap,
    plot_actual_recovered_boxplot,
    plot_calibration_curve,
    plot_lift_distribution,
    plot_recovery_rate_by_strategy,
    plot_utilization_comparison,
)


class Experiment:
    """Orchestrates the whole validation experiment."""

    def __init__(
        self,
        scenarios: Sequence[str],
        n_seeds: int = N_EXPERIMENT_SEEDS,
        seed: int = DATA_SEED,
    ) -> None:
        self.scenarios = list(scenarios)
        self.n_seeds = n_seeds
        self.seed = seed
        self._model: Optional[ActionAwareLogistic] = None
        self.demo_pool: List = []

    # ------------------------------------------------------------------
    # Data + model
    # ------------------------------------------------------------------
    def prepare_data_and_model(self) -> Dict[str, object]:
        """Generate all data, train/freeze model, evaluate model quality."""
        gen = SyntheticDataGenerator(self.seed)
        all_data = gen.generate(N_TRAIN + N_VAL + N_TEST, prefix="dataset")
        train_tx, val_tx, test_tx = split_dataset(
            all_data, N_TRAIN, N_VAL, N_TEST, seed=self.seed
        )
        self.demo_pool = build_demo_pool(self.seed, N_DEMO_POOL)

        model = ActionAwareLogistic()
        model.fit(train_tx, val_tx)
        self._model = model

        train_metrics = evaluate_model_on_split(model, train_tx, "train")
        val_metrics = evaluate_model_on_split(model, val_tx, "val")
        test_metrics = evaluate_model_on_split(model, test_tx, "test")

        return {
            "n_train": len(train_tx),
            "n_val": len(val_tx),
            "n_test": len(test_tx),
            "n_demo_pool": len(self.demo_pool),
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
        }

    # ------------------------------------------------------------------
    # Single seed / scenario run
    # ------------------------------------------------------------------
    def run_seed_scenario(
        self,
        scenario_name: str,
        seed: int,
    ) -> Dict[str, object]:
        """Run one (scenario, seed) experiment; returns per-strategy metrics."""
        if self._model is None or not self._model.frozen:
            raise RuntimeError("prepare_data_and_model() must run first")

        scenario = SCENARIOS[scenario_name]
        capacity = capacity_dict_from_scenario(scenario)
        batch = sample_batch(self.demo_pool, N_DEMO_BATCH, seed)

        probs = self._model.predict_proba(batch)
        allocations = run_all_strategies(batch, probs, capacity)

        # Shared uniform outcome realization across all strategies (fair).
        u = generate_uniform_draws(len(batch), seed)
        outcomes: Dict[str, np.ndarray] = {}
        for name, alloc in allocations.items():
            outcomes[name] = simulate_outcomes_from_draws(batch, alloc.actions, u)

        # Baseline actual recovery (no-intervention) for lift calculation.
        no_op_actual = metrics_from_allocation(
            batch, allocations["no_intervention"], outcomes["no_intervention"], 0.0
        ).actual_recovered

        per_strategy: Dict[str, BatchMetrics] = {}
        for name, alloc in allocations.items():
            per_strategy[name] = compute_batch_metrics(
                batch, alloc, outcomes[name], no_op_actual
            )

        # -- Binding analysis: how tight are the capacity constraints?
        binding = self._assess_binding(batch, probs, capacity)

        return {
            "scenario": scenario_name,
            "seed": seed,
            "batch_size": len(batch),
            "metrics": per_strategy,
            "allocations": allocations,
            "binding": binding,
        }

    def _assess_binding(
        self,
        batch: Sequence,
        probs: Dict[Action, np.ndarray],
        capacity: Dict[Resource, float],
    ) -> Dict[str, float]:
        """Greedy demand (unconstrained action choice) vs capacity.

        Reports the fraction of available capacity consumed when every
        transaction takes its SINGLE best-EV action (a proxy for how tight
        each resource is). A value >= 1.0 indicates the resource binds hard.
        """
        from expected_value import best_action_by_ev
        from actions import action_resource_vector
        from config import SCENARIOS

        ev = best_action_by_ev(
            [t.amount for t in batch],
            probs,
            [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
             Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION],
        )
        acts = [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
                Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION]
        demand = {"retry": 0.0, "messaging": 0.0, "incentive": 0.0, "human": 0.0}
        for i, j in enumerate(ev):
            rv = action_resource_vector(acts[int(j)])
            demand["retry"] += rv.retry
            demand["messaging"] += rv.messaging
            demand["incentive"] += rv.incentive
            demand["human"] += rv.human

        ratios: Dict[str, float] = {}
        for res, cap in capacity.items():
            key = res.value
            capval = float(cap)
            ratios[key] = demand.get(key, 0.0) / capval if capval > 0 else float("inf")
        return ratios

    # ------------------------------------------------------------------
    # Full run
    # ------------------------------------------------------------------
    def run_all(self, verbose: bool = True) -> Dict[str, object]:
        """Run all scenarios x seeds and aggregate results."""
        os.makedirs(RESULTS_DIR, exist_ok=True)
        data_summary = self.prepare_data_and_model()
        if verbose:
            print("Dataset + model ready. Model metrics:")
            for split in ("train", "val", "test"):
                m = data_summary[f"{split}_metrics"]
                print(
                    f"  {split}: n={m.n} roc_auc={m.roc_auc:.3f} "
                    f"brier={m.brier:.4f} p={m.precision:.3f} r={m.recall:.3f} "
                    f"f1={m.f1:.3f} ece={m.ece:.4f}"
                )

        # per_scenario[strategy] = list of BatchMetrics across seeds
        scenario_results: Dict[str, Dict[str, object]] = {}
        binding_table: List[Dict[str, object]] = []
        model_curve_data = self._collect_calibration_data()

        for scenario_name in self.scenarios:
            batch_metrics_by_strategy: Dict[str, List[BatchMetrics]] = {
                "no_intervention": [],
                "fixed_rule": [],
                "ev_greedy": [],
                "rpa": [],
            }
            bindings: List[Dict[str, float]] = []
            for seed in range(self.n_seeds):
                res = self.run_seed_scenario(scenario_name, seed)
                bindings.append(res["binding"])
                for name, bm in res["metrics"].items():
                    batch_metrics_by_strategy[name].append(bm)

            # binding summary (uses actual utilization across strategies)
            binding_rows: List[Dict[str, object]] = []
            resource_names = ["incentive", "messaging", "human", "retry"]
            for key in resource_names:
                seed_binds: List[bool] = []
                per_seed_max_util: List[float] = []
                for seed_idx in range(self.n_seeds):
                    utils = [
                        getattr(batch_metrics_by_strategy[strategy][seed_idx], f"{key}_utilization")
                        for strategy in ("fixed_rule", "ev_greedy", "rpa")
                    ]
                    peak = float(max(utils))
                    per_seed_max_util.append(peak)
                    seed_binds.append(peak >= 0.9)
                frac_bound = float(np.mean(seed_binds))
                binding_rows.append({
                    "scenario": scenario_name,
                    "resource": key,
                    "peak_utilization_mean": f"{np.mean(per_seed_max_util):.2f}",
                    "fraction_of_seeds_binding": f"{frac_bound:.1f}",
                    "binds": "True" if frac_bound >= 0.8 else "False",
                })
            binding_table.extend(binding_rows)

            aggregated: Dict[str, object] = {}
            for name, bms in batch_metrics_by_strategy.items():
                aggregated[name] = aggregate_metrics(bms)

            # RPA vs greedy lift analysis
            lift = compare_lift(
                batch_metrics_by_strategy["rpa"],
                batch_metrics_by_strategy["ev_greedy"],
            )
            lift_dist = plot_lift_distribution(lift["lifts"], scenario_name)
            wilcox = paired_wilcoxon(
                [b.actual_recovered for b in batch_metrics_by_strategy["rpa"]],
                [b.actual_recovered for b in batch_metrics_by_strategy["ev_greedy"]],
            )

            scenario_results[scenario_name] = {
                "aggregated": aggregated,
                "lift": lift,
                "wilcoxon": wilcox,
                "plots": {"lift_distribution": lift_dist},
                "batch_metrics": batch_metrics_by_strategy,
            }
            n_binding = sum(1 for r in binding_rows if r["binds"] == "True")
            if verbose:
                print(
                    f"[scenario {scenario_name}] {n_binding} resource(s) bind "
                    f"(of {len(binding_rows)}) "
                    f"| RPA lift vs greedy: mean={lift['lift_mean']:.2f}% "
                    f"wins={lift['wins']} ties={lift['ties']} losses={lift['losses']}"
                )

        results = {
            "data_summary": data_summary,
            "scenario_results": scenario_results,
            "binding_table": binding_table,
            "model_curve_data": model_curve_data,
        }
        self._render_outputs(results)
        return results

    def _collect_calibration_data(self) -> Dict[str, np.ndarray]:
        """Collect pooled (pred, label) for the calibration plot from test split."""
        if self._model is None:
            return {}
        gen = SyntheticDataGenerator(self.seed)
        all_data = gen.generate(N_TRAIN + N_VAL + N_TEST, prefix="dataset")
        _, _, test_tx = split_dataset(all_data, N_TRAIN, N_VAL, N_TEST, seed=self.seed)
        from model import ACTIONS
        probs_list: List[np.ndarray] = []
        labels_list: List[np.ndarray] = []
        for action in ACTIONS:
            p_true = logit_recovery_probability(test_tx, action)
            rng = np.random.default_rng(0)
            y_true = (rng.random(len(test_tx)) < p_true).astype(int)
            p_pred = self._model.predict_proba(test_tx)[action]
            probs_list.append(np.asarray(p_pred))
            labels_list.append(y_true)
        return {
            "probs": np.concatenate(probs_list),
            "labels": np.concatenate(labels_list),
        }

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------
    def _render_outputs(self, results: Dict[str, object]) -> None:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        from visualization import ensure_dirs
        ensure_dirs()

        report: List[str] = []
        add = report.append
        add("# RPA Validation Experiment Report\n")
        add(f"Data seed = {self.seed}; seeds per scenario = {self.n_seeds}; "
            f"scenarios = {', '.join(self.scenarios)}\n")

        # 1. Model metrics
        ds = results["data_summary"]
        add("## 1. Predictive model (frozen Logistic Regression)\n")
        add(markdown_table_from_rows(
            [
                {
                    "split": s,
                    "n": getattr(ds[f"{s}_metrics"], "n"),
                    "roc_auc": f"{getattr(ds[f'{s}_metrics'], 'roc_auc'):.3f}",
                    "precision": f"{getattr(ds[f'{s}_metrics'], 'precision'):.3f}",
                    "recall": f"{getattr(ds[f'{s}_metrics'], 'recall'):.3f}",
                    "f1": f"{getattr(ds[f'{s}_metrics'], 'f1'):.3f}",
                    "brier": f"{getattr(ds[f'{s}_metrics'], 'brier'):.4f}",
                    "ece": f"{getattr(ds[f'{s}_metrics'], 'ece'):.4f}",
                }
                for s in ("train", "val", "test")
            ],
            "Logistic regression + calibration performance",
        ))

        cal = results["model_curve_data"]
        if cal:
            plot_calibration_curve(cal["probs"], cal["labels"])

        # 2. Binding analysis
        add("## 2. Binding (constraint tightness) check per scenario\n")
        add(markdown_table_from_rows(results["binding_table"],
                                     "Capacity tightness: peak utilization across strategies and seeds"))
        add("`binds = True` when the peak utilization of a resource reaches ~0.9 "
            "(i.e. the capacity actually bites in that scenario).\n")

        # 3. Format per-scenario aggregated comparison tables
        add("## 3. Strategy comparison (aggregated over seeds)\n")
        for scn in self.scenarios:
            sr = results["scenario_results"][scn]
            add(f"\n### Scenario {scn}: {SCENARIOS[scn].description}\n")
            rows: List[Dict[str, object]] = []
            for strategy_name in ("no_intervention", "fixed_rule", "ev_greedy", "rpa"):
                agg = sr["aggregated"][strategy_name]
                rows.append({
                    "strategy": strategy_name,
                    "actual_rec_mean": f"{agg.actual_recovered['mean']:,.0f}",
                    "actual_rec_std": f"{agg.actual_recovered['std']:,.0f}",
                    "net_mean": f"{agg.net_recovered['mean']:,.0f}",
                    "recovery_rate_mean": f"{agg.recovery_rate['mean']:.3f}",
                    "lift_vs_inaction_mean%": f"{agg.lift_percent['mean']:.1f}",
                    "cost_rec_rupee_mean": f"{agg.cost_per_recovered['mean']:.3f}",
                    "incentive_util": f"{agg.utilization['incentive']['mean']:.2f}",
                    "messaging_util": f"{agg.utilization['messaging']['mean']:.2f}",
                    "human_util": f"{agg.utilization['human']['mean']:.2f}",
                })
            add(markdown_table_from_rows(rows, "Aggregated strategy metrics"))

            # RPA vs greedy detail
            lift = sr["lift"]
            wil = sr["wilcoxon"]
            add(markdown_table_from_rows(
                [
                    {
                        "metric": "RPA mean lift (greedy=0%)",
                        "value": f"{lift['lift_mean']:.2f}%",
                    },
                    {"metric": "lift std", "value": f"{lift['lift_std']:.2f}%"},
                    {"metric": "lift median / min / max",
                     "value": f"{lift['lift_median']:.2f} / {lift['lift_min']:.2f} / {lift['lift_max']:.2f}%"},
                    {"metric": "wins / ties / losses",
                     "value": f"{lift['wins']} / {lift['ties']} / {lift['losses']}"},
                    {"metric": "95% CI of mean lift",
                     "value": f"[{lift['ci_low']:.2f}, {lift['ci_high']:.2f}]%"},
                    {"metric": "paired test p-value", "value": f"{wil['pvalue']:.4g} ({wil['method']})"},
                ],
                "RPA vs EV-greedy (actual recovered revenue)",
            ))

        # 4. Save comparison CSV
        table_path = os.path.join(RESULTS_DIR, "strategy_comparison.csv")
        self._write_comparison_csv(results, table_path)
        add(f"\nComparison CSV written to `{table_path}`\n")

        # 5. Visualizations
        self._render_plots(results)

        # 6. Thesis verdict
        add(self._thesis_verdict(results))

        report_path = os.path.join(RESULTS_DIR, "experiment_report.md")
        with open(report_path, "w") as f:
            f.write("\n".join(report))
        print(f"Report written to {report_path}")

    def _write_comparison_csv(self, results: Dict[str, object], path: str) -> None:
        rows: List[Dict[str, object]] = []
        for scn in self.scenarios:
            sr = results["scenario_results"][scn]
            for strategy_name in ("no_intervention", "fixed_rule", "ev_greedy", "rpa"):
                agg = sr["aggregated"][strategy_name]
                rows.append({
                    "scenario": scn,
                    "strategy": strategy_name,
                    "actual_rec_mean": agg.actual_recovered["mean"],
                    "actual_rec_std": agg.actual_recovered["std"],
                    "actual_rec_median": agg.actual_recovered["median"],
                    "actual_rec_min": agg.actual_recovered["min"],
                    "actual_rec_max": agg.actual_recovered["max"],
                    "net_mean": agg.net_recovered["mean"],
                    "recovery_rate_mean": agg.recovery_rate["mean"],
                    "cost_per_recovered_mean": agg.cost_per_recovered["mean"],
                    "lift_vs_inaction_mean": agg.lift_percent["mean"],
                })
        pd.DataFrame(rows).to_csv(path, index=False)

    def _render_plots(self, results: Dict[str, object]) -> None:
        per_scenario_actual: Dict[str, Dict[str, List[float]]] = {}
        per_scenario_rate: Dict[str, Dict[str, List[float]]] = {}
        per_scenario_action_counts: Dict[str, Dict[str, List[Dict[str, int]]]] = {}
        per_scenario_util: Dict[str, Dict[str, List[float]]] = {}
        util_fields = ("incentive_utilization", "messaging_utilization", "human_utilization")

        for scn in self.scenarios:
            bms = results["scenario_results"][scn]["batch_metrics"]
            actual: Dict[str, List[float]] = {}
            rate: Dict[str, List[float]] = {}
            counts: Dict[str, List[Dict[str, int]]] = {}
            util: Dict[str, List[float]] = {}
            for strategy, ms in bms.items():
                actual[strategy] = [m.actual_recovered for m in ms]
                rate[strategy] = [m.recovery_rate for m in ms]
                counts[strategy] = [m.transaction_counts for m in ms]
                util[strategy] = [max(getattr(m, f) for f in util_fields) for m in ms]
            per_scenario_actual[scn] = actual
            per_scenario_rate[scn] = rate
            per_scenario_action_counts[scn] = counts
            per_scenario_util[scn] = util

        plot_actual_recovered_boxplot(per_scenario_actual)
        plot_recovery_rate_by_strategy(per_scenario_rate)
        plot_action_allocation_heatmap(per_scenario_action_counts)
        plot_utilization_comparison(per_scenario_util)

    def _thesis_verdict(self, results: Dict[str, object]) -> str:
        """Compute an explicit thesis-support verdict across scenarios.

        Rules (honest, evidence-based):
          - SUPPORTED:   constrained scenarios show clear positive lift
                         (mean > 0.75%) AND relaxed scenario shows no advantage.
          - WEAKLY SUPPORTED: positive but smaller, or mixed.
          - NEUTRAL/REJECTED: no meaningful advantage anywhere.
        """
        lines: List[str] = ["## 4. Thesis verdict\n"]
        evidence: List[str] = []
        for scn in self.scenarios:
            lift = results["scenario_results"][scn]["lift"]
            evidence.append(
                f"- Scenario {scn}: mean lift {lift['lift_mean']:+.2f}% "
                f"(wins {lift['wins']}, ties {lift['ties']}, "
                f"losses {lift['losses']}; "
                f"95% CI [{lift['ci_low']:+.2f}, {lift['ci_high']:+.2f}%])"
            )
        lines.extend(evidence)

        constrained = [s for s in self.scenarios if s != "E"]
        c_lifts = [
            float(results["scenario_results"][s]["lift"]["lift_mean"]) for s in constrained
        ]
        relaxed = float(
            results["scenario_results"].get("E", {}).get("lift", {}).get("lift_mean", 0.0)
        )
        mean_c = float(np.mean(c_lifts)) if c_lifts else 0.0

        # Evidence summary across constrained scenarios.
        total_wins = sum(
            int(results["scenario_results"][s]["lift"]["wins"]) for s in constrained
        )
        total_losses = sum(
            int(results["scenario_results"][s]["lift"]["losses"]) for s in constrained
        )
        best_p = min(
            float(results["scenario_results"][s]["wilcoxon"]["pvalue"]) for s in constrained
        )

        if (
            mean_c > 0.5
            and best_p < 0.05
            and total_wins >= 2 * max(total_losses, 1)
            and relaxed < mean_c
        ):
            verdict = "RPA thesis is SUPPORTED"
        elif (
            mean_c > 0.5
            and total_wins > total_losses
            and best_p < 0.10
        ):
            verdict = "RPA thesis is WEAKLY SUPPORTED"
        elif mean_c < -0.5:
            verdict = "RPA thesis is REJECTED (greedy dominates)"
        else:
            verdict = "RPA thesis is NEUTRAL (no consistent statistical advantage)"

        lines.append(
            f"\n**Verdict: {verdict}**\n\n"
            f"Constrained-scenario mean lift = {mean_c:+.2f}% "
            f"(wins {total_wins} / ties {sum(int(results['scenario_results'][s]['lift']['ties']) for s in constrained)} "
            f"/ losses {total_losses}); best paired-test p = {best_p:.4f}; "
            f"relaxed-scenario lift = {relaxed:+.2f}% "
            f"(expected ~0 for an honest comparison).\n"
        )
        return "\n".join(lines)


def metrics_from_allocation(batch, alloc, outcomes, no_op_actual) -> BatchMetrics:
    """Helper to compute metrics for one allocation (used for baseline)."""
    return compute_batch_metrics(batch, alloc, outcomes, no_op_actual)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RPA validation experiment")
    p.add_argument("--seeds", type=int, default=N_EXPERIMENT_SEEDS)
    p.add_argument("--scenarios", nargs="+", default=["A", "B", "C", "D", "E"])
    p.add_argument("--seed", type=int, default=DATA_SEED)
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    exp = Experiment(scenarios=args.scenarios, n_seeds=args.seeds, seed=args.seed)
    exp.run_all(verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())