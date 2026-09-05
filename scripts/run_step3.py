"""Step 3 CLI — run the RPA backend pipeline or the FastAPI server.

Usage:
    .venv/bin/python scripts/run_step3.py batch   [--split demo] [--seed 0] [--db]
    .venv/bin/python scripts/run_step3.py server  [--port 8000]
    .venv/bin/python scripts/run_step3.py report  [--batch-id <id>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_step3", description="RPA Step 3 backend")
    sub = parser.add_subparsers(dest="command")

    p_batch = sub.add_parser("batch", help="Run a full recovery batch on a split")
    p_batch.add_argument("--split", default="demo")
    p_batch.add_argument("--seed", type=int, default=0)
    p_batch.add_argument("--db", action="store_true", help="attempt DB persistence")
    p_batch.add_argument("--strategies", nargs="*", default=None)

    p_server = sub.add_parser("server", help="Run the FastAPI server")
    p_server.add_argument("--host", default="127.0.0.1")
    p_server.add_argument("--port", type=int, default=8000)

    p_report = sub.add_parser("report", help="Print a batch summary report")
    p_report.add_argument("--batch-id", required=True)

    args = parser.parse_args(argv)
    if args.command == "batch":
        from rpa.orchestrator import run_batch_on_split
        result = run_batch_on_split(
            args.split, batch_seed=args.seed, strategies=args.strategies
        )
        print(json.dumps(result.summary(), indent=2, default=str))
        print(f"\naudit: rpa_runs/{result.batch_id}/audit.json")
        print(f"result: rpa_runs/{result.batch_id}/result.json")
        if args.db:
            from rpa.db import persist_batch_result
            ok = persist_batch_result(result)
            print(f"[step3] DB persist attempted: {ok}")
        return 0

    if args.command == "server":
        import uvicorn
        uvicorn.run("rpa.api:app", host=args.host, port=args.port, reload=False)
        return 0

    if args.command == "report":
        from rpa.orchestrator import load_batch_result
        data = load_batch_result(args.batch_id)
        print(json.dumps(data, indent=2, default=str))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())