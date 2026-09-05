"""Metrics calculation and aggregation for the experiment.

Per-strategy-per-batch metrics and cross-batch aggregation (mean/std/median/
min/max, lift, wins/ties/losses, confidence intervals).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import numpy as np

from actions import action_cost
from config import Action, Resource
from data_generation import Transaction
from strategies import StrategyAllocation


@dataclass
class BatchMetrics:
    """Metrics for a single strategy on a single batch."""

    strategy: str
    total_revenue_at_risk: float
    expected_recovered: float
    actual_recovered: float
    recovery_rate: float                 # actual_recovered / total_at_risk
    net_recovered: float                 # actual_recovered - total action cost
    total_action_cost: float
    recovery_lift_percent: float         # vs no-intervention actual
    cost_per_recovered_rupee: float
    incentive_utilization: float         # fraction of budget used
    messaging_utilization: float
    human_utilization: float
    retry_utilization: float
    transaction_counts: Dict[str, int]   # count per action
    n_violations: int


def _action_counts(actions: List[Action]) -> Dict[str, int]:
    counts: Dict[str, int] = {a.value: 0 for a in Action}
    for a in actions:
        counts[a.value] += 1
    return counts


def _capacity_value(capacity: Dict[Resource, float], res: Resource) -> float | None:
    return capacity.get(res)


def compute_batch_metrics(
    transactions: Sequence[Transaction],
    allocation: StrategyAllocation,
    outcomes: np.ndarray,
    no_intervention_actual: float,
) -> BatchMetrics:
    """Compute all metrics for ONE strategy on ONE batch.

    - outcomes: binary actual recovery indicators for this batch.
    - no_intervention_actual: actual recovered revenue under Strategy 1
      (same batch, same outcome realization) to compute lift.
    """
    amounts = np.array([t.amount for t in transactions], dtype=float)
    total_at_risk = float(amounts.sum())
    actual_recovered = float(np.sum(amounts * outcomes))
    recovery_rate = actual_recovered / total_at_risk if total_at_risk > 0 else 0.0
    expected = float(sum(allocation.expected_values))
    total_action_cost = float(sum(action_cost(a) for a in allocation.actions))
    net = actual_recovered - total_action_cost
    incentive_cap = _capacity_value(allocation.capacities, Resource.INCENTIVE_BUDGET)
    messaging_cap = _capacity_value(allocation.capacities, Resource.MESSAGING)
    human_cap = _capacity_value(allocation.capacities, Resource.HUMAN_SLOTS)
    retry_cap = _capacity_value(allocation.capacities, Resource.RETRY)

    def _util(used: float, cap: float | None) -> float:
        return (used / cap) if (cap is not None and cap > 0) else 0.0

    total_cost = sum(action_cost(a) for a in allocation.actions)
    cost_per_recovered = -1.0
    if actual_recovered > 0:
        cost_per_recovered = total_cost / actual_recovered

    n_violations = len(allocation.check_violations())
    return BatchMetrics(
        strategy=allocation.name,
        total_revenue_at_risk=total_at_risk,
        expected_recovered=expected,
        actual_recovered=actual_recovered,
        recovery_rate=recovery_rate,
        net_recovered=net,
        total_action_cost=total_action_cost,
        recovery_lift_percent=((actual_recovered - no_intervention_actual) / no_intervention_actual * 100.0)
        if no_intervention_actual > 0 else 0.0,
        cost_per_recovered_rupee=cost_per_recovered,
        incentive_utilization=_util(allocation.resource_used.get("incentive", 0.0), incentive_cap),
        messaging_utilization=_util(allocation.resource_used.get("messaging", 0.0), messaging_cap),
        human_utilization=_util(allocation.resource_used.get("human", 0.0), human_cap),
        retry_utilization=_util(allocation.resource_used.get("retry", 0.0), retry_cap),
        transaction_counts=_action_counts(allocation.actions),
        n_violations=n_violations,
    )


# ---------------------------------------------------------------------------
# Aggregation across seed batches
# ---------------------------------------------------------------------------
@dataclass
class AggregatedMetrics:
    """Aggregated metrics across a set of batch runs (e.g. 20 seeds)."""

    strategy: str
    n_runs: int
    actual_recovered: Dict[str, float]      # mean/std/median/min/max
    net_recovered: Dict[str, float]
    recovery_rate: Dict[str, float]
    lift_percent: Dict[str, float]
    cost_per_recovered: Dict[str, float]
    utilization: Dict[str, Dict[str, float]]  # resource -> agg


def _agg(values: Sequence[float]) -> Dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def aggregate_metrics(
    batch_metrics: Sequence[BatchMetrics],
) -> AggregatedMetrics:
    """Aggregate BatchMetrics across runs (distribution stats per metric)."""
    if len(batch_metrics) == 0:
        raise ValueError("aggregate_metrics requires at least one BatchMetrics")
    strategy = batch_metrics[0].strategy
    actuals = [b.actual_recovered for b in batch_metrics]
    nets = [b.net_recovered for b in batch_metrics]
    rates = [b.recovery_rate for b in batch_metrics]
    lifts = [b.recovery_lift_percent for b in batch_metrics]
    costs = [b.cost_per_recovered_rupee for b in batch_metrics]

    utilization: Dict[str, Dict[str, float]] = {}
    for res in ("incentive", "messaging", "human", "retry"):
        utilization[res] = _agg([getattr(b, f"{res}_utilization") for b in batch_metrics])

    return AggregatedMetrics(
        strategy=strategy,
        n_runs=len(batch_metrics),
        actual_recovered=_agg(actuals),
        net_recovered=_agg(nets),
        recovery_rate=_agg(rates),
        lift_percent=_agg(lifts),
        cost_per_recovered=_agg(costs),
        utilization=utilization,
    )


def compare_lift(
    rpa_metrics: Sequence[BatchMetrics],
    greedy_metrics: Sequence[BatchMetrics],
) -> Dict[str, object]:
    """RPA vs EV-greedy lift analysis across paired seed runs.

    Lift per seed = (RPA_actual - greedy_actual) / greedy_actual.
    Returns distribution stats, wins/ties/losses count and bootstrap CI.
    """
    rpa = np.array([b.actual_recovered for b in rpa_metrics], dtype=float)
    greedy = np.array([b.actual_recovered for b in greedy_metrics], dtype=float)
    if len(rpa) != len(greedy):
        raise ValueError("RPA and greedy must have same number of runs")

    with np.errstate(divide="ignore", invalid="ignore"):
        lift = np.where(greedy > 0, (rpa - greedy) / greedy * 100.0, 0.0)

    wins = int((lift > 1e-9).sum())
    ties = int((np.abs(lift) <= 1e-9).sum())
    losses = int((lift < -1e-9).sum())

    ci = _bootstrap_ci(lift)

    return {
        "rpa_actual_mean": float(rpa.mean()),
        "greedy_actual_mean": float(greedy.mean()),
        "lift_mean": float(lift.mean()),
        "lift_std": float(lift.std(ddof=1)) if len(lift) > 1 else 0.0,
        "lift_median": float(np.median(lift)),
        "lift_min": float(lift.min()),
        "lift_max": float(lift.max()),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "ci_low": ci[0],
        "ci_high": ci[1],
        "lifts": lift.tolist(),
    }


def _bootstrap_ci(samples: np.ndarray, n_boot: int = 10_000, alpha: float = 0.05) -> Tuple[float, float]:
    """Bootstrap 95% CI of the mean (percentile method)."""
    rng = np.random.default_rng(0)
    n = len(samples)
    if n == 0:
        return (0.0, 0.0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        means[b] = rng.choice(samples, size=n, replace=True).mean()
    low = np.percentile(means, 100 * alpha / 2)
    high = np.percentile(means, 100 * (1 - alpha / 2))
    return float(low), float(high)


def paired_wilcoxon(rpa: Sequence[float], greedy: Sequence[float]) -> Dict[str, float]:
    """One-sided Wilcoxon signed-rank test that RPA > greedy on actual recovery."""
    from scipy.stats import wilcoxon
    r = np.asarray(rpa, dtype=float)
    g = np.asarray(greedy, dtype=float)
    if len(r) != len(g):
        raise ValueError("paired arrays must match")
    diff = r - g
    zeros = np.abs(diff) < 1e-12
    n_pos = int((diff > 1e-12).sum())
    n_neg = int((diff < -1e-12).sum())
    n_disc = n_pos + n_neg
    if n_disc == 0:
        return {"statistic": 0.0, "pvalue": 1.0, "method": "all_ties"}
    if (diff[~zeros] > 0).all() or (diff[~zeros] < 0).all():
        # wilcoxon fails on all-same-sign; report a pseudo p-value via sign test
        from scipy.stats import binomtest
        p = binomtest(n_pos, n_disc, 0.5, alternative="greater").pvalue
        return {"statistic": float(n_pos), "pvalue": float(p), "method": "exact_binomial"}
    try:
        stat, p = wilcoxon(diff, alternative="greater")
        return {"statistic": float(stat), "pvalue": float(p), "method": "wilcoxon"}
    except ValueError:
        return {"statistic": float("nan"), "pvalue": float("nan"), "method": "unavailable"}