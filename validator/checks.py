"""
The behave-specific structural checks — all pure `ast`, all deterministic:

  class 1  duplicate / colliding step definitions
  class 5  no-op `then` steps that assert nothing
  class 6  unconditional raise, and unreachable (dead) code
  class 7  over-mocking / fake-pass (mocking instead of a real call)

Undefined names (classes 2 & 4) live in scope.py; library availability
(class 3) lives in environment.py.
"""
from __future__ import annotations

import ast
from typing import Iterator, List

from .loader import StepModule
from .models import Finding, Severity

STEP_DECORATORS = {"given", "when", "then", "step"}
MOCK_FACTORIES = {"MagicMock", "Mock", "AsyncMock", "NonCallableMock", "create_autospec"}
TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _callable_name(node: ast.AST):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _callable_name(node.func)
    return None


def _iter_functions(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _step_decorators(func) -> List[tuple]:
    """(step_type, pattern, lineno) for each @given/@when/@then/@step on func."""
    out = []
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Call):
            name = _callable_name(decorator.func)
            if name in STEP_DECORATORS and decorator.args:
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.append((name, first.value, decorator.lineno))
    return out


def _body_without_docstring(body: List[ast.stmt]) -> List[ast.stmt]:
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


# --- class 1 -----------------------------------------------------------------
def check_duplicate_steps(modules: List[StepModule]) -> List[Finding]:
    """Replicates behave's registry: a step is keyed by (type, pattern). Two
    functions sharing a key collide — behave keeps the last, so the earlier ones
    are dead code. Keyed on the PATTERN, never the function name."""
    registry = {}  # (step_type, pattern) -> [(file, line)]
    for module in modules:
        for func in _iter_functions(module.tree):
            for step_type, pattern, line in _step_decorators(func):
                registry.setdefault((step_type, pattern), []).append((module.path, line))

    findings: List[Finding] = []
    for (step_type, pattern), sites in registry.items():
        if len(sites) < 2:
            continue
        for path, line in sites:
            others = [f"{p}:{l}" for p, l in sites if (p, l) != (path, line)]
            findings.append(Finding(
                rule="duplicate-step-definition", severity=Severity.ERROR,
                file=path, line=line, symbol=f'@{step_type}("{pattern}")',
                message=(f'duplicate step "{pattern}" — also defined at '
                         f'{", ".join(others)}; behave keeps the last, the rest are dead code'),
                suggestion="remove or rename the duplicate so each step pattern is unique"))
    return findings


# --- class 5 -----------------------------------------------------------------
def check_noop_steps(modules: List[StepModule]) -> List[Finding]:
    """A `then` step is meant to assert. One whose body is empty or only
    pass/docstring asserts nothing — it passes no matter what the system does."""
    findings: List[Finding] = []
    for module in modules:
        for func in _iter_functions(module.tree):
            steps = _step_decorators(func)
            if "then" not in {t for t, _, _ in steps}:
                continue
            body = _body_without_docstring(func.body)
            trivial = all(
                isinstance(stmt, ast.Pass)
                or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
                for stmt in body)
            if not body or trivial:
                findings.append(Finding(
                    rule="no-op-step", severity=Severity.ERROR,
                    file=module.path, line=func.lineno, symbol=func.name,
                    message=(f"step '{func.name}' asserts nothing — it passes no "
                             f"matter what the system does"),
                    suggestion="assert a concrete expected value, or this is a false pass"))
    return findings


# --- class 6 -----------------------------------------------------------------
def check_unconditional_raise(modules: List[StepModule]) -> List[Finding]:
    """A step whose first real statement is `raise` fails every scenario that
    uses it before any assertion runs."""
    findings: List[Finding] = []
    for module in modules:
        for func in _iter_functions(module.tree):
            if not _step_decorators(func):
                continue
            body = _body_without_docstring(func.body)
            if body and isinstance(body[0], ast.Raise):
                raised = body[0].exc
                exc_name = _callable_name(raised) if raised is not None else None
                findings.append(Finding(
                    rule="unconditional-raise", severity=Severity.ERROR,
                    file=module.path, line=body[0].lineno, symbol=func.name,
                    message=(f"step '{func.name}' always raises "
                             f"{exc_name or 'an exception'} before doing anything — "
                             f"every scenario using it fails"),
                    suggestion="implement the step or remove it; never register a stub that always raises"))
    return findings


def check_dead_code(modules: List[StepModule]) -> List[Finding]:
    """Any statement after a return/raise/break/continue in the same block can
    never run."""
    findings: List[Finding] = []
    for module in modules:
        for node in ast.walk(module.tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for index, stmt in enumerate(block[:-1]):
                    if isinstance(stmt, TERMINALS):
                        unreachable = block[index + 1]
                        findings.append(Finding(
                            rule="dead-code", severity=Severity.WARNING,
                            file=module.path, line=unreachable.lineno,
                            message=(f"unreachable code after "
                                     f"{type(stmt).__name__.lower()} on line {stmt.lineno}"),
                            suggestion="remove the unreachable statements"))
                        break
    return findings


# --- class 7 -----------------------------------------------------------------
def check_over_mocking(modules: List[StepModule],
                       external_boundaries=frozenset()) -> List[Finding]:
    """Mocking the system under test means asserting on a stand-in, not the real
    call path — the fake-pass pattern. `external_boundaries` is the (caller-
    supplied, not hardcoded) set of top-level modules it is legitimate to mock
    (the edges the sandbox is meant to provide); everything else is flagged."""
    findings: List[Finding] = []
    for module in modules:
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callable_name(node.func) or ""
            if name == "patch":
                target = None
                if (node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    target = node.args[0].value
                root = target.split(".")[0] if target else None
                if root and root in external_boundaries:
                    continue
                findings.append(Finding(
                    rule="over-mocking", severity=Severity.WARNING,
                    file=module.path, line=node.lineno, symbol=target or "patch(...)",
                    message=(f"patches {target or 'a dependency'} — the test exercises "
                             f"a stand-in, not the real call path"),
                    suggestion="call the real code against the sandbox (e.g. LocalStack) instead of patching it"))
            elif name in MOCK_FACTORIES:
                findings.append(Finding(
                    rule="over-mocking", severity=Severity.WARNING,
                    file=module.path, line=node.lineno, symbol=name,
                    message=(f"builds a {name} — asserting on a fake object proves "
                             f"nothing about the real system"),
                    suggestion="exercise the real call path and assert on its real output"))
    return findings
