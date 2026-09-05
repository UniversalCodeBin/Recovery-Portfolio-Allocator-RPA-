"""Action-conditioned features.

The Step 2 model is *action-conditioned*: it takes the candidate recovery
action as an input and produces a probability for that action. This module
produces the per-(transaction, action) action features.

For each (txn, action) row we emit:

* ``action_type``        — string label of the action (one-hot downstream).
* ``action_cost``        — rupee cost of applying this action.
* ``action_resource_count`` — number of distinct resources this action
                              consumes (count of non-zero entries in
                              ``resource_requirements``).
* ``uses_retry``         — 1 iff retry is in resource_requirements.
* ``uses_messaging``     — 1 iff messaging is in resource_requirements.
* ``uses_incentive``     — 1 iff incentive_budget is in resource_requirements.
* ``uses_human``         — 1 iff human_slots is in resource_requirements.
* ``is_no_op``           — 1 iff action_type == 'no_intervention'.
"""
from __future__ import annotations

import pandas as pd

from data_core.registry import action_lookup

ACTION_CATEGORICAL_COLUMNS: list[str] = ["action_type"]
ACTION_NUMERIC_FEATURES: list[str] = [
    "action_cost",
    "action_resource_count",
    "uses_retry",
    "uses_messaging",
    "uses_incentive",
    "uses_human",
    "is_no_op",
]

ACTION_OUTPUT_COLUMNS: list[str] = ACTION_CATEGORICAL_COLUMNS + ACTION_NUMERIC_FEATURES


def _expand_resources(res: dict) -> dict:
    out = {
        "uses_retry": 0,
        "uses_messaging": 0,
        "uses_incentive": 0,
        "uses_human": 0,
    }
    if not isinstance(res, dict):
        return out
    for k, v in res.items():
        if float(v) <= 0:
            continue
        if k == "retry":
            out["uses_retry"] = 1
        elif k == "messaging":
            out["uses_messaging"] = 1
        elif k == "incentive_budget":
            out["uses_incentive"] = 1
        elif k == "human_slots":
            out["uses_human"] = 1
    return out


def build_action_features(
    action_ids: list[str],
    recovery_actions: pd.DataFrame,
) -> pd.DataFrame:
    """Build per-action feature rows for the *given* list of action ids.

    Returned in the same order as ``action_ids``.
    """
    if not action_ids:
        return pd.DataFrame(columns=["action_id"] + ACTION_OUTPUT_COLUMNS)
    df = recovery_actions.set_index("action_id").loc[action_ids].reset_index()
    rows = []
    for _, row in df.iterrows():
        flags = _expand_resources(row["resource_requirements"])
        rows.append({
            "action_id": row["action_id"],
            "action_type": str(row["action_type"]),
            "action_cost": float(row["action_cost"]),
            "action_resource_count": int(sum(flags.values())),
            **flags,
            "is_no_op": int(str(row["action_type"]) == "no_intervention"),
        })
    return pd.DataFrame(rows)


__all__ = [
    "ACTION_CATEGORICAL_COLUMNS",
    "ACTION_NUMERIC_FEATURES",
    "ACTION_OUTPUT_COLUMNS",
    "build_action_features",
]
