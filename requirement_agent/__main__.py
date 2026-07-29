"""
CLI: run the requirement agent on one app's analyzer output.

    PYTHONPATH=/path/to/2026/implementation \\
      python -m requirement_agent ANALYZER_OUTPUT.yaml --app-id DCFO \\
             [--codebase /path/to/src_or_zip] [--workspace /path/to/ws]

Needs Bedrock via .env (BEDROCK_MODEL_ARN). The heavy requirement docs are written to
``<workspace>/requirements/*.json`` (+ markdown in ``requirements_md/``); the manifest
and full agent log land in the workspace too.
"""
from __future__ import annotations

import argparse
import sys

from requirement_agent.schemas import RequirementTask


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="requirement_agent", description=__doc__)
    p.add_argument("analyzer_output", help="path to the analyzer's quad YAML (entities + quads)")
    p.add_argument("--app-id", required=True, help="app id / KB scope")
    p.add_argument("--codebase", default=None, help="raw source (.zip or folder) for read_source")
    p.add_argument("--workspace", default="", help="output dir (default: a fresh temp dir)")
    args = p.parse_args(argv)

    kwargs = dict(app_id=args.app_id, analyzer_output=args.analyzer_output,
                  codebase=args.codebase)
    if args.workspace:
        kwargs["workspace_dir"] = args.workspace
    task = RequirementTask(**kwargs)

    print(f"requirement_agent: app={task.app_id} analyzer={task.analyzer_output}",
          file=sys.stderr)
    print(f"  workspace: {task.workspace_dir}", file=sys.stderr)

    # Imported here so `--help` doesn't require the Strands runtime.
    from requirement_agent.boundary import run_with_boundary
    outcome = run_with_boundary(task)

    docs = [e for e in (outcome.requirement_set.entries if outcome.requirement_set else [])
            if e.status == "documented"]
    print(f"\n{'DELIVERED' if outcome.delivered else 'ROUTED TO HUMAN'} — "
          f"{len(docs)} unit(s) documented in {outcome.attempts} attempt(s).")
    print(f"  docs:     {task.workspace_dir}/requirements/*.json")
    print(f"  markdown: {task.workspace_dir}/requirements_md/*.md")
    print(f"  manifest: {task.workspace_dir}/requirements_manifest.json")
    print(f"  log:      {task.workspace_dir}/agent_log.txt")
    if outcome.coverage_gaps:
        print(f"  coverage gaps: {len(outcome.coverage_gaps)} unit(s) unaccounted")
    if outcome.gate_reasons:
        print("  unresolved gate findings:")
        for r in outcome.gate_reasons[:10]:
            print(f"    - {r}")
    return 0 if outcome.delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
