#!/usr/bin/env python
"""Step 2 end-to-end runner.

    python scripts/run_step2.py             # train + predict + artifacts
    python scripts/run_step2.py --load-db   # also write predictions to PostgreSQL
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.config import (
    LOGREG_C,
    LOGREG_CLASS_WEIGHT,
    LOGREG_MAX_ITER,
    RANDOM_SEED,
    FeatureFlags,
)
from ml.pipeline import run_step2


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="RPA Step 2 ML pipeline")
    p.add_argument("--seed", type=int, default=RANDOM_SEED)
    p.add_argument("--c", type=float, default=LOGREG_C)
    p.add_argument("--max-iter", type=int, default=LOGREG_MAX_ITER)
    p.add_argument("--class-weight", choices=["balanced", "none"], default="none")
    p.add_argument("--save-db", action="store_true",
                   help="also write predictions to the recovery_predictions DB table")
    args = p.parse_args(argv)

    cw = LOGREG_CLASS_WEIGHT
    if args.class_weight == "balanced":
        cw = "balanced"
    elif args.class_weight == "none":
        cw = None

    flags = FeatureFlags()
    result = run_step2(
        seed=args.seed,
        logreg_c=args.c,
        class_weight=cw,
        max_iter=args.max_iter,
        flags=flags,
        save_db=args.save_db,
    )
    print(f"[step2] DONE. model={result.model_identifier}, "
          f"calibration={result.calibration_chosen}, "
          f"#test_preds={result.n_predictions_test}, "
          f"#demo_preds={result.n_predictions_demo}, "
          f"db_inserted={result.db_inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
