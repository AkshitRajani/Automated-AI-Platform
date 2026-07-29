"""
The orchestrator — run every check over the parsed files and return one Report.

This single entry point is what both front doors call: the CLI (`python -m
validator`) and, later, the Strands agent `@tool`. Same engine, one result shape.
"""
from __future__ import annotations

import os
from typing import Dict, FrozenSet, Optional, Set

from . import checks, environment, scope
from .loader import load_modules
from .models import Report


def _functions_by_name(modules) -> Dict[str, str]:
    """name -> file where it is defined (for cross-file-import messages)."""
    out: Dict[str, str] = {}
    for module in modules:
        for func in checks._iter_functions(module.tree):
            out.setdefault(func.name, module.path)
    return out


def _first_party_modules(modules) -> Set[str]:
    """Top-level module/package names that exist in the scanned project, so the
    library check does not flag the app's own modules as 'missing'."""
    roots: Set[str] = set()
    for module in modules:
        base = os.path.basename(module.path)
        if base.endswith(".py"):
            roots.add(base[:-3])
        roots.add(os.path.basename(os.path.dirname(module.path)))
    return roots


def validate(path: str,
             check_libraries: bool = False,
             external_boundaries: FrozenSet[str] = frozenset(),
             standards: Optional[dict] = None) -> Report:
    """``standards`` (optional) is the per-application team-standards config
    (see ``standards.py``) — rules a team promoted from recurring review feedback.
    It is validated loudly here: a malformed config raises, never half-applies."""
    modules, findings = load_modules(path)

    findings += checks.check_duplicate_steps(modules)
    findings += scope.check_undefined_names(modules, _functions_by_name(modules))
    findings += checks.check_noop_steps(modules)
    findings += checks.check_unconditional_raise(modules)
    findings += checks.check_dead_code(modules)
    findings += checks.check_over_mocking(modules, external_boundaries)

    if check_libraries:
        findings += environment.check_unavailable_libraries(
            modules, _first_party_modules(modules))

    if standards is not None:
        from .standards import check_standards, load_standards
        findings += check_standards(path, load_standards(standards))

    findings.sort(key=lambda f: (f.file, f.line, f.rule))
    return Report(findings=findings, files_checked=len(modules))
