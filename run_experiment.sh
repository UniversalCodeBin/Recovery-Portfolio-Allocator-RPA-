#!/usr/bin/env bash
# Single-command end-to-end run of the RPA validation experiment.
#   1. creates venv if missing
#   2. installs dependencies
#   3. runs the test suite
#   4. runs the full experiment (20 seeds x scenarios A..E)
#   5. prints the location of the report
set -euo pipefail

cd "$(dirname "$0")"

PY=${PYTHON:-.venv/bin/python}

if [ ! -x "$PY" ]; then
  echo "[run_experiment] creating virtual environment..."
  uv venv --python 3.11 .venv
fi

echo "[run_experiment] installing dependencies..."
uv pip install --python "$PY" -r requirements.txt

echo "[run_experiment] running test suite..."
"$PY" -m pytest

echo "[run_experiment] running full experiment (scenarios A B C D E, 20 seeds)..."
"$PY" experiment.py

echo
echo "[run_experiment] done. Report: results/experiment_report.md"
echo "[run_experiment] Plots:   results/plots/"