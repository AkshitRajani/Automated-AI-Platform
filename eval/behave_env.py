"""
BehaveEnv — an ExecutionEnv that runs a Behave bundle for the executable gates.

The reference ``InProcessEnv`` runs a plain-Python ``def run(sut)`` test. The
coding agent, however, emits **Behave** (a ``.feature`` + ``@given/@when/@then``
step files). This env runs that bundle and:

  * reports ``passed`` = Behave finished with zero failed scenarios;
  * captures **SUT line coverage** via ``sys.settrace`` so gates 3 (calls-real-code)
    and 5 (covers-change) work;
  * honours ``sut_source`` — gate 6 writes a **mutant** of the SUT to disk, runs,
    then restores the original. A real test fails on the mutant; a fake one doesn't.

Each run executes in a **fresh subprocess** (see ``_behave_subprocess.py``). This
is essential, not an optimisation: gate 6 runs the test ~once per mutant, and
gate 7 several times, all within one ``generate`` call. In a single interpreter
the SUT module is cached in ``sys.modules`` after the first run, so a mutated file
on disk is never re-read and every mutant test silently passes (verifies nothing).
A new process per run guarantees the on-disk SUT — mutant or original — is the
code actually executed, the same way mutmut/cosmic-ray isolate runs.

Pure stdlib + Behave (already a dependency). No ``coverage``/``pytest``/``mutmut``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

from .execution import ExecCase, RunOutcome

_BOOTSTRAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_behave_subprocess.py")
_TIMEOUT_S = 120


def _features_dir(test_path: str) -> str:
    """From a step file (…/features/steps/x.py) find the …/features dir to run."""
    d = os.path.dirname(os.path.abspath(test_path))
    if os.path.basename(d) == "steps":
        d = os.path.dirname(d)                  # …/features/steps -> …/features
    return d


class BehaveEnv:
    def run(self, case: ExecCase, sut_source: Optional[str] = None) -> RunOutcome:
        # Mutation override: put the mutant on disk; the fresh subprocess reads it.
        original: Optional[str] = None
        if sut_source is not None:
            try:
                with open(case.sut_path, encoding="utf-8") as fh:
                    original = fh.read()
                with open(case.sut_path, "w", encoding="utf-8") as fh:
                    fh.write(sut_source)
            except OSError as exc:
                return RunOutcome(passed=False, setup_error=f"cannot stage SUT: {exc}")

        try:
            return self._run_behave(case)
        finally:
            if original is not None:                       # restore the real SUT
                try:
                    with open(case.sut_path, "w", encoding="utf-8") as fh:
                        fh.write(original)
                except OSError:
                    pass

    def _run_behave(self, case: ExecCase) -> RunOutcome:
        features = _features_dir(case.test_path)
        if not os.path.isdir(features):
            return RunOutcome(passed=False, setup_error=f"no features dir at {features}")
        workspace_root = os.path.dirname(os.path.abspath(features))

        out_fd, out_path = tempfile.mkstemp(suffix=".json", prefix="behave_out_")
        os.close(out_fd)
        env = dict(os.environ)
        env["PYTHONPATH"] = workspace_root + os.pathsep + env.get("PYTHONPATH", "")

        try:
            proc = subprocess.run(
                [sys.executable, _BOOTSTRAP, features, case.sut_path, out_path],
                cwd=workspace_root, env=env, capture_output=True, text=True,
                timeout=_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            self._cleanup(out_path)
            return RunOutcome(passed=False, covered={case.sut_path: set()},
                              setup_error=f"behave timed out after {_TIMEOUT_S}s")

        try:
            with open(out_path) as fh:
                data = json.load(fh)
        except Exception:
            self._cleanup(out_path)
            return RunOutcome(passed=False, covered={case.sut_path: set()},
                              setup_error="behave did not run: "
                              + (proc.stderr[-400:] or proc.stdout[-400:] or "no output"),
                              output=proc.stdout[-2000:])
        self._cleanup(out_path)

        return RunOutcome(passed=bool(data.get("passed")),
                          covered={case.sut_path: set(data.get("covered", []))},
                          setup_error=data.get("error"),
                          output=proc.stdout[-2000:])

    @staticmethod
    def _cleanup(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
