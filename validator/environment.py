"""
Class 3 — is each imported library actually available?

No hardcoded allowlist. A name is "available" if it is part of the standard
library, OR an installed distribution in the active environment, OR a first-party
module that exists in the scanned project. Anything else is missing.

This is the one check that depends on the environment, by design: it must run
INSIDE the target environment, because that is the only place that knows
what is actually installed — and where import-name vs package-name mismatches
(e.g. `sklearn` ships in `scikit-learn`) resolve correctly. It is therefore
opt-in (`--check-libraries`), not part of the default static run.
"""
from __future__ import annotations

import ast
import sys
from typing import Iterator, List, Set, Tuple

from .loader import StepModule
from .models import Finding, Severity

try:
    from importlib.metadata import packages_distributions
except ImportError:  # Python < 3.10
    packages_distributions = None  # type: ignore


def _stdlib_modules() -> Set[str]:
    return set(getattr(sys, "stdlib_module_names", set()))


def _installed_top_level() -> Set[str]:
    if packages_distributions is None:
        return set()
    # maps importable top-level name -> [distribution names]; we want the keys
    return set(packages_distributions().keys())


def _imported_roots(tree: ast.Module) -> Iterator[Tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # `from . import x` is first-party
            if node.module:
                yield node.module.split(".")[0], node.lineno


def check_unavailable_libraries(modules: List[StepModule],
                                first_party: Set[str]) -> List[Finding]:
    available = _stdlib_modules() | _installed_top_level() | first_party
    findings: List[Finding] = []
    for module in modules:
        seen: Set[str] = set()
        for root, line in _imported_roots(module.tree):
            if root in seen or root in available:
                continue
            seen.add(root)
            findings.append(Finding(
                rule="unavailable-library", severity=Severity.ERROR,
                file=module.path, line=line, symbol=root,
                message=f"imports '{root}', which is not available in this environment",
                suggestion=("install or declare it, or remove the import; "
                            "run this check inside the target environment")))
    return findings
