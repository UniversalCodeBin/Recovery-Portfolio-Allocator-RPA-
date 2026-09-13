"""FastAPI MVP API for the RPA Step 3 backend.

Endpoints:
    GET  /health                          — service health
    GET  /model/metadata                  — frozen model metadata
    POST /recovery/batch                  — create & run a recovery batch
    POST /recovery/preview                — preview candidate actions (EV + policy)
    POST /recovery/strategy/{strategy}    — run one strategy on a batch
    POST /recovery/compare                — run all strategies (fair comparison)
    POST /recovery/execute                — execute a plan (simulation only)
    GET  /recovery/plan/{batch_id}        — retrieve a recovery plan
    GET  /recovery/metrics/{batch_id}     — batch metrics
    GET  /recovery/audit/{batch_id}       — audit/decision details

All execution endpoints return SIMULATION results. Nothing in this API can
move real money.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from math import isfinite
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from rpa.config import (
    DEFAULT_MODEL_IDENTIFIER,
    EV_ENGINE_VERSION,
    OPTIMIZER_VERSION,
    POLICY_VERSION,
    SIMULATOR_VERSION,
    VERIFICATION_VERSION,
    default_resource_limits,
)
from rpa.loading import (
    load_actions,
    load_customers,
    load_transactions,
)
from rpa.orchestrator import (
    RPABatchOrchestrator,
    load_batch_result,
)
from rpa.prediction_service import PredictionService
from rpa.settings import get_settings
from rpa.strategies import STRATEGY_NAMES

logger = logging.getLogger(__name__)

app = FastAPI(
    title="RPA Backend API (Step 3)",
    version="0.3.0",
    description=(
        "Recovery Portfolio Allocator backend. Prediction -> EV -> Policy -> "
        "Optimizer -> Simulated Execution -> Audit. SIMULATION ONLY — never "
        "moves real money."
    ),
)

# Mount production v1 router
from rpa.api_v1 import router as v1_router

app.include_router(v1_router)

# ---------------------------------------------------------------------------
# CORS — read from settings, fall back to safe defaults
# ---------------------------------------------------------------------------
default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
try:
    settings = get_settings()
    allowed_origins = (
        list(settings.cors_origins) if settings.cors_origins else default_origins
    )
except Exception:  # noqa: BLE001
    env_origins = os.getenv("CORS_ORIGINS")
    allowed_origins = (
        [o.strip() for o in env_origins.split(",") if o.strip()]
        if env_origins
        else default_origins
    )
allowed_origins = [origin for origin in allowed_origins if origin != "*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    logger.info(
        "%s %s %d %.1fms rid=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
class APIError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, field: str | None = None
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        super().__init__(message)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "field": exc.field,
            },
            "request_id": request_id,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
            },
            "request_id": request_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("Unhandled exception rid=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred",
            },
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class _ValidatedRequest(BaseModel):
    @field_validator("resource_limits", check_fields=False)
    @classmethod
    def validate_resource_limits(cls, limits):
        if limits is None:
            return limits
        valid = set(default_resource_limits())
        unknown = set(limits) - valid
        if unknown:
            raise ValueError(f"unknown resource limit(s): {sorted(unknown)}")
        for key, value in limits.items():
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(
                    f"resource limit {key} must be a finite non-negative number or null"
                )
        return limits

    @field_validator("transaction_ids", check_fields=False)
    @classmethod
    def validate_transaction_ids(cls, ids):
        if ids is None:
            return ids
        if not ids or any(
            not isinstance(value, str) or not value.strip() for value in ids
        ):
            raise ValueError("transaction_ids must contain non-empty strings")
        if len(ids) != len(set(ids)):
            raise ValueError("transaction_ids must not contain duplicates")
        return ids

    @field_validator("strategies", check_fields=False)
    @classmethod
    def validate_strategies(cls, strategies):
        if strategies is None:
            return strategies
        if not strategies:
            raise ValueError("strategies must not be empty")
        unknown = set(strategies) - set(STRATEGY_NAMES)
        if unknown:
            raise ValueError(f"unknown strategy or strategies: {sorted(unknown)}")
        if len(strategies) != len(set(strategies)):
            raise ValueError("strategies must not contain duplicates")
        return strategies


class BatchRequest(_ValidatedRequest):
    split: str = Field("demo", min_length=1)
    batch_seed: int = Field(0, ge=0, description="Random seed for outcome simulation")
    batch_id: str | None = Field(
        None, description="Batch ID to re-compare from stored source data"
    )
    resource_limits: dict[str, float | None] | None = Field(
        None, description="Shared resource caps; defaults to Step 1 values"
    )
    strategies: list[str] | None = Field(
        None, description="Strategies to run (default all except rule_based)"
    )
    transaction_ids: list[str] | None = Field(None)


class PreviewRequest(_ValidatedRequest):
    split: str = Field("demo", min_length=1)
    transaction_ids: list[str] | None = None


class StrategyRequest(_ValidatedRequest):
    split: str = Field("demo", min_length=1)
    strategy: str = Field(
        "rpa_optimizer", description="no_action|rule_based|ev_greedy|rpa_optimizer"
    )
    batch_seed: int = Field(0, ge=0)
    resource_limits: dict[str, float | None] | None = None


class ExecuteRequest(_ValidatedRequest):
    split: str = Field("demo", min_length=1)
    strategy: str = "rpa_optimizer"
    batch_seed: int = Field(0, ge=0)
    batch_id: str | None = None
    resource_limits: dict[str, float | None] | None = None


# ---------------------------------------------------------------------------
# App state (module-level singletons; tests can override)
# ---------------------------------------------------------------------------
def _load_context(split: str = "demo", transaction_ids: list[str] | None = None):
    transactions = load_transactions(split)
    customers = load_customers()
    actions = load_actions()
    if transaction_ids:
        known_ids = set(transactions["transaction_id"])
        unknown_ids = sorted(set(transaction_ids) - known_ids)
        if unknown_ids:
            raise HTTPException(
                status_code=404,
                detail=f"transaction(s) not found in split {split}: {unknown_ids}",
            )
        transactions = transactions[
            transactions["transaction_id"].isin(transaction_ids)
        ]
    return transactions, customers, actions


def _load_context_from_batch(batch_id: str):
    """Load transactions, customers, and actions from a persisted batch directory.
    Used by /recovery/execute and /recovery/compare to re-run on the same data."""
    from rpa.orchestrator import RUNS_DIR

    batch_dir = RUNS_DIR / batch_id
    txn_path = batch_dir / "transactions.csv"
    cust_path = batch_dir / "customers.csv"

    if not txn_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"batch {batch_id} has no stored source data (pre-CSV batch). Use split-based execution instead.",
        )

    transactions = pd.read_csv(txn_path)
    customers = pd.read_csv(cust_path) if cust_path.exists() else load_customers()
    actions = load_actions()
    return transactions, customers, actions


# ---------------------------------------------------------------------------
# Health & metadata
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "rpa-backend",
        "step": 3,
        "version": "0.3.0",
        "mode": settings.mode,
        "simulation_only": settings.mode == "demo",
    }


@app.get("/model/metadata")
def model_metadata() -> dict:
    service = PredictionService()
    meta = service.metadata
    return {
        "model_identifier": meta["model_identifier"],
        "n_features": meta["n_features"],
        "chosen_calibration": meta["chosen_calibration"],
        "feature_spec": meta["feature_spec"],
        "feature_count": len(meta["feature_names"]),
        "precomputed_predictions_available": _predictions_available(
            meta["model_identifier"]
        ),
    }


def _predictions_available(model_id: str) -> bool:
    from rpa.config import PREDICTIONS_DIR

    return any(PREDICTIONS_DIR.glob(f"predictions_*_{model_id}.csv"))


# ---------------------------------------------------------------------------
# Recovery endpoints
# ---------------------------------------------------------------------------
@app.post("/recovery/batch", response_model=dict)
def run_batch(req: BatchRequest) -> dict:
    try:
        transactions, customers, actions = _load_context(req.split, req.transaction_ids)
        limits = req.resource_limits or default_resource_limits()
        orch = RPABatchOrchestrator()
        result = orch.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=req.batch_seed,
            strategies=req.strategies,
        )
        if result.status == "error":
            raise HTTPException(status_code=500, detail=result.error)
        return {"batch_id": result.batch_id, "summary": result.summary()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"batch failed: {exc}")


@app.post("/recovery/batch/csv")
async def run_batch_from_csv(
    file: UploadFile = File(...),  # noqa: B008  (FastAPI dependency injection)
    batch_seed: int = 0,
    resource_limits: str | None = None,
    strategies: str | None = None,
) -> dict:
    """Create and run a recovery batch from an uploaded Razorpay-style CSV.

    Accepts a CSV file via multipart/form-data upload. The CSV is parsed,
    validated, and transformed into the canonical RPA feature dataset before
    being fed into the existing prediction -> EV -> policy -> optimizer pipeline.

    Parameters:
        file: CSV file (multipart upload)
        batch_seed: Random seed for outcome simulation
        resource_limits: JSON string of resource limits (optional)
        strategies: JSON string of strategy names to run (optional)
    """
    import json as json_mod

    from rpa.csv_adapter import AmountUnit, CSVValidationError, ingest_csv

    # Read and validate file size
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    # Validate content type
    content_type = file.content_type or ""
    if not (
        content_type == "text/csv"
        or content_type.startswith("application/")
        or (file.filename and file.filename.endswith(".csv"))
    ):
        raise HTTPException(
            status_code=422,
            detail=f"expected CSV file, got content-type: {content_type}",
        )

    try:
        result = ingest_csv(content, amount_unit=AmountUnit.RUPEES)
    except CSVValidationError as exc:
        detail: str | dict = str(exc)
        if exc.details:
            detail = {"message": str(exc), "details": exc.details}
        raise HTTPException(status_code=422, detail=detail)

    # Parse optional JSON parameters
    limits = default_resource_limits()
    if resource_limits:
        try:
            parsed_limits = json_mod.loads(resource_limits)
            if isinstance(parsed_limits, dict):
                limits.update(parsed_limits)
        except (json_mod.JSONDecodeError, TypeError):
            raise HTTPException(status_code=422, detail="invalid resource_limits JSON")

    strat_list = None
    if strategies:
        try:
            parsed_strats = json_mod.loads(strategies)
            if isinstance(parsed_strats, list):
                strat_list = parsed_strats
        except (json_mod.JSONDecodeError, TypeError):
            raise HTTPException(status_code=422, detail="invalid strategies JSON")

    try:
        actions = load_actions()
        orch = RPABatchOrchestrator()
        result_batch = orch.run_batch(
            transactions=result.transactions_df,
            actions=actions,
            customers=result.customers_df,
            resource_limits=limits,
            batch_seed=batch_seed,
            strategies=strat_list,
        )
        if result_batch.status == "error":
            raise HTTPException(status_code=500, detail=result_batch.error)
        return {
            "batch_id": result_batch.batch_id,
            "summary": result_batch.summary(),
            "csv_metadata": result.metadata,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"batch from CSV failed: {exc}")


@app.post("/recovery/preview")
def preview(req: PreviewRequest) -> dict:
    """Preview candidate actions (predictions + EV + policy screen) for a batch."""
    try:
        transactions, customers, actions = _load_context(req.split, req.transaction_ids)
        service = PredictionService()
        pred = service.score(transactions, customers, actions)
        from rpa.ev_engine import EVEngine
        from rpa.policy_engine import PolicyEngine

        ev_table = EVEngine().compute(transactions, pred.probabilities, actions)
        res_state = PolicyEngine().initial_resource_state(default_resource_limits())
        verdicts = PolicyEngine().screen(ev_table, transactions, res_state)
        return {
            "model_identifier": pred.model_identifier,
            "n_transactions": pred.n_transactions,
            "n_actions": pred.n_actions,
            "rows": ev_table.to_frame().to_dict(orient="records"),
            "verdicts": [v.to_dict() for v in verdicts],
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"preview failed: {exc}")


@app.post("/recovery/strategy/{strategy_name}")
def run_strategy(strategy_name: str, req: StrategyRequest) -> dict:
    if strategy_name not in STRATEGY_NAMES:
        raise HTTPException(
            status_code=400, detail=f"unknown strategy: {strategy_name}"
        )
    try:
        transactions, customers, actions = _load_context(req.split)
        limits = req.resource_limits or default_resource_limits()
        orch = RPABatchOrchestrator()
        result = orch.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=req.batch_seed,
            strategies=[strategy_name],
        )
        if result.status == "error":
            raise HTTPException(status_code=500, detail=result.error)
        plan = result.plans[strategy_name]
        metrics = result.summary()["strategy_metrics"][strategy_name]
        return {
            "batch_id": result.batch_id,
            "strategy": strategy_name,
            "plan": plan.to_records(),
            "metrics": metrics,
            "execution": result.executions[strategy_name]
            .to_frame()
            .to_dict(orient="records"),
            "verification": result.verifications[strategy_name].batch_metrics,
            "simulation": True,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"strategy failed: {exc}")


@app.post("/recovery/compare")
def compare(req: BatchRequest) -> dict:
    """Run all strategies on identical inputs and return a fair comparison."""
    try:
        if req.batch_id:
            transactions, customers, actions = _load_context_from_batch(req.batch_id)
        else:
            transactions, customers, actions = _load_context(
                req.split, req.transaction_ids
            )
        limits = req.resource_limits or default_resource_limits()
        orch = RPABatchOrchestrator()
        result = orch.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=req.batch_seed,
            strategies=list(STRATEGY_NAMES),
        )
        if result.status == "error":
            raise HTTPException(status_code=500, detail=result.error)
        return {
            "batch_id": result.batch_id,
            "batch_seed": req.batch_seed,
            "simulation": True,
            "strategies": result.summary()["strategy_metrics"],
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"compare failed: {exc}")


@app.post("/recovery/execute")
def execute(req: ExecuteRequest) -> dict:
    """Execute an approved plan under simulation. SIMULATION ONLY."""
    if req.strategy not in STRATEGY_NAMES:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {req.strategy}")
    settings = get_settings()
    if settings.production:
        raise HTTPException(
            status_code=400,
            detail="Real execution is not available through this endpoint. Use /v1/recovery/jobs for production execution.",
        )
    try:
        if req.batch_id:
            transactions, customers, actions = _load_context_from_batch(req.batch_id)
        else:
            transactions, customers, actions = _load_context(req.split)
        limits = req.resource_limits or default_resource_limits()
        orch = RPABatchOrchestrator()
        result = orch.run_batch(
            transactions=transactions,
            actions=actions,
            customers=customers,
            resource_limits=limits,
            batch_seed=req.batch_seed,
            strategies=[req.strategy],
        )
        if result.status == "error":
            raise HTTPException(status_code=500, detail=result.error)
        ex = result.executions[req.strategy]
        return {
            "batch_id": result.batch_id,
            "strategy": req.strategy,
            "simulation": True,
            "batch_metrics": ex.batch_metrics(),
            "executions": ex.executions,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"execute failed: {exc}")


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
@app.get("/recovery/plan/{batch_id}")
def get_plan(batch_id: str) -> dict:
    return _load_ok(batch_id, lambda d: d.get("plans", {}))


@app.get("/recovery/metrics/{batch_id}")
def get_metrics(batch_id: str) -> dict:
    try:
        data = load_batch_result(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "batch_id": batch_id,
        "status": data.get("status"),
        "verifications": data.get("verifications", {}),
    }


@app.get("/recovery/audit/{batch_id}")
def get_audit(batch_id: str) -> Any:
    try:
        from rpa.orchestrator import RUNS_DIR

        p = RUNS_DIR / batch_id / "audit.json"
        if not p.exists():
            raise FileNotFoundError(batch_id)
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"audit not found: {exc}")


def _load_ok(batch_id: str, selector) -> dict:
    try:
        data = load_batch_result(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "batch_id": batch_id,
        "status": data.get("status"),
        **({} if selector is None else {"plans": selector(data)}),
    }


# ---------------------------------------------------------------------------
# Version info endpoint
# ---------------------------------------------------------------------------
@app.get("/versions")
def versions() -> dict:
    return {
        "model": DEFAULT_MODEL_IDENTIFIER,
        "policy": POLICY_VERSION,
        "optimizer": OPTIMIZER_VERSION,
        "ev_engine": EV_ENGINE_VERSION,
        "simulator": SIMULATOR_VERSION,
        "verification": VERIFICATION_VERSION,
    }


# ---------------------------------------------------------------------------
# Frontend helper endpoints (Step 4 integration)
# ---------------------------------------------------------------------------
@app.get("/recovery/batch/{batch_id}")
def get_batch(batch_id: str) -> dict:
    """Retrieve full batch data including plans, executions, verifications, ev_table, verdicts."""
    try:
        data = load_batch_result(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"batch not found: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to load batch: {exc}")
    return data


@app.get("/recovery/batches")
def list_batches() -> list[dict]:
    """List available persisted recovery runs from disk for demo and history."""
    from rpa.orchestrator import RUNS_DIR

    out: list[dict] = []
    if not RUNS_DIR.exists():
        return out
    dirs = [
        p for p in RUNS_DIR.iterdir() if p.is_dir() and (p / "result.json").exists()
    ]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in dirs:
        try:
            data = json.loads((p / "result.json").read_text(encoding="utf-8"))
            batch_id = data.get("batch_id", p.name)
            verifs = data.get("verifications") or {}
            strat_summaries = {}
            for s_name, s_v in verifs.items():
                bm = s_v.get("batch_metrics", {})
                strat_summaries[s_name] = {
                    "planned_total_net_ev": bm.get("planned_total_net_ev", 0.0),
                    "recovered_total": bm.get("recovered_total", 0.0),
                    "net_recovered_total": bm.get("net_recovered_total", 0.0),
                    "cost_total": bm.get("cost_total", 0.0),
                    "n_successful": bm.get("n_successful", 0),
                    "n_failed": bm.get("n_failed", 0),
                    "n_blocked": bm.get("n_blocked", 0),
                    "all_verified": bm.get("all_verified", False),
                }
            txns = data.get("transaction_ids", [])
            out.append(
                {
                    "batch_id": batch_id,
                    "status": data.get("status", "completed"),
                    "created_at": data.get("created_at"),
                    "n_transactions": len(txns),
                    "strategies": list(data.get("plans", {}).keys()),
                    "strategy_summaries": strat_summaries,
                    "has_audit": (p / "audit.json").exists(),
                }
            )
        except Exception:  # noqa: BLE001, S112
            continue
    return out


@app.delete("/recovery/batch/{batch_id}")
def delete_batch(batch_id: str) -> dict:
    """Delete a persisted recovery batch from disk."""
    import shutil

    from rpa.orchestrator import RUNS_DIR

    batch_dir = RUNS_DIR / batch_id
    if not batch_dir.exists() or not batch_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"batch not found: {batch_id}")
    shutil.rmtree(batch_dir)
    return {"deleted": batch_id}


@app.get("/recovery/actions")
def get_actions() -> dict:
    """Return available candidate actions, default resource limits, and splits."""
    actions = load_actions()
    return {
        "actions": [
            {
                "action_id": a.action_id,
                "action_type": a.action_type,
                "action_cost": a.action_cost,
                "resource_requirements": a.resource_requirements,
                "enabled": a.enabled,
            }
            for a in actions
        ],
        "default_resource_limits": default_resource_limits(),
        "available_splits": ["demo", "val", "test", "train"],
    }


@app.get("/recovery/explain/{batch_id}/{transaction_id}")
def get_explanation(
    batch_id: str,
    transaction_id: str,
    strategy: str = "rpa_optimizer",
) -> dict:
    """Return step-by-step decision explanation for a transaction from batch audit."""
    if strategy not in STRATEGY_NAMES:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {strategy}")
    from rpa.audit import AuditEvent, AuditTrail
    from rpa.orchestrator import RUNS_DIR

    audit_file = RUNS_DIR / batch_id / "audit.json"
    if not audit_file.exists():
        raise HTTPException(
            status_code=404, detail=f"audit not found for batch {batch_id}"
        )
    try:
        raw_events = json.loads(audit_file.read_text(encoding="utf-8"))
        trail = AuditTrail(batch_id)
        for e in raw_events:
            trail.events.append(
                AuditEvent(
                    audit_id=e["audit_id"],
                    batch_id=e["batch_id"],
                    component=e["component"],
                    event_type=e["event_type"],
                    entity_id=e.get("entity_id", ""),
                    event_metadata=e.get("event_metadata", {}),
                    timestamp=e.get("timestamp", ""),
                )
            )
        exp = trail.explain_selection(transaction_id, strategy=strategy)
        if exp.get("decision") is None and exp.get("prediction") is None:
            result_file = RUNS_DIR / batch_id / "result.json"
            if result_file.exists():
                res_data = json.loads(result_file.read_text(encoding="utf-8"))
                if transaction_id not in res_data.get("transaction_ids", []):
                    raise HTTPException(
                        status_code=404,
                        detail=f"transaction {transaction_id} not found in batch {batch_id}",
                    )
        return exp
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"failed to explain transaction: {exc}"
        )


# ---------------------------------------------------------------------------
# Production auth endpoints (only available in production mode)
# ---------------------------------------------------------------------------
@app.post("/auth/token")
async def login_token(req: dict[str, str]) -> dict:
    """Issue an access token. In demo mode, returns a synthetic token."""
    settings = get_settings()
    if settings.mode == "demo":
        return {
            "access_token": "demo-token",
            "token_type": "Bearer",
            "expires_in": settings.access_token_ttl_seconds,
        }
    raise HTTPException(
        status_code=501,
        detail="Production login requires database. Use /v1/auth/token.",
    )


__all__ = ["app"]
