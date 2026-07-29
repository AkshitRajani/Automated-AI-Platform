"""
The orchestrator — run the seven gates cheapest-first and stop at the first FAIL.
The whole output is one bit (`deliver`) plus the per-gate trail. There is no step
after gate 7: no score, no weighting, no model.

This is the single entry point the coding agent's `boundary.py` calls at the slot
its docstring reserves for "the external Eval." Same engine for the CLI handover.

Order is by *cost*, not by gate number: the static gates (1, 2, 4) run before the
single baseline execution, then the execution gates (3, 5, 6, 7). Gate 4 (static
no-op) is therefore checked before gate 3 (which must run the test) — cheapest
first, exactly as the design prescribes.
"""
from __future__ import annotations

from typing import List, Optional

from . import gates
from .context import EvalContext
from .execution import ExecutionEnv, InProcessEnv
from .grounding import Resolver, check_grounding
from .models import GateOutcome, GateStatus, Verdict


def evaluate(ctx: EvalContext,
             env: Optional[ExecutionEnv] = None,
             resolver: Optional[Resolver] = None) -> Verdict:
    env = env or InProcessEnv()
    trail: List[GateOutcome] = []

    def step(outcome: GateOutcome) -> bool:
        """Record the gate; return True if the cascade should stop here."""
        trail.append(outcome)
        return outcome.status is GateStatus.FAIL

    # --- static layer (one validator pass, reused by gates 1 and 4) ---------
    static_report = None
    if ctx.steps_root:
        from validator.runner import validate
        static_report = validate(ctx.steps_root,
                                 external_boundaries=ctx.external_boundaries)

    if step(gates.gate1_runs(static_report, ctx.case)):
        return Verdict(deliver=False, gates=trail, failed_gate=1)
    if step(check_grounding(ctx.identifiers, ctx.app_id, resolver)):
        return Verdict(deliver=False, gates=trail, failed_gate=2)
    if step(gates.gate4_real_value(static_report, ctx.case)):
        return Verdict(deliver=False, gates=trail, failed_gate=4)

    # --- one baseline run, shared by the execution gates --------------------
    baseline = env.run(ctx.case)

    if step(gates.gate3_calls_real(ctx.case, baseline)):
        return Verdict(deliver=False, gates=trail, failed_gate=3)
    if step(gates.gate5_covers_change(ctx.case, baseline, ctx.changed_lines)):
        return Verdict(deliver=False, gates=trail, failed_gate=5)
    #sut_changed = ctx.changed_lines.get(ctx.case.sut_path, set())
    if step(gates.gate6_planted_bug(ctx.case, env, baseline, ctx.mutation_max)): #sut_changed
        return Verdict(deliver=False, gates=trail, failed_gate=6)
    if step(gates.gate7_stable(ctx.case, env, baseline, ctx.stability_runs)):
        return Verdict(deliver=False, gates=trail, failed_gate=7)

    # Delivered. Evidence is a raw count of facts (for Pareto ordering among
    # survivors), never a grade.
    caught = next((g.data.get("mutants_caught", 0)
                   for g in trail if g.number == 6), 0)
    covered = len(baseline.covered.get(ctx.case.sut_path, set()))
    return Verdict(deliver=True, gates=trail, failed_gate=None,
                   evidence={"mutants_caught": caught, "lines_covered": covered})
