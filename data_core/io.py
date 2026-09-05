"""Filesystem IO helpers for the RPA data foundation (CSV, no extra deps).

CSV is used for on-disk artifacts to match the existing experiment convention
and to avoid pulling in a parquet engine (pyarrow/fastparquet). This module
centralizes write/read so dtypes and JSON columns round-trip consistently:

* datetime columns are parsed back to tz-aware ``datetime64[ns, UTC]``.
* integer columns use ``Int64`` (nullable) so nulls survive the round-trip.
* JSON columns (resource_requirements, metadata, event_metadata) are parsed
  back from JSON strings into Python dicts/lists.

These helpers are intentionally small and dependency-light so Step 2 can adopt
them directly when building its modeling datasets.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

import pandas as pd

# Columns that are dates (UTC) per entity table.
DATETIME_COLUMNS: Dict[str, list[str]] = {
    "customers": ["created_at", "updated_at"],
    "transactions": ["due_date", "transaction_timestamp", "created_at", "updated_at"],
    "recovery_actions": [],
    "action_outcomes": ["attempted_at", "outcome_timestamp"],
    "recovery_predictions": ["prediction_timestamp"],
    "resource_constraints": [],
    "recovery_decisions": ["decision_timestamp"],
    "audit_logs": ["timestamp"],
}

INT_COLUMNS: Dict[str, list[str]] = {
    "customers": ["customer_tenure_days"],
    "transactions": ["retry_count", "days_overdue"],
    "recovery_actions": [],
    "action_outcomes": [],
    "recovery_predictions": [],
    "resource_constraints": [],
    "recovery_decisions": [],
    "audit_logs": [],
}

JSON_COLUMNS: Dict[str, list[str]] = {
    "recovery_actions": ["resource_requirements"],
    "recovery_decisions": ["metadata"],
    "audit_logs": ["event_metadata"],
}


def _json_serialize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Serialize dict/list cells to JSON strings (so CSV round-trips cleanly)."""
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if series.apply(lambda v: isinstance(v, (dict, list))).any():
            out[col] = series.apply(
                lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v
            )
    return out


def write_frame(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = _json_serialize_df(df)
    out.to_csv(path, index=False)
    return path


def _parse_json_cell(v) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return v


def read_frame(path: str | Path, table: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    for col in DATETIME_COLUMNS.get(table, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    for col in INT_COLUMNS.get(table, []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in JSON_COLUMNS.get(table, []):
        if col in df.columns:
            df[col] = df[col].apply(_parse_json_cell)
    return df


def _parse_json_cell(v) -> Any:
    import math

    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return v


def write_dataset(frames: Dict[str, pd.DataFrame], dir_: str | Path) -> Dict[str, str]:
    dir_ = Path(dir_)
    dir_.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    for table, df in frames.items():
        if df.empty:
            continue
        p = dir_ / f"{table}.csv"
        write_frame(df, p)
        paths[table] = str(p)
    return paths


def read_dataset(dir_: str | Path) -> Dict[str, pd.DataFrame]:
    dir_ = Path(dir_)
    frames: Dict[str, pd.DataFrame] = {}
    if not dir_.exists():
        return frames
    for p in sorted(dir_.glob("*.csv")):
        table = p.stem
        if table in DATETIME_COLUMNS:
            frames[table] = read_frame(p, table)
        else:
            frames[table] = pd.read_csv(p)
    return frames
