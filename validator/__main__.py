"""
Step-file validator — command-line entry point.

Usage:
    python -m validator <path>                  # check a file or a folder of step files
    python -m validator <path> --json           # machine-readable findings (agent loop / CI)
    python -m validator <path> --check-libraries # also verify imports exist in THIS environment

Exit code: 0 if there are no ERROR findings, 1 otherwise (CI-friendly).
Pure standard library — no install step required.
"""
from __future__ import annotations

import argparse
import json
import sys

from .models import Severity
from .runner import validate


def _format(report) -> str:
    head = (f"Checked {report.files_checked} file(s): "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    if report.files_checked == 0:
        return head + ("\n  ! no Python files found at that path — nothing was checked "
                       "(is the path correct, and quoted if it contains spaces?)")
    if not report.findings:
        return head + "\n  — no issues found"

    by_file: dict = {}
    for finding in report.findings:
        by_file.setdefault(finding.file, []).append(finding)

    lines = [head]
    for path in sorted(by_file):
        lines.append("")
        lines.append(path)
        for finding in sorted(by_file[path], key=lambda f: (f.line, f.rule)):
            mark = "x" if finding.severity is Severity.ERROR else "."
            lines.append(f"  {mark} {finding.severity.value:<7} line {finding.line:<4} "
                         f"[{finding.rule}] {finding.message}")
            if finding.suggestion:
                lines.append(f"      -> {finding.suggestion}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="validator",
        description="Deterministic static validator for Behave step files (stdlib only).")
    parser.add_argument("path", help="a step file, or a directory of step files")
    parser.add_argument("--json", action="store_true",
                        help="emit findings as JSON (for the agent repair loop / CI)")
    parser.add_argument("--check-libraries", action="store_true",
                        help="also check imported libraries exist in THIS environment "
                             "(run inside the target environment)")
    args = parser.parse_args(argv)

    report = validate(args.path, check_libraries=args.check_libraries)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_format(report))

    if report.files_checked == 0:
        return 2  # nothing was validated — a path problem, not a clean pass
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
