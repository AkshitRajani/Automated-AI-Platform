"""Injected fakes — isolate gate logic from real execution and a real KB."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, List, Optional, Set

from eval.execution import ExecCase, RunOutcome


class FakeEnv:
    """Returns scripted outcomes. `baseline` is returned by the first call and by
    any mutant-free call; `mutant_passed` controls whether mutants are caught."""

    def __init__(self, baseline: RunOutcome, mutant_passed: bool = False):
        self._baseline = baseline
        self._mutant_passed = mutant_passed
        self.calls = 0

    def run(self, case: ExecCase, sut_source: Optional[str] = None) -> RunOutcome:
        self.calls += 1
        if sut_source is None:
            return self._baseline
        # a mutant run: did the test notice (fail) or not (pass)?
        return RunOutcome(passed=self._mutant_passed,
                          covered=self._baseline.covered)


class FakeResolver:
    """Confirms only the names it was given."""

    def __init__(self, names: List[str]):
        self._names = set(names)

    def resolve(self, query: str, kind: str = "any", app_id: str = "", limit: int = 10):
        cands = ([SimpleNamespace(canonical_name=query, resolved=True)]
                 if query in self._names else [])
        return SimpleNamespace(candidates=cands)


def covered(sut_path: str, lines: Set[int]) -> Dict[str, Set[int]]:
    return {sut_path: set(lines)}
