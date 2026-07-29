#!/usr/bin/env python3
"""
RUN EVERYTHING — one command, one scoreboard, one report file to send back.

    python verify_all.py --app <app_id> [--quads <quad_file>] [--specs <spec_workspace>]

Runs every check that applies:  quad file (if given) · spec workspace (if given) ·
knowledge base · graph · journeys. Read-only. The combined report lands in
verification_report/ — zip that folder and send it when reporting any issue.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script: str, *args: str) -> int:
    print(f"\n{'=' * 60}\n### {script} {' '.join(args)}\n{'=' * 60}")
    return subprocess.call([sys.executable, os.path.join(HERE, script), *args])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--quads", default="")
    ap.add_argument("--specs", default="")
    args = ap.parse_args()

    codes = []
    if args.quads:
        codes.append(run("check_quadfile.py", args.quads))
    if args.specs:
        specs_args = [args.specs] + (["--quads", args.quads] if args.quads else [])
        codes.append(run("check_specs.py", *specs_args))
    codes.append(run("check_kb.py", "--app", args.app))
    codes.append(run("check_graph.py", "--app", args.app))
    codes.append(run("check_journeys.py", "--app", args.app))

    print(f"\n{'=' * 60}")
    if any(codes):
        print("VERDICT: at least one check FAILED — zip the verification_report/ "
              "folder and send it back with a note of which step you ran last.")
        return 1
    print("VERDICT: all checks passed. The pipeline output is healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
