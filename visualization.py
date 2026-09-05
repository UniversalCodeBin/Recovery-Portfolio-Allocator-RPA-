"""Visualization helpers for the RPA validation experiment.

Generates matplotlib/seaborn figures and markdown tables into results/.
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from config import PLOTS_DIR, Action
from metrics import BatchMetrics

FONT = {"family": "DejaVu Sans", "size": 9}
plt.rc("font", **FONT)


def ensure_dirs() -> None:
    os.makedirs(PLOTS_DIR, exist_ok=True)


def savefig(fig, name: str) -> str:
    ensure_dirs()
    path = os.path.join(PLOTS_DIR, name)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_actual_recovered_boxplot(
    per_scenario: Dict[str, Dict[str, List[float]]],
) -> str:
    """Boxplot of actual recovered revenue by strategy, per scenario.

    per_scenario[scenario][strategy] = list of actual recovery values per seed.
    """
    rows: List[Dict[str, object]] = []
    for scenario, strat_map in per_scenario.items():
        for strategy, values in strat_map.items():
            for v in values:
                rows.append({"scenario": scenario, "strategy": strategy, "actual_recovered": v})
    df = pd.DataFrame(rows)
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharey=False)
    axes = axes.ravel()
    for k, scenario in enumerate(sorted(per_scenario.keys())):
        ax = axes[k]
        sub = df[df.scenario == scenario]
        sns.boxplot(data=sub, x="strategy", y="actual_recovered", ax=ax)
        ax.set_title(f"Scenario {scenario}")
        ax.tick_params(axis="x", rotation=30)
    axes[5].axis("off")
    fig.suptitle("Actual recovered revenue by strategy (20 seeds)")
    fig.tight_layout()
    return savefig(fig, "actual_recovered_boxplot.png")


def plot_lift_distribution(
    lifts: List[float],
    scenario: str,
) -> str:
    """Histogram + KDE of RPA-vs-greedy lift percent across seeds."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(lifts, bins=min(len(lifts), 12), alpha=0.7, color="steelblue",
            edgecolor="white")
    ax.axvline(0, color="crimson", ls="--", lw=1.2)
    ax.set_xlabel("RPA lift vs greedy (%)")
    ax.set_ylabel("seeds")
    ax.set_title(f"Scenario {scenario}: RPA lift distribution (n={len(lifts)})")
    fig.tight_layout()
    return savefig(fig, f"rpa_lift_{scenario}.png")


def plot_utilization_comparison(
    per_scenario: Dict[str, Dict[str, List[float]]],
) -> str:
    """Horizontal bar of mean resource utilization by strategy and scenario."""
    rows: List[Dict[str, object]] = []
    for scenario, strat_map in per_scenario.items():
        for strategy, values in strat_map.items():
            rows.append({"scenario": scenario, "strategy": strategy, "util": np.mean(values)})
    df = pd.DataFrame(rows)

    resources = ["incentive", "messaging", "human", "retry"]
    scenarios = sorted(per_scenario.keys())
    fig, axes = plt.subplots(1, len(scenarios), figsize=(4 * len(scenarios), 4), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for k, scn in enumerate(scenarios):
        ax = axes[k]
        sub = df[df.scenario == scn]
        sns.barplot(
            data=sub,
            x="strategy",
            y="util",
            ax=ax,
            order=sorted(sub.strategy.unique()),
        )
        ax.set_title(f"Scenario {scn}")
        ax.set_ylim(0, 1.05)
        ax.tick_params(axis="x", rotation=30)
    axes[0].set_ylabel("mean utilization")
    fig.suptitle("Resource utilization comparison")
    fig.tight_layout()
    return savefig(fig, "utilization_comparison.png")


def plot_recovery_rate_by_strategy(
    per_scenario: Dict[str, Dict[str, List[float]]],
) -> str:
    """Boxplot of actual recovery rate by strategy per scenario."""
    rows: List[Dict[str, object]] = []
    for scenario, strat_map in per_scenario.items():
        for strategy, values in strat_map.items():
            for v in values:
                rows.append({"scenario": scenario, "strategy": strategy, "rate": v})
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(12, 5))
    sns.boxplot(data=df, x="scenario", y="rate", hue="strategy", ax=ax)
    ax.set_ylabel("actual recovery rate")
    ax.set_title("Actual recovery rate by strategy and scenario")
    fig.tight_layout()
    return savefig(fig, "recovery_rate_by_strategy.png")


def plot_calibration_curve(
    probs: np.ndarray,
    labels: np.ndarray,
    n_bins: int = 10,
) -> str:
    """Reliability diagram: mean predicted vs observed frequency per bin."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    centers = (bins[:-1] + bins[1:]) / 2
    fraction_pos = np.zeros(n_bins)
    for b in range(n_bins):
        mask = (probs >= bins[b]) & (probs < bins[b + 1])
        if b == n_bins - 1:
            mask = probs >= bins[-1]
        if mask.sum() > 0:
            fraction_pos[b] = float(labels[mask].mean())
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(centers, fraction_pos, "o-", color="steelblue", label="observed")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("mean predicted probability")
    ax.set_ylabel("observed frequency")
    ax.set_title("Calibration curve")
    ax.legend()
    fig.tight_layout()
    return savefig(fig, "calibration_curve.png")


def plot_action_allocation_heatmap(
    per_scenario: Dict[str, Dict[str, List[Dict[str, int]]]],
) -> str:
    """Heatmap of mean transaction count per action by strategy per scenario.

    per_scenario[scenario][strategy] = list of transaction-count dicts per seed.
    """
    action_names = [a.value for a in Action]
    rows: List[Dict[str, object]] = []
    for scenario, strat_map in per_scenario.items():
        for strategy, count_lists in strat_map.items():
            mean_counts: Dict[str, float] = {
                a: 0.0 for a in action_names
            }
            for counts in count_lists:
                for a in action_names:
                    mean_counts[a] += counts.get(a, 0)
            n = len(count_lists)
            for a in action_names:
                rows.append({
                    "scenario": scenario,
                    "strategy": strategy,
                    "action": a,
                    "count": mean_counts[a] / n if n else 0.0,
                })
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index=["strategy", "action"], columns="scenario", values="count")
    fig, ax = plt.subplots(figsize=(4 + len(per_scenario) * 2, 7))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="Blues", ax=ax, linewidths=0.5)
    ax.set_title("Mean transaction count by action, strategy and scenario")
    fig.tight_layout()
    return savefig(fig, "action_allocation_heatmap.png")


def markdown_table_from_rows(rows: List[Dict[str, object]], title: str) -> str:
    """Render a list of dict rows as a Markdown table."""
    if not rows:
        return f"**{title}**\n\n(no data)\n"
    cols = list(rows[0].keys())
    header = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    lines = [header, sep]
    for r in rows:
        cells = [str(r[c]) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return f"**{title}**\n\n" + "\n".join(lines) + "\n"


def markdown_table_from_df(df: pd.DataFrame, title: str) -> str:
    rows = df.to_dict(orient="records")
    return markdown_table_from_rows(rows, title)