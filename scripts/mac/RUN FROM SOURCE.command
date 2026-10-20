#!/bin/bash
# Developer/source mode: creates .venv on first run, then starts VERBATIM.
cd "$(dirname "$0")/../.."
if [[ ! -x .venv/bin/python ]]; then
  PY=$(command -v python3.12 || command -v python3)
  "$PY" -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -r requirements.txt || { read -n1 -p "Install failed"; exit 1; }
fi
.venv/bin/python run.py "$@"
