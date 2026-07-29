"""
``lint_tests`` — static linter over the generated step files.

Wraps the already-built validator (``validator.validate``) verbatim and maps its
``Report`` to a Pydantic ``LintReport`` so the tool has a clean, schema-typed
output. Exposed to the agent **because it is a static linter**: it can only
surface problems, never certify a pass, so it cannot be reward-hacked into a
false green. The authoritative pass/fail oracle stays external (not a tool).

Behave/Python only today. For Cucumber (Java) output the compile step IS the
undefined-name/missing-import check — the agent runs ``javac`` via ``shell``
when a JDK is available; Karate (self-contained .feature) has no linter yet.
When a lint run finds zero Python files, the report says so explicitly — a
zero-file "ok" is never presented as a validated pass.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel

from coding_agent.tools._strands import tool


class LintFinding(BaseModel):
    rule: str
    severity: Literal["ERROR", "WARNING"]
    file: str
    line: int
    message: str
    suggestion: str = ""
    symbol: str = ""


class LintReport(BaseModel):
    ok: bool                  # True iff no ERROR findings
    files_checked: int
    error_count: int
    warning_count: int
    findings: List[LintFinding] = []
    note: str = ""            # honesty channel: what this run did NOT cover


@tool
def lint_tests(
    path: str,
    check_libraries: bool = False,
    external_boundaries: List[str] = [],
) -> LintReport:
    """Statically check your generated Behave step files BEFORE you finish.

    Catches the failure classes that produce fake-passing tests: duplicate step
    definitions, undefined names, unavailable imports, no-op steps, unconditional
    raises, dead code, and over-mocking (stubbing real code instead of calling it).
    Fix every ERROR and re-lint before emitting. This finds problems only — it does
    NOT mean your test passes; the external evaluation decides that.

    Args:
        path: file or directory of generated step files (must be inside the workspace).
        check_libraries: also verify imports exist in the runtime environment.
        external_boundaries: top-level module names legitimately allowed to be mocked
            (e.g. ["boto3"] when only the AWS boundary is mocked).
    """
    import json
    import os

    from validator import validate  # lazy import: validator is a sibling package

    # Per-application team standards: the caller (core / UI) drops the app's
    # ``standards.json`` at the lint root; when present, its rules run as part of
    # this same static pass. Config is per-app DATA — nothing team-specific in code.
    standards = None
    standards_note = ""
    std_dir = path if os.path.isdir(path) else os.path.dirname(path)
    std_path = os.path.join(std_dir, "standards.json")
    if os.path.isfile(std_path):
        try:
            with open(std_path, encoding="utf-8") as fh:
                standards = json.load(fh)
            standards_note = "Team standards applied from standards.json."
        except (OSError, json.JSONDecodeError) as exc:
            return LintReport(
                ok=False, files_checked=0, error_count=1, warning_count=0,
                findings=[LintFinding(
                    rule="team-standards-config", severity="ERROR", file=std_path,
                    line=0, message=f"standards.json could not be read: {exc}",
                    suggestion="fix the standards file — rules must never half-apply.")],
                note="Lint aborted: the team-standards config is unreadable.",
            )

    try:
        report = validate(
            path,
            check_libraries=check_libraries,
            external_boundaries=frozenset(external_boundaries),
            standards=standards,
        )
    except ValueError as exc:
        # A malformed standards config raises in validate() — surface it as a
        # finding (actionable), never a crash and never a silent skip.
        return LintReport(
            ok=False, files_checked=0, error_count=1, warning_count=0,
            findings=[LintFinding(
                rule="team-standards-config", severity="ERROR", file=std_path,
                line=0, message=str(exc),
                suggestion="fix the standards file — rules must never half-apply.")],
            note="Lint aborted: the team-standards config is invalid.",
        )
    d = report.to_dict()
    note = standards_note
    if d["files_checked"] == 0:
        note = (note + " " if note else "") + (
                "0 Python step files found under this path. This linter covers "
                "Python/Behave only — non-Python test files (e.g. Cucumber Java "
                "step classes) were NOT checked. Do not treat this as a validated "
                "pass; for Java, compile the step classes (javac) as the check.")
    return LintReport(
        ok=d["ok"],
        files_checked=d["files_checked"],
        error_count=d["error_count"],
        warning_count=d["warning_count"],
        findings=[LintFinding(**f) for f in d["findings"]],
        note=note,
    )
