"""
The execution layer — running a test against the code under test and observing
what it touched. This is what separates the eval from the static validator: gates
3, 5, 6 and 7 need to *run* the test, not just read it.

`ExecutionEnv` is the boundary that keeps the cascade execution-model-agnostic:

  - `InProcessEnv`  — the reference adapter shipped here. Pure stdlib. Runs the
    bundle's test against an importable Python SUT and records which SUT lines ran
    via ``sys.settrace`` (no `coverage` dependency). Mutation is supported by
    passing a replacement ``sut_source`` compiled under the SUT's own filename, so
    coverage and tracebacks stay truthful. This is the backend-logic path.
  - `SandboxEnv` / `ArtsEnv` — implement the *same* protocol at the integration
    boundary (LocalStack on our side, ARTS at the client). The cascade does not
    change; only the env swaps. That swap is the whole of A/B stack parity.

A test for this layer is a Python module exposing ``def run(sut): ...`` that calls
the SUT and asserts. A raised ``AssertionError`` means the test *failed* (it
noticed); any other exception is a *setup error* (it could not run).
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Set


@dataclass
class RunOutcome:
    passed: bool
    covered: Dict[str, Set[int]] = field(default_factory=dict)   # sut_path -> executed lines
    setup_error: Optional[str] = None                            # non-assertion failure to run
    output: str = ""


@dataclass
class ExecCase:
    sut_path: str    # the code under test (a .py file)
    test_path: str   # a module exposing ``def run(sut): ...`` that calls + asserts


class ExecutionEnv(Protocol):
    def run(self, case: ExecCase, sut_source: Optional[str] = None) -> RunOutcome: ...


class InProcessEnv:
    """Reference execution env — pure stdlib, no `coverage`/`pytest`/`mutmut`.

    ``sut_source`` overrides the on-disk SUT (used by gate 6 to run a mutant);
    when ``None`` the file is read from disk (the baseline run)."""

    def run(self, case: ExecCase, sut_source: Optional[str] = None) -> RunOutcome:
        # 1. Load the SUT (original source, or a mutant), under its real filename.
        if sut_source is None:
            try:
                with open(case.sut_path, encoding="utf-8") as handle:
                    sut_source = handle.read()
            except OSError as exc:
                return RunOutcome(passed=False, setup_error=f"cannot read SUT: {exc}")
        sut_mod = types.ModuleType("sut_under_test")
        sut_mod.__file__ = case.sut_path
        try:
            exec(compile(sut_source, case.sut_path, "exec"), sut_mod.__dict__)
        except Exception as exc:  # a mutant that won't even load → caller treats as a fail
            return RunOutcome(passed=False, setup_error=f"SUT did not load: {exc!r}")

        # 2. Load the test module and find its run(sut) entry point.
        try:
            with open(case.test_path, encoding="utf-8") as handle:
                test_source = handle.read()
            test_mod = types.ModuleType("test_under_eval")
            test_mod.__file__ = case.test_path
            exec(compile(test_source, case.test_path, "exec"), test_mod.__dict__)
        except Exception as exc:
            return RunOutcome(passed=False, setup_error=f"test did not load: {exc!r}")
        run_fn = test_mod.__dict__.get("run")
        if not callable(run_fn):
            return RunOutcome(passed=False,
                              setup_error="test module exposes no callable run(sut)")

        # 3. Run the test, tracing only the SUT file's executed lines.
        covered: Set[int] = set()
        target = case.sut_path

        def tracer(frame, event, arg):
            if frame.f_code.co_filename == target and event == "line":
                covered.add(frame.f_lineno)
            return tracer

        previous = sys.gettrace()
        sys.settrace(tracer)
        try:
            run_fn(sut_mod)
            passed, error = True, None
        except AssertionError:
            passed, error = False, None        # the test noticed — a real failure
        except Exception as exc:               # could not run cleanly — a setup error
            passed, error = False, f"{type(exc).__name__}: {exc}"
        finally:
            sys.settrace(previous)

        return RunOutcome(passed=passed, covered={target: covered}, setup_error=error)
