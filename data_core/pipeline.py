"""Step 1 pipeline orchestrator.

End-to-end data foundation pipeline (Step 1 ONLY -- no model, no optimizer,
no strategy, no recovery-decision logic):

    generate  ->  clean  ->  validate  ->  split  ->  (report)  ->  (optional DB)

Stages
------
1. **generate** - reproducible neutral synthetic dataset (customers, txn,
   actions, outcomes; empty predictions/decisions). Written to ``data/raw/``.
2. **clean**    - policies applied; rejected rows + transformations recorded.
   Cleaned frames written to ``data/cleaned/``.
3. **validate** - Pydantic structural + cross-record integrity checks.
   Accepted frames written to ``data/validated/``.
4. **split**    - customer-grouped, leakage-free train/val/test/demo.
   Written to ``data/splits/``.
5. **report**   - data-quality report (JSON + Markdown) in ``reports/``.
6. **load_db**  - optional: load validated frames into PostgreSQL (env-driven).
   Skipped automatically when no DB is reachable.

Usage:
    from data_core.pipeline import Step1Pipeline
    Step1Pipeline().run()          # end-to-end, writes all artifacts
    Step1Pipeline().run(load_db=True)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .config import (
    AUDIT_TIMESTAMP,
    CLEANED_PATH,
    DATA_GENERATION_SEED,
    QUALITY_REPORT_JSON_PATH,
    QUALITY_REPORT_MD_PATH,
    RAW_PATH,
    REPORTS_DIR,
    SPLITS_DIR,
    SPLIT_SEED,
    VALIDATED_PATH,
    N_CUSTOMERS,
)
from .cleaning import CleaningPipeline
from .db import Database
from .generator import SyntheticDataGenerator
from .io import write_dataset, write_frame
from .quality_report import DataQualityReport, build_quality_report
from .splitting import assert_no_leakage, save_splits, split_transactions
from .validation import validate


def _audit(dataset_name: str, stage: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "audit_id": f"aud_{stage}",
        "entity_type": dataset_name,
        "entity_id": dataset_name,
        "event_type": stage,
        "event_metadata": payload or {},
        "timestamp": AUDIT_TIMESTAMP,
    }


@dataclass
class PipelineResult:
    raw_frames: Dict[str, pd.DataFrame] = None  # type: ignore[assignment]
    cleaned_frames: Dict[str, pd.DataFrame] = None  # type: ignore[assignment]
    validated_frames: Dict[str, pd.DataFrame] = None  # type: ignore[assignment]
    splits: Dict[str, pd.DataFrame] = None  # type: ignore[assignment]
    cleaning_report: Any = None
    validation_result: Any = None
    quality_report: DataQualityReport = None  # type: ignore[assignment]
    db_loaded: bool = False
    summary: Dict[str, Any] = None  # type: ignore[assignment]


class Step1Pipeline:
    """Configurable, reproducible Step 1 data-foundation pipeline."""

    def __init__(
        self,
        seed: int = DATA_GENERATION_SEED,
        n_customers: int = N_CUSTOMERS,
        target_total: int = 2000,
        dataset_name: str = "rpa_step1_synthetic",
    ) -> None:
        self.seed = seed
        self.n_customers = n_customers
        self.target_total = target_total
        self.dataset_name = dataset_name
        self.generator = SyntheticDataGenerator(seed)
        self.cleaner = CleaningPipeline()

    # ------------------------------------------------------------------
    def generate(self) -> Dict[str, pd.DataFrame]:
        generated = self.generator.generate(
            n_customers=self.n_customers, target_total=self.target_total
        )
        frames = generated.to_frames()
        # Record generation as an audit event.
        audit_row = _audit(self.dataset_name, "raw_data_generated", {"seed": self.seed, "counts": generated.counts()})
        frames["audit_logs"] = pd.concat(
            [frames.get("audit_logs", pd.DataFrame()),
             pd.DataFrame([audit_row])],
            ignore_index=True,
        )
        for d in (RAW_PATH.parent,):
            d.mkdir(parents=True, exist_ok=True)
        write_dataset(frames, RAW_PATH.parent)
        return frames

    def clean(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        cd = self.cleaner.clean(frames)
        for d in (CLEANED_PATH.parent,):
            d.mkdir(parents=True, exist_ok=True)
        write_dataset(cd.frames, CLEANED_PATH.parent)
        self._last_cleaning_report = cd.report
        return cd.frames

    def validate(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        res = validate(frames)
        self._last_validation = res
        for d in (VALIDATED_PATH.parent,):
            d.mkdir(parents=True, exist_ok=True)
        write_dataset(res.accepted, VALIDATED_PATH.parent)
        # Persist rejected rows for auditability.
        if res.rejected:
            rej_dir = VALIDATED_PATH.parent / "rejected"
            write_dataset(res.rejected, rej_dir)
        return res.accepted

    def split(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        customers = frames["customers"]
        transactions = frames["transactions"]
        splits = split_transactions(transactions, customers, seed=SPLIT_SEED)
        assert_no_leakage(splits)
        paths = save_splits(splits)
        self._last_split_paths = paths
        return splits

    # ------------------------------------------------------------------
    def _build_quality_report(self, frames, splits) -> DataQualityReport:
        report = build_quality_report(
            dataset_name=self.dataset_name,
            generated=frames,
            cleaning_report=self._last_cleaning_report,
            validation_result=self._last_validation,
            splits=splits,
        )
        for d in (QUALITY_REPORT_JSON_PATH.parent,):
            d.mkdir(parents=True, exist_ok=True)
        report.to_json(QUALITY_REPORT_JSON_PATH)
        QUALITY_REPORT_MD_PATH.write_text(report.to_markdown(), encoding="utf-8")
        return report

    def _try_load_db(self, frames: Dict[str, pd.DataFrame]) -> bool:
        """Best-effort DB load; returns True if loaded, False if skipped."""
        try:
            from .db import connect, Database  # noqa: WPS433
            conn = connect()
        except Exception as exc:  # no DB / bad credentials
            print(f"[step1] DB load skipped: {exc}")
            return False
        try:
            db = Database()
            db.create_schema(conn, reset=True)
            db.load_dataset(conn, frames, reset=True)
            conn.close()
            return True
        except Exception as exc:
            print(f"[step1] DB load failed: {exc}")
            try:
                conn.close()
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    def run(self, load_db: bool = False, verbose: bool = True) -> PipelineResult:
        """Run the full Step 1 pipeline end-to-end."""
        if verbose:
            print(f"[step1] Generating synthetic dataset (seed={self.seed}, "
                  f"n_customers={self.n_customers}, target_total={self.target_total})...")
        raw = self.generate()
        if verbose:
            print(f"[step1] Raw records: {sum(len(f) for f in raw.values())}")

        if verbose:
            print("[step1] Cleaning ...")
        cleaned = self.clean(raw)
        cr = self._last_cleaning_report
        if verbose:
            print(f"[step1] Cleaned: {cr.total_cleaned} accepted, "
                  f"{cr.total_rejected} rejected, {cr.total_duplicates} duplicates removed")

        if verbose:
            print("[step1] Validating ...")
        validated = self.validate(cleaned)
        vr = self._last_validation
        if verbose:
            print(f"[step1] Validated: {vr.n_accepted} accepted, {vr.n_rejected} rejected "
                  f"(valid={vr.valid})")

        if verbose:
            print("[step1] Splitting (customer-grouped, leakage-free) ...")
        splits = self.split(validated)
        if verbose:
            print(f"[step1] Splits: {self._last_split_paths}")

        report = self._build_quality_report(raw, splits)
        if verbose:
            print(f"[step1] Quality report: {QUALITY_REPORT_MD_PATH}")

        db_loaded = False
        if load_db:
            db_loaded = self._try_load_db(validated)
            if verbose:
                print(f"[step1] DB load: {'ok' if db_loaded else 'skipped'}")

        summary = {
            "seed": self.seed,
            "dataset_name": self.dataset_name,
            "raw_counts": {k: len(v) for k, v in raw.items()},
            "cleaned_counts": report.cleaning.get("by_entity", {}),
            "accepted": vr.n_accepted,
            "rejected": vr.n_rejected,
            "splits": {k: len(v) for k, v in splits.items()},
            "trusted": report.trusted,
            "db_loaded": db_loaded,
            "quality_report_md": str(QUALITY_REPORT_MD_PATH),
            "quality_report_json": str(QUALITY_REPORT_JSON_PATH),
            "raw_path": str(RAW_PATH),
            "cleaned_path": str(CLEANED_PATH),
            "validated_path": str(VALIDATED_PATH),
            "splits_dir": str(SPLITS_DIR),
        }
        return PipelineResult(
            raw_frames=raw,
            cleaned_frames=cleaned,
            validated_frames=validated,
            splits=splits,
            cleaning_report=cr,
            validation_result=vr,
            quality_report=report,
            db_loaded=db_loaded,
            summary=summary,
        )


def run(seed: int = DATA_GENERATION_SEED, load_db: bool = False, verbose: bool = True) -> PipelineResult:
    return Step1Pipeline(seed=seed).run(load_db=load_db, verbose=verbose)


__all__ = ["Step1Pipeline", "PipelineResult", "run"]
