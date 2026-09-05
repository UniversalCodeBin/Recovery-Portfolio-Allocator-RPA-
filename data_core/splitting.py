"""Dataset splitting with leakage prevention (Step 1 foundation only).

Strategy
--------
Splits are **customer-grouped**: every transaction that belongs to a given
customer is placed in exactly one split. This guarantees:

* no customer appears in more than one split  -> no customer-history leakage,
* no transaction_id appears in more than one split,
* the demo pool is fully disjoint from train/val/test (no information from the
  modelling splits can leak into the held-out demo set).

Customer historical metrics (``historical_success_rate``, ``historical_recovery_rate``,
``customer_ltv``, ``customer_tenure_days``) are static, per-customer properties
materialized at generation time -- they are **not** derived from the
transaction set, so they cannot leak across splits. The customer-grouped split
additionally prevents any *future* Step-2 engineer from accidentally building
customer-level aggregates (e.g. per-customer mean amount) out of transactions
that straddle the train/test boundary.

No model is trained and no ML feature is computed here -- this module only
establishes the split mechanism and writes reproducible split artifacts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import SPLIT_FRACTIONS, SPLIT_SEED, SPLITS_DIR, SPLIT_PATH_TEMPLATE
from .io import write_frame


@dataclass
class SplitAssignment:
    """Deterministic assignment of customers to named splits."""

    fractions: Dict[str, float]
    seed: int
    customer_split: Dict[str, str] = field(default_factory=dict)
    split_names: List[str] = field(default_factory=list)

    def split_of(self, customer_id: str) -> str:
        return self.customer_split[customer_id]


def make_assignment(
    customer_ids: List[str],
    fractions: Optional[Dict[str, float]] = None,
    seed: int = SPLIT_SEED,
) -> SplitAssignment:
    """Build a deterministic, disjoint customer->split assignment."""
    fractions = dict(fractions) if fractions else dict(SPLIT_FRACTIONS)
    total = sum(fractions.values())
    fractions = {k: v / total for k, v in fractions.items()}
    split_names = list(fractions.keys())

    customer_ids = sorted(set(customer_ids))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(customer_ids).tolist()

    boundaries: List[float] = []
    cum = 0.0
    for name in split_names:
        cum += fractions[name]
        boundaries.append(cum)

    assignment: Dict[str, str] = {}
    cursor = 0
    n = len(perm)
    for name, boundary in zip(split_names, boundaries):
        is_last = name == split_names[-1]
        stop = n if is_last else int(round(boundary * n))
        stop = max(stop, cursor)
        for cid in perm[cursor:stop]:
            assignment[cid] = name
        cursor = stop
    return SplitAssignment(
        fractions=fractions, seed=int(seed), customer_split=assignment, split_names=split_names
    )


def split_transactions(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    fractions: Optional[Dict[str, float]] = None,
    seed: int = SPLIT_SEED,
) -> Dict[str, pd.DataFrame]:
    """Split transactions into named splits grouped by customer.

    ``transactions`` must have a ``customer_id`` column and ``customers`` must
    have a ``customer_id`` column. The union of all splits equals the input and
    the splits are mutually disjoint (no customer / transaction leakage).
    """
    fractions = dict(fractions) if fractions else dict(SPLIT_FRACTIONS)
    assignment = make_assignment(
        customers["customer_id"].tolist(), fractions=fractions, seed=seed
    )
    split_col = transactions["customer_id"].map(assignment.customer_split)
    out: Dict[str, pd.DataFrame] = {}
    for name in assignment.split_names:
        out[name] = transactions.loc[split_col == name].copy()
    return out


def assert_no_leakage(splits: Dict[str, pd.DataFrame]) -> None:
    """Raise AssertionError if any customer or transaction spans two splits."""
    cust_seen: Dict[str, str] = {}
    txn_seen: Dict[str, str] = {}
    for name, df in splits.items():
        for cid in df["customer_id"].unique().tolist():
            prev = cust_seen.get(cid)
            if prev is not None and prev != name:
                raise AssertionError(f"customer {cid} in two splits: {prev} and {name}")
            cust_seen[cid] = name
        for tid in df["transaction_id"].unique().tolist():
            prev = txn_seen.get(tid)
            if prev is not None and prev != name:
                raise AssertionError(f"transaction {tid} in two splits")
            txn_seen[tid] = name


def save_splits(
    splits: Dict[str, pd.DataFrame],
    out_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """Persist each split as CSV and write a split manifest (reproducibility)."""
    out_dir_path = out_dir or SPLITS_DIR
    out_dir_path.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    for name, df in splits.items():
        if df.empty:
            continue
        p = out_dir_path / SPLIT_PATH_TEMPLATE.format(name=name)
        write_frame(df, p)
        paths[name] = str(p)
    manifest = {
        "seed": SPLIT_SEED,
        "fractions": SPLIT_FRACTIONS,
        "counts": {k: int(len(v)) for k, v in splits.items()},
        "paths": paths,
    }
    (out_dir_path / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    return paths


__all__ = [
    "SplitAssignment",
    "make_assignment",
    "split_transactions",
    "assert_no_leakage",
    "save_splits",
]
