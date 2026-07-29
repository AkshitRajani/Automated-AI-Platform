"""
Discover step files and parse each into a syntax tree.

This is the front of the pipeline: turn source text into the labeled tree the
checks read. A file that does not even parse becomes a finding (the "does it
run" question) instead of crashing the whole run.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import List, Tuple

from .models import Finding, Severity


@dataclass
class StepModule:
    path: str
    source: str
    tree: ast.Module


def discover_python_files(root: str) -> List[str]:
    """Every .py file under `root` (or just `root` itself if it is a file)."""
    if os.path.isfile(root):
        return [root] if root.endswith(".py") else []
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def load_modules(root: str) -> Tuple[List[StepModule], List[Finding]]:
    modules: List[StepModule] = []
    findings: List[Finding] = []
    for path in discover_python_files(root):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as exc:
            findings.append(Finding(
                rule="unreadable-file", severity=Severity.ERROR,
                file=path, line=0, message=f"could not read file: {exc}"))
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            findings.append(Finding(
                rule="syntax-error", severity=Severity.ERROR,
                file=path, line=exc.lineno or 0,
                message=f"file does not parse: {exc.msg}",
                suggestion="the test cannot run until the syntax error is fixed"))
            continue
        modules.append(StepModule(path=path, source=source, tree=tree))
    return modules, findings
