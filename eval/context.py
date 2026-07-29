"""
What the cascade needs to judge one test: the execution case (SUT + test), the
identifiers to ground, the changed lines for gate 5, and — optionally — a folder
of step files for the static validator layer.

`from_bundle` adapts the coding agent's `TestBundle` into an `EvalContext`,
pulling the grounded identifiers straight off the bundle. The execution case and
changed lines come from the task/workspace (not the bundle), so they are passed
explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from .execution import ExecCase


@dataclass
class EvalContext:
    app_id: str
    case: ExecCase
    changed_lines: Dict[str, Set[int]] = field(default_factory=dict)
    identifiers: List[Tuple[str, str]] = field(default_factory=list)   # (name, kind)
    steps_root: Optional[str] = None          # dir of step files → static validator layer
    external_boundaries: FrozenSet[str] = frozenset()   # modules the test may legitimately mock
    stability_runs: int = 3
    mutation_max: int = 8

    @classmethod
    def from_bundle(cls, bundle, app_id: str, case: ExecCase,
                    changed_lines: Optional[Dict[str, Set[int]]] = None,
                    steps_root: Optional[str] = None,
                    external_boundaries: FrozenSet[str] = frozenset()) -> "EvalContext":
        identifiers = [(g.name, g.kind)
                       for g in getattr(bundle, "grounded_identifiers", [])]
        return cls(
            app_id=app_id,
            case=case,
            changed_lines=changed_lines or {},
            identifiers=identifiers,
            steps_root=steps_root,
            external_boundaries=external_boundaries,
        )
