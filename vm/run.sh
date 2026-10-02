#!/usr/bin/env bash
# EqualEd VM warehouse dashboard
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r vm/requirements.txt
fi
exec .venv/bin/python vm/app.py "$@"
