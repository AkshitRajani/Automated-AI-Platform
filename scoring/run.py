#!/usr/bin/env python3
"""
Scoring launcher — no manual PYTHONPATH needed.

Reads ``scoring/scoring/.env`` (including ``SCORING_ROOT`` / ``PYTHONPATH``)
then runs the CLI.

    py run.py
    py run.py serve --open
"""
from __future__ import annotations

import sys
from pathlib import Path

_OUTER_ROOT = Path(__file__).resolve().parent
if str(_OUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_OUTER_ROOT))

from scoring.config import apply_python_path, load_env_file
from scoring.__main__ import main

load_env_file()
apply_python_path()

if __name__ == "__main__":
    raise SystemExit(main())
