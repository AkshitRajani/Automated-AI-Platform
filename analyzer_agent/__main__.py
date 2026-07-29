"""
CLI front door — the reference handover, mirroring ``python -m coding_agent``.

    PYTHONPATH=/path/to/2026/implementation \\
        python -m analyzer_agent <repo> --app-id DEMO [--out facts.yaml]

Runs Step 1 (parser draft) then Step 2 (the Strands+Bedrock agent), writes the
verified facts as an ingestion-ready quad YAML, and prints the run stats
(graph facts / notes / rejected / precision). Requires the Strands runtime + a
valid ``BEDROCK_MODEL_ARN`` in ``.env`` — the model is never assumed.
"""
from __future__ import annotations

import argparse
import sys

from analyzer import analyze, load_quadfile, to_yaml

from .agent import AnalyzerTask, run
from .config import ConfigError, analyzer_settings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="analyzer_agent", description=__doc__)
    p.add_argument("repo", help="path to the application codebase")
    p.add_argument("--app-id", required=True, help="KB scope / app id")
    p.add_argument("--draft", default="",
                   help="existing parser quad file to use as the draft "
                        "(default: parse the repo fresh)")
    p.add_argument("--out", default="", help="write verified facts as quad YAML here")
    p.add_argument("--notes-out", default="", help="write behavioural notes (pgvector) here")
    args = p.parse_args(argv)

    settings = analyzer_settings()
    print(f"analyzer_agent: app={args.app_id} repo={args.repo}", file=sys.stderr)
    print(f"  settings: {settings}", file=sys.stderr)

    # The agent takes the codebase PLUS the Step-1 parser draft. Supply one on disk
    # with --draft, else the agent parses the repo itself.
    draft = load_quadfile(args.draft) if args.draft else None
    if draft is not None:
        print(f"  draft: {len(draft.quads)} parser quads from {args.draft}", file=sys.stderr)

    try:
        store = run(AnalyzerTask(repo_dir=args.repo, app_id=args.app_id, draft=draft))
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    stats = store.stats()
    print(f"\n  graph facts : {stats['graph_facts']}")
    print(f"  notes       : {stats['notes']}")
    print(f"  rejected    : {stats['rejected']}")
    print(f"  precision   : {stats['precision']}/100")

    if args.out:
        open(args.out, "w").write(to_yaml(store.to_quadfile()))
        print(f"  verified facts -> {args.out}", file=sys.stderr)
    if args.notes_out:
        with open(args.notes_out, "w") as f:
            for n in store.notes:
                f.write(f"{n.subject}\t{n.predicate}\t{n.object}\t{n.file}:{n.line}\t{n.note}\n")
        print(f"  notes -> {args.notes_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
