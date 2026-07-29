"""
Core CLI — drive the flows from the terminal (stdout trace sink).

    PYTHONPATH=... python -m core onboard <src> --app-id DEMO
    PYTHONPATH=... python -m core generate --app-id DEMO --ticket-file t.txt ...
    PYTHONPATH=... python -m core score --app-id DCFO --generated ./ws/features
"""
from __future__ import annotations

import argparse
import sys

from .config import ConfigError
from .pipeline import Pipeline
from .trace import stdout_listener


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="core", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("onboard", help="codebase → KB")
    po.add_argument("src", help="directory | .zip | s3://bucket/key")
    po.add_argument("--app-id", required=True)

    pg = sub.add_parser("generate", help="ticket + diff → test")
    pg.add_argument("--app-id", required=True)
    pg.add_argument("--ticket-file", required=True)
    pg.add_argument("--diff-file", required=True)
    pg.add_argument("--workspace", required=True)
    pg.add_argument("--framework", default="behave")

    ps = sub.add_parser(
        "score",
        help="generated BDD vs golden manual BDD → score_report.json + .html",
    )
    ps.add_argument("--app-id", required=True)
    ps.add_argument(
        "--generated", required=True,
        help="path to generated .feature file(s) or directory (e.g. workspace/features)",
    )
    ps.add_argument(
        "--golden", default=None,
        help="golden manual BDD directory (default: CORE_GOLDEN_BDD_ROOT/<app-id>/features)",
    )
    ps.add_argument(
        "--output", "-o", default=None,
        help="write reports here (default: CORE_SCORE_OUTPUT_DIR or cwd)",
    )
    ps.add_argument(
        "--threshold", type=float, default=None,
        help="behaviour match threshold 0..1 (default: SCORING_THRESHOLD or 0.45)",
    )
    ps.add_argument(
        "--open", action="store_true",
        help="open score_report.html in the default browser",
    )

    args = p.parse_args(argv)
    pipe = Pipeline()
    pipe.trace.add_listener(stdout_listener)

    try:
        if args.cmd == "onboard":
            r = pipe.onboard(args.src, args.app_id)
            print(f"\nparser: {r.parser_entities} entities / {r.parser_quads} quads")
            print(f"agent : {r.agent_graph_facts} facts / {r.agent_notes} notes "
                  f"(precision {r.agent_precision})")
            print(f"quad  : {r.quad_file}")
            print(f"ingested: {r.ingested}")
        elif args.cmd == "generate":
            ticket = open(args.ticket_file).read()
            diff = open(args.diff_file).read()
            r = pipe.generate(ticket_text=ticket, diff=diff, app_id=args.app_id,
                              workspace_dir=args.workspace, framework=args.framework)
            print(f"\ndelivered: {r.delivered}  attempts: {r.attempts}  "
                  f"human: {r.routed_to_human}")
            if r.reasons:
                print("reasons:\n  - " + "\n  - ".join(r.reasons))
        else:
            r = pipe.score(
                app_id=args.app_id,
                generated_dir=args.generated,
                golden_dir=args.golden,
                output_dir=args.output,
                threshold=args.threshold,
            )
            print(f"\noverall score:          {r.overall_score:.1f}%")
            print(f"behaviour coverage:     {r.behavior_coverage_pct:.1f}%")
            print(f"matched:                {r.matched_behaviors} / {r.manual_scenarios}")
            print(f"golden:                 {r.golden_dir}")
            print(f"generated:              {r.generated_dir}")
            print(f"JSON report:            {r.report_json}")
            print(f"HTML report:            {r.report_html}")
            if args.open:
                import webbrowser
                from pathlib import Path
                webbrowser.open(Path(r.report_html).resolve().as_uri())
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
