"""
CLI entry — run the Coding Agent on one task.

    PYTHONPATH=/path/to/2026/implementation python -m coding_agent task.json

``task.json`` is an ``AgentTask`` (see ``schemas.py``):

    {
      "ticket_id": "ETSAPS-1",
      "ticket_text": "Charge a 5% late fee when a payment is >15 days overdue.",
      "diff": "--- a/late.py\\n+++ b/late.py\\n@@ ...",
      "framework": "behave",
      "scope": {"app_id": "APP"},
      "workspace_dir": "/abs/path/to/workspace"
    }

Connection + model settings come from ``.env`` (never hardcoded). Running the
agent requires the Strands runtime + valid Bedrock/KB settings; this entry
fails fast with a clear message if they are missing.
"""
from __future__ import annotations

import json
import sys

from coding_agent.schemas import AgentTask


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2

    with open(argv[0]) as f:
        task = AgentTask.model_validate(json.load(f))

    # Imported here so `python -m coding_agent --help`-style misuse doesn't
    # require the Strands runtime just to print usage. Route by mode: a diff means
    # per-change; no diff means whole-app functional suite.
    if task.diff.strip():
        from coding_agent.boundary import run_with_boundary
        outcome = run_with_boundary(task)
    else:
        from coding_agent.boundary import run_suite_with_boundary
        outcome = run_suite_with_boundary(task)
    print(outcome.model_dump_json(indent=2))
    return 0 if outcome.delivered else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
