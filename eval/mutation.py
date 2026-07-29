"""
Output sabotage — the engine behind gate 6.

A deterministic, AST-only mutator (no AI, no `mutmut` dependency). It takes the
SUT source and produces a handful of variants, each with **one return value
replaced by a fixed sentinel** (None / 0 / "" / []). Sabotaging the *output* is
universal: it works on any function — arithmetic, string, search — without
needing an operator to flip. A test that asserts on the real output will fail on
at least one such mutant (it noticed); a test that only *looks* like it checks
something fails on none.

This is the per-change, label-free use of mutation (Meta TestGen-LLM ships the
same binary filter); the ICSE-2018 "mutation is a size artifact" critique is
about suite-level mutation %, and does not apply to a single yes/no gate.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, List


@dataclass
class Mutant:
    label: str
    source: str


# Each sentinel is a fresh AST node factory (nodes can't be reused across trees).
_SENTINELS: List[tuple] = [
    ("None", lambda: ast.Constant(value=None)),
    ("0", lambda: ast.Constant(value=0)),
    ("''", lambda: ast.Constant(value="")),
    ("[]", lambda: ast.List(elts=[], ctx=ast.Load())),
]


class _ReplaceOneReturn(ast.NodeTransformer):
    """Replace the value of the return statement at ordinal ``target``."""

    def __init__(self, target: int, make_value: Callable[[], ast.expr]):
        self._seen = -1
        self._target = target
        self._make = make_value

    def visit_Return(self, node: ast.Return) -> ast.Return:
        if node.value is None:
            return node
        self._seen += 1
        if self._seen == self._target:
            return ast.Return(value=self._make())
        return node


def _value_returns(source: str, path: str) -> int:
    tree = ast.parse(source, filename=path)
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Return) and n.value is not None)


def generate_mutants(source: str, path: str, max_n: int = 8) -> List[Mutant]:
    """Up to ``max_n`` distinct output-sabotage mutants of ``source``."""
    count = _value_returns(source, path)
    mutants: List[Mutant] = []
    seen_src = {source}
    for ordinal in range(count):
        for label, make_value in _SENTINELS:
            tree = ast.parse(source, filename=path)
            mutated = _ReplaceOneReturn(ordinal, make_value).visit(tree)
            ast.fix_missing_locations(mutated)
            try:
                mutated_source = ast.unparse(mutated)
            except Exception:
                continue
            if mutated_source in seen_src:   # no-op (the return already was that value)
                continue
            seen_src.add(mutated_source)
            mutants.append(Mutant(label=f"return#{ordinal}→{label}", source=mutated_source))
            if len(mutants) >= max_n:
                return mutants
    return mutants
