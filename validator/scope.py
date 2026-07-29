"""
Classes 2 & 4 — undefined names / missing imports.

The "given list vs used list" check, done properly with lexical scope. A name
used in the code must resolve to something the file was *given*: an import, a
definition, a function argument, a Python builtin, or a name behave injects into
step modules. We resolve each used name outward through its scope chain
(innermost first), exactly as Python does — never by matching text.

A name defined inside one function is not visible inside another (different
"rooms"); the scope stack is what tracks that.
"""
from __future__ import annotations

import ast
import builtins
import os
from typing import Dict, List, Set

from .loader import StepModule
from .models import Finding, Severity

BUILTIN_NAMES: Set[str] = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__builtins__",
    "__loader__", "__spec__", "__package__", "__path__", "__dict__",
}

# behave makes these available inside step modules without an import.
BEHAVE_INJECTED: Set[str] = {
    "given", "when", "then", "step",
    "use_step_matcher", "register_type", "step_matcher", "matchers",
}


def _collect_targets(target: ast.AST, into: Set[str]) -> None:
    if isinstance(target, ast.Name):
        into.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_targets(elt, into)
    elif isinstance(target, ast.Starred):
        _collect_targets(target.value, into)
    # Attribute / Subscript targets (a.b = ..., a[i] = ...) bind no new name


def _scope_bindings(body: List[ast.stmt]):
    """Names bound directly in this scope. Does not descend into nested
    function/class bodies (separate scopes), but a nested def/class NAME binds
    here. Returns (bound, has_unknown_star_import)."""
    bound: Set[str] = set()
    unknown_star = False

    def handle(stmt: ast.AST) -> None:
        nonlocal unknown_star
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                _collect_targets(target, bound)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            _collect_targets(stmt.target, bound)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    # `from behave import *` only adds known names; any other
                    # star import could bind anything, so we stop guessing.
                    if stmt.module != "behave":
                        unknown_star = True
                else:
                    bound.add(alias.asname or alias.name)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)  # the name binds here; the body is a new scope
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            _collect_targets(stmt.target, bound)
            for sub in stmt.body + stmt.orelse:
                handle(sub)
        elif isinstance(stmt, (ast.While, ast.If)):
            for sub in stmt.body + stmt.orelse:
                handle(sub)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    _collect_targets(item.optional_vars, bound)
            for sub in stmt.body:
                handle(sub)
        elif isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                if handler.name:
                    bound.add(handler.name)
                for sub in handler.body:
                    handle(sub)
            for sub in stmt.body + stmt.orelse + stmt.finalbody:
                handle(sub)
        elif isinstance(stmt, (ast.Global, ast.Nonlocal)):
            for name in stmt.names:
                bound.add(name)

    for stmt in body:
        handle(stmt)
    return bound, unknown_star


class _Frame:
    __slots__ = ("bound", "unknown_star")

    def __init__(self, bound: Set[str], unknown_star: bool):
        self.bound = bound
        self.unknown_star = unknown_star


class _Analyzer(ast.NodeVisitor):
    """Walks the tree carrying a stack of scope frames; reports every Load of a
    name that resolves nowhere."""

    def __init__(self) -> None:
        self.frames: List[_Frame] = []
        self.undefined: List[tuple] = []  # (name, lineno)

    # --- resolution ---
    def _resolve(self, name: str) -> bool:
        if name in BUILTIN_NAMES or name in BEHAVE_INJECTED:
            return True
        return any(name in frame.bound for frame in self.frames)

    def _suppressed(self) -> bool:
        # an unknown `*` import could have bound anything: don't guess
        return any(frame.unknown_star for frame in self.frames)

    # --- scope helpers ---
    def _add_args(self, args: ast.arguments, bound: Set[str]) -> None:
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            bound.add(arg.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)

    def _visit_defaults(self, args: ast.arguments) -> None:
        for default in list(args.defaults) + list(args.kw_defaults):
            if default is not None:
                self.visit(default)

    # --- scopes ---
    def visit_Module(self, node: ast.Module) -> None:
        bound, star = _scope_bindings(node.body)
        self.frames.append(_Frame(bound, star))
        for stmt in node.body:
            self.visit(stmt)
        self.frames.pop()

    def _function(self, node) -> None:
        # decorators and default values are evaluated in the ENCLOSING scope
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_defaults(node.args)
        bound, star = _scope_bindings(node.body)
        self._add_args(node.args, bound)
        self.frames.append(_Frame(bound, star))
        for stmt in node.body:
            self.visit(stmt)
        self.frames.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_defaults(node.args)
        bound: Set[str] = set()
        self._add_args(node.args, bound)
        self.frames.append(_Frame(bound, False))
        self.visit(node.body)
        self.frames.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        bound, star = _scope_bindings(node.body)
        self.frames.append(_Frame(bound, star))
        for stmt in node.body:
            self.visit(stmt)
        self.frames.pop()

    def _comprehension(self, node) -> None:
        bound: Set[str] = set()
        for generator in node.generators:
            _collect_targets(generator.target, bound)
        self.frames.append(_Frame(bound, False))
        self.generic_visit(node)
        self.frames.pop()

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # walrus :=
        if isinstance(node.target, ast.Name) and self.frames:
            self.frames[-1].bound.add(node.target.id)
        self.visit(node.value)

    # --- the actual check ---
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not self._suppressed():
            if not self._resolve(node.id):
                self.undefined.append((node.id, node.lineno))


def check_undefined_names(modules: List[StepModule],
                          functions_by_name: Dict[str, str]) -> List[Finding]:
    findings: List[Finding] = []
    for module in modules:
        analyzer = _Analyzer()
        analyzer.visit(module.tree)
        seen: Set[str] = set()
        for name, line in analyzer.undefined:
            if name in seen:
                continue
            seen.add(name)
            origin = functions_by_name.get(name)
            if origin and origin != module.path:
                findings.append(Finding(
                    rule="missing-cross-file-import", severity=Severity.ERROR,
                    file=module.path, line=line, symbol=name,
                    message=(f"uses '{name}', which is defined in "
                             f"{os.path.basename(origin)} but never imported here"),
                    suggestion=f"import '{name}' from its module before using it"))
            else:
                findings.append(Finding(
                    rule="undefined-name", severity=Severity.ERROR,
                    file=module.path, line=line, symbol=name,
                    message=(f"uses '{name}', which is never imported or defined "
                             f"(NameError at runtime)"),
                    suggestion=f"import or define '{name}' before using it"))
    return findings
