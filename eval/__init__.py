"""
Eval — the deterministic gate cascade (Component 3).

The eval is `validator` (the static layer) + the execution layer + the
orchestrator. It produces one bit — **deliver** or **repair/discard** — never a
score. Public surface:

    from eval import evaluate, EvalContext, ExecCase, InProcessEnv, Verdict

    ctx = EvalContext(app_id="DEMO", case=ExecCase(sut, test),
                      changed_lines={sut: {12, 13}})
    verdict = evaluate(ctx)              # InProcessEnv by default
    if verdict.deliver: ...
"""
from __future__ import annotations

from .cascade import evaluate
from .context import EvalContext
from .execution import ExecCase, ExecutionEnv, InProcessEnv, RunOutcome
from .grounding import Resolver
from .models import Finding, GateOutcome, GateStatus, Severity, Verdict

__all__ = [
    "evaluate",
    "EvalContext",
    "ExecCase",
    "ExecutionEnv",
    "InProcessEnv",
    "RunOutcome",
    "Resolver",
    "Verdict",
    "GateOutcome",
    "GateStatus",
    "Finding",
    "Severity",
]
