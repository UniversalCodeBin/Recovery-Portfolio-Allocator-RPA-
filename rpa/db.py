"""Optional PostgreSQL persistence for Step 3 backend entities.

Follows the same best-effort pattern as Step 2's ``ml.prediction``: if the DB
is unreachable, records still live on disk (JSON run directory) and the DB
insert silently skips. No Step 3 component depends on the DB being present.

Populates the tables created in ``V002__add_rpa_backend.sql``:
recovery_runs, candidate_actions, policy_decisions, recovery_plans,
executions, verifications, audit_events.
"""

from __future__ import annotations

import pandas as pd

from data_core.db import Database


def _try_connect():
    try:
        from data_core.db import connect

        return connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[rpa] DB unavailable, skipping persistence: {exc}")
        return None


def persist_batch_result(result, schema: str = "rpa") -> bool:
    """Write a completed :class:`BatchResult` into the Step 3 tables.

    Returns True if the DB insert ran, False if DB was unavailable.
    """
    conn = _try_connect()
    if conn is None:
        return False
    try:
        db = Database(schema=schema)
        db.load_frame(conn, "recovery_runs", _runs_frame(result), reset_table=False)

        frames = {
            "candidate_actions": _candidates_frame(result),
            "policy_decisions": _policy_frame(result),
            "recovery_plans": _plans_frame(result),
            "executions": _executions_frame(result),
            "verifications": _verifications_frame(result),
            "audit_events": _audit_frame(result),
        }
        for table, df in frames.items():
            if df.empty:
                continue
            db.load_frame(conn, table, df, reset_table=False)
        conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[rpa] DB persist failed: {exc}")
        try:
            conn.close()
        except Exception:  # noqa: BLE001, S110
            pass
        return False


# ---------------------------------------------------------------------------
# Frame builders
# ---------------------------------------------------------------------------
def _runs_frame(result) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": result.batch_id,
                "status": result.status,
                "batch_seed": 0,
                "model_identifier": (
                    result.prediction.model_identifier
                    if result.prediction
                    else "precomputed"
                ),
                "resource_limits": {k: v for k, v in result.resource_limits.items()},
                "strategies": list(result.plans.keys()),
                "simulation": True,
                "created_at": result.created_at,
                "updated_at": result.created_at,
            }
        ]
    )


def _candidates_frame(result) -> pd.DataFrame:
    if result.ev_table is None:
        return pd.DataFrame()
    rows = []
    for r in result.ev_table.rows:
        rows.append(
            {
                "candidate_id": f"cand_{result.batch_id}_{r.transaction_id}_{r.action_id}",
                "run_id": result.batch_id,
                "transaction_id": r.transaction_id,
                "action_id": r.action_id,
                "predicted_recovery_probability": r.p_recovery,
                "recoverable_amount": r.recoverable_amount,
                "gross_expected": r.gross_expected,
                "action_cost": r.action_cost,
                "incentive_cost": r.incentive_cost,
                "total_cost": r.total_cost,
                "net_expected": r.net_expected,
            }
        )
    return pd.DataFrame(rows)


def _policy_frame(result) -> pd.DataFrame:
    rows = []
    for v in result.verdicts:
        rows.append(
            {
                "decision_id": f"dec_{result.batch_id}_{v.transaction_id}_{v.action_id}",
                "run_id": result.batch_id,
                "transaction_id": v.transaction_id,
                "action_id": v.action_id,
                "decision": v.decision,
                "policy_id": v.policy_id,
                "rule": v.rule,
                "reason": v.reason,
                "limit_value": v.limit,
                "current_usage": v.current_usage,
            }
        )
    return pd.DataFrame(rows)


def _plans_frame(result) -> pd.DataFrame:
    rows = []
    for strategy, plan in result.plans.items():
        for rec in plan.to_records():
            rows.append(
                {
                    "plan_id": f"plan_{result.batch_id}_{strategy}_{rec['transaction_id']}",
                    "run_id": result.batch_id,
                    "strategy": strategy,
                    "transaction_id": rec["transaction_id"],
                    "action_id": rec["action_id"],
                    "net_ev": rec["net_ev"],
                    "status": rec["status"],
                }
            )
    return pd.DataFrame(rows)


def _executions_frame(result) -> pd.DataFrame:
    rows = []
    for strategy, ex in result.executions.items():
        for r in ex.executions:
            rows.append(
                {
                    "execution_id": f"ex_{result.batch_id}_{strategy}_{r['transaction_id']}",
                    "run_id": result.batch_id,
                    "strategy": strategy,
                    "transaction_id": r["transaction_id"],
                    "action_id": r.get("action_id"),
                    "status": r["status"],
                    "recovered_amount": r["recovered_amount"],
                    "recovery_cost": r["recovery_cost"],
                    "net_recovered_amount": r["net_recovered_amount"],
                    "p_predicted": r.get("p_predicted"),
                    "simulation": True,
                }
            )
    return pd.DataFrame(rows)


def _verifications_frame(result) -> pd.DataFrame:
    rows = []
    for strategy, verif in result.verifications.items():
        for r in verif.rows:
            rows.append(
                {
                    "verification_id": f"ver_{result.batch_id}_{strategy}_{r['transaction_id']}",
                    "run_id": result.batch_id,
                    "strategy": strategy,
                    "transaction_id": r["transaction_id"],
                    "planned_action_id": r["planned_action_id"],
                    "executed": r["executed"],
                    "executed_status": r["executed_status"],
                    "successful": r["successful"],
                    "failed": r["failed"],
                    "blocked": r["blocked"],
                    "recovered_amount": r["recovered_amount"],
                    "net_recovered_amount": r["net_recovered_amount"],
                    "verified": r["verified"],
                    "verification_error": r.get("verification_error"),
                }
            )
    return pd.DataFrame(rows)


def _audit_frame(result) -> pd.DataFrame:
    rows = []
    for e in result.audit.events:
        rows.append(
            {
                "audit_id": e.audit_id,
                "run_id": e.batch_id,
                "component": e.component,
                "event_type": e.event_type,
                "entity_id": e.entity_id,
                "event_metadata": e.event_metadata,
                "timestamp": e.timestamp,
            }
        )
    return pd.DataFrame(rows)


__all__ = ["persist_batch_result"]
