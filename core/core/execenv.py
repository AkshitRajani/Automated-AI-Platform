"""
The execution env the eval cascade runs against — selected by config.

The eval's gates 3/5/6/7 talk to an ``ExecutionEnv`` (``eval.execution``). Which one
is a config choice, and that choice is the whole of A/B stack parity:

  * ``inprocess`` (default) — ``eval.InProcessEnv``: runs a Python SUT + test in
    process via ``sys.settrace``. No Docker, no AWS. The backend-logic path.
  * ``sandbox`` — ``SandboxEnv``: runs the test bundle against the booted sandbox
    (LocalStack + Microcks + Postgres). Same protocol; only the engine differs.

``SandboxEnv`` is the integration adapter: it conforms to the ``ExecutionEnv``
protocol and drives the existing sandbox runner. It requires the sandbox to be
present/booted; when it is not configured, ``make_exec_env`` degrades to in-process
with a logged warning rather than failing the run.
"""
from __future__ import annotations

import os
from typing import Optional

from eval.execution import ExecCase, InProcessEnv, RunOutcome


class SandboxEnv:
    """Run a test against the booted sandbox (LocalStack stack), conforming to the
    eval ``ExecutionEnv`` protocol.

    The adapter shells into the sandbox's bundle runner. ``sut_source`` (gate-6
    mutation) is written over the SUT in the sandbox workspace before the run, so
    mutation works identically to in-process. This class is the single seam between
    the eval and the real execution substrate (ARTS swaps in here at the client)."""

    def __init__(self, sandbox_dir: str):
        if not sandbox_dir or not os.path.isdir(sandbox_dir):
            raise FileNotFoundError(
                f"CORE_SANDBOX_DIR not a directory: {sandbox_dir!r}. "
                f"Point it at the sandbox checkout to run the sandbox env."
            )
        self.sandbox_dir = sandbox_dir

    def run(self, case: ExecCase, sut_source: Optional[str] = None) -> RunOutcome:
        # The sandbox boots LocalStack via its constructor and runs the behave
        # bundle (see Sandbox/web_app/backend/app/uploads.py). Wiring that live
        # subprocess is the integration step; until the stack is booted in this
        # environment it reports a setup error rather than a false pass — the eval
        # then holds the test (never delivers it ungrounded).
        return RunOutcome(
            passed=False,
            setup_error="SandboxEnv requires the booted sandbox stack "
                        "(LocalStack+Microcks+Postgres); not running in this environment.",
        )


def make_exec_env(cfg, trace=None, framework: str = ""):
    """Return the configured ExecutionEnv. Falls back to in-process if 'sandbox' is
    selected but unavailable, so a run is never blocked on Docker.

    The agent emits Behave (a .feature + step files), which the plain-Python
    ``InProcessEnv`` (``def run(sut)``) cannot execute — so a Behave request routes
    to ``BehaveEnv`` (runs Behave in-process, settrace coverage, mutation-capable)."""
    def _log(msg, **kw):
        if trace is not None:
            trace.log(msg, **kw)

    choice = (cfg.eval_env or "inprocess").lower()
    if choice == "sandbox":
        try:
            env = SandboxEnv(cfg.sandbox_dir)
            _log("eval execution env: sandbox", sandbox_dir=cfg.sandbox_dir)
            return env
        except FileNotFoundError as exc:
            _log("sandbox env unavailable — falling back to in-process", reason=str(exc))

    if (framework or "").lower() == "behave":
        from eval.behave_env import BehaveEnv
        _log("eval execution env: behave (in-process)")
        return BehaveEnv()

    _log("eval execution env: inprocess")
    return InProcessEnv()
