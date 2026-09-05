#!/usr/bin/env python
"""Step 1 end-to-end runner.

    python scripts/run_step1.py            # generate + clean + validate + split + report
    python scripts/run_step1.py --load-db  # also load validated data into PostgreSQL
    python scripts/run_step1.py --seed 7   # reproducible alternative seed

Database credentials are read from environment variables (see .env.example):
RPA_DB_HOST, RPA_DB_PORT, RPA_DB_NAME, RPA_DB_USER, RPA_DB_PASSWORD, RPA_DB_SCHEMA.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the project root (parent of scripts/) is importable regardless of CWD.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_core.config import DATA_GENERATION_SEED
from data_core.pipeline import Step1Pipeline


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="RPA Step 1 data foundation pipeline")
    p.add_argument("--seed", type=int, default=DATA_GENERATION_SEED)
    p.add_argument("--load-db", action="store_true", help="load validated data into PostgreSQL")
    p.add_argument("--n-customers", type=int, default=None)
    p.add_argument("--target-total", type=int, default=None)
    args = p.parse_args(argv)

    kwargs: dict = {"seed": args.seed}
    if args.n_customers is not None:
        kwargs["n_customers"] = args.n_customers
    if args.target_total is not None:
        kwargs["target_total"] = args.target_total
    pipeline = Step1Pipeline(**kwargs)
    result = pipeline.run(load_db=args.load_db, verbose=True)
    if not result.summary["trusted"]:
        print("[step1] WARNING: dataset is NOT trusted (validation rejected records).")
        return 1
    print("[step1] DONE. Trusted dataset ready for Step 2+.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
