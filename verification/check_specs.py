#!/usr/bin/env python3
"""
CHECK 5 — did the SPEC AGENT produce a complete spec set? (no database needed)

    python check_specs.py <spec_workspace> [--quads <quad_file.yaml>]

Verifies:  the manifest exists · every entry documented or skipped WITH a reason ·
every documented doc file exists and carries all nine sections · with --quads,
that every walked journey/family got a spec (coverage against the analyzer).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from _common import record, write_report, exit_code

SECTIONS = ["System Overview", "Input Specification", "Consolidated Requirements",
            "Output Specification", "Function Specification", "User Stories",
            "Traceability Matrix", "Confidence Mapping", "Gap Analysis"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--quads", default="")
    args = ap.parse_args()

    manifest_path = os.path.join(args.workspace, "requirements_manifest.json")
    if not os.path.isfile(manifest_path):
        record("manifest", "FAIL", f"{manifest_path} not found — the spec agent did not "
                                   f"finish (check its agent_log.txt)")
        write_report("check_specs")
        return 1
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    entries = manifest.get("entries", [])
    documented = [e for e in entries if e.get("status") == "documented"]
    skipped = [e for e in entries if e.get("status") != "documented"]
    record("manifest", "PASS",
           f"{len(documented)} documented, {len(skipped)} skipped, "
           f"{len(manifest.get('skipped_types', []))} whole types skipped with reasons")

    no_reason = [e.get("unit", "?") for e in skipped if not e.get("reason")]
    record("skips carry reasons", "PASS" if not no_reason else "FAIL",
           "every skip is explained" if not no_reason
           else f"{len(no_reason)} skips have NO reason: {', '.join(no_reason[:4])}")

    bad_docs = []
    for e in documented:
        doc_file = e.get("doc_file", "")
        path = doc_file if os.path.isabs(doc_file) else os.path.join(args.workspace, doc_file)
        if not os.path.isfile(path):
            bad_docs.append(f"{e.get('unit', '?')} (file missing)")
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            missing = [s for s in SECTIONS
                       if not str((doc.get("sections") or {}).get(s, "")).strip()]
            if missing:
                bad_docs.append(f"{e.get('unit', '?')} (missing: {', '.join(missing[:3])})")
        except Exception as exc:
            bad_docs.append(f"{e.get('unit', '?')} (unreadable: {exc})")
    record("doc files complete", "PASS" if not bad_docs else "FAIL",
           f"all {len(documented)} docs exist with all nine sections" if not bad_docs
           else f"{len(bad_docs)} problem docs: {'; '.join(bad_docs[:4])}")

    if args.quads:
        import yaml
        with open(args.quads, encoding="utf-8") as fh:
            qdoc = yaml.safe_load(fh) or {}
        walked = [str(e.get("id")) for e in (qdoc.get("entities") or [])
                  if isinstance(e, dict) and e.get("type") in ("Journey", "BehaviorGroup")]
        have = {e.get("unit") for e in entries}
        uncovered = [j for j in walked if j not in have]
        record("journey coverage vs analyzer", "PASS" if not uncovered else "FAIL",
               f"{len(walked) - len(uncovered)}/{len(walked)} walked journeys/families "
               f"accounted for in the spec set"
               + (f" — MISSING: {', '.join(uncovered[:4])}" if uncovered else ""))

    write_report("check_specs")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
