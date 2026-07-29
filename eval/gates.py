"""
The seven gates as plain functions. Each returns a `GateOutcome` (PASS / FAIL /
SKIP) and, on failure, `Finding`s in the validator's shape so the agent can repair
the exact line. The cascade (cascade.py) runs them cheapest-first and stops at the
first FAIL.

Gates 1, 2, 4 are static (no execution). Gates 3, 5, 6, 7 run the test against the
SUT through an `ExecutionEnv`. Gate 2 lives in grounding.py.
"""
from __future__ import annotations

import ast
from typing import Dict, Optional, Set

from .execution import ExecCase, ExecutionEnv, RunOutcome
from .models import Finding, GateOutcome, GateStatus, Severity
from .mutation import generate_mutants


def _err(rule: str, message: str, suggestion: str = "",
         file: str = "<bundle>", line: int = 0, symbol: str = "") -> Finding:
    return Finding(rule=rule, severity=Severity.ERROR, file=file, line=line,
                   message=message, suggestion=suggestion, symbol=symbol)


# --- gate 1 — Runs (static parse) -------------------------------------------
def gate1_runs(static_report, case: ExecCase) -> GateOutcome:
    """Does it parse and load? Uses the validator's parse pass when step files are
    given; otherwise compiles the SUT and test directly."""
    if static_report is not None:
        broken = [f for f in static_report.findings
                  if f.rule in {"syntax-error", "unreadable-file"}]
        if broken:
            return GateOutcome(1, "Runs", GateStatus.FAIL,
                               "step files do not parse", list(broken))
        return GateOutcome(1, "Runs", GateStatus.PASS,
                           f"{static_report.files_checked} file(s) parse")

    findings = []
    for path in (case.sut_path, case.test_path):
        try:
            with open(path, encoding="utf-8") as handle:
                ast.parse(handle.read(), filename=path)
        except Exception as exc:
            findings.append(_err("syntax-error", f"{path} does not parse: {exc}",
                                 "fix the syntax error before the test can run", file=path))
    if findings:
        return GateOutcome(1, "Runs", GateStatus.FAIL, "does not parse", findings)
    return GateOutcome(1, "Runs", GateStatus.PASS, "SUT and test parse")


# --- gate 4 — Checks a real value (static no-op) ----------------------------
def gate4_real_value(static_report, case: ExecCase) -> GateOutcome:
    """Does it assert a concrete value, or nothing? The validator catches behave
    no-op `then` steps; for the plain-Python path we add a light vacuous-assert
    scan. The *dynamic* fake-pass net is gate 6 — this is only the cheap pre-cut."""
    if static_report is not None:
        noop = [f for f in static_report.findings if f.rule == "no-op-step"]
        if noop:
            return GateOutcome(4, "Checks a real value", GateStatus.FAIL,
                               "a then-step asserts nothing", list(noop))

    try:
        with open(case.test_path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=case.test_path)
    except Exception:
        return GateOutcome(4, "Checks a real value", GateStatus.SKIP,
                           "test did not parse (gate 1 owns that)")

    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    if not asserts:
        return GateOutcome(4, "Checks a real value", GateStatus.FAIL,
                           "the test asserts nothing",
                           [_err("no-assertion",
                                 "the test contains no assert — it passes no matter what",
                                 "assert a concrete expected value", file=case.test_path)])

    def vacuous(node: ast.Assert) -> bool:
        test = node.test
        if isinstance(test, ast.Constant):              # assert True / assert 1
            return True
        if (isinstance(test, ast.Compare)               # assert x is not None
                and len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot)
                and any(isinstance(c, ast.Constant) and c.value is None
                        for c in (test.left, *test.comparators))):
            return True
        return False

    if all(vacuous(a) for a in asserts):
        return GateOutcome(4, "Checks a real value", GateStatus.FAIL,
                           "every assertion is vacuous (assert True / is not None)",
                           [_err("vacuous-assert",
                                 "every assertion is trivially true and checks no concrete value",
                                 "assert the SUT's actual output against an expected value",
                                 file=case.test_path, line=asserts[0].lineno)])
    return GateOutcome(4, "Checks a real value", GateStatus.PASS,
                       f"{len(asserts)} assertion(s)")


# --- gate 3 — Calls the real code (coverage of SUT > 0) ---------------------
def gate3_calls_real(case: ExecCase, baseline: RunOutcome) -> GateOutcome:
    if baseline.setup_error:
        return GateOutcome(3, "Calls the real code", GateStatus.FAIL,
                           f"the test could not run: {baseline.setup_error}",
                           [_err("test-setup-error", baseline.setup_error,
                                 "make the test run cleanly against correct code",
                                 file=case.test_path)])
    covered = baseline.covered.get(case.sut_path, set())
    if covered:
        return GateOutcome(3, "Calls the real code", GateStatus.PASS,
                           f"executed {len(covered)} line(s) of the SUT")
    return GateOutcome(3, "Calls the real code", GateStatus.FAIL,
                       "the test never executed any SUT line",
                       [_err("no-real-invocation",
                             "the test asserts without invoking the code under test",
                             "call the real SUT instead of asserting on in-memory values",
                             file=case.test_path)])


# --- gate 5 — Covers the change (covered ∩ changed) -------------------------
def gate5_covers_change(case: ExecCase, baseline: RunOutcome,
                        changed_lines: Dict[str, Set[int]]) -> GateOutcome:
    changed = set(changed_lines.get(case.sut_path, set()))
    if not changed:
        return GateOutcome(5, "Covers the change", GateStatus.SKIP,
                           "no changed lines supplied for the SUT")
    covered = baseline.covered.get(case.sut_path, set())
    hit = changed & covered
    if hit:
        return GateOutcome(5, "Covers the change", GateStatus.PASS,
                           f"executed {len(hit)}/{len(changed)} changed line(s)",
                           data={"changed": len(changed), "hit": len(hit)})
    return GateOutcome(5, "Covers the change", GateStatus.FAIL,
                       f"none of the {len(changed)} changed line(s) were executed",
                       [_err("change-not-covered",
                             f"the test does not execute the changed lines {sorted(changed)}",
                             "exercise the changed branch / behaviour", file=case.sut_path)])


# --- gate 6 — Catches a planted bug (mutation) ------------------------------
def gate6_planted_bug(case: ExecCase, env: ExecutionEnv,
                      baseline: RunOutcome, max_n: int = 8) -> GateOutcome:
                      #changed_lines: Optional[Set[int]] = None) -> GateOutcome:
    """The load-bearing gate. Baseline must pass on correct code, then the test
    must fail on ≥1 output-sabotage mutant. A test that catches none runs but
    verifies nothing — the 2025 fake-pass class.

    ``changed_lines`` (the SUT's own changed-line set, if any) scopes mutation
    to the function(s) actually under test, so a multi-function file doesn't
    exhaust the mutation budget on unrelated code the test never calls."""
    if not baseline.passed:
        return GateOutcome(6, "Catches a planted bug", GateStatus.FAIL,
                           "the test does not pass on correct code (baseline failed)",
                           [_err("baseline-fail",
                                 "the test fails against unmodified code, so the planted-bug "
                                 "check is meaningless",
                                 "make the test pass on correct code first", file=case.test_path)])
    try:
        with open(case.sut_path, encoding="utf-8") as handle:
            source = handle.read()
    except OSError as exc:
        return GateOutcome(6, "Catches a planted bug", GateStatus.FAIL,
                           f"cannot read SUT to mutate: {exc}", [])

    mutants = generate_mutants(source, case.sut_path, max_n=max_n) #, changed_lines=changed_lines)
    if not mutants:
        return GateOutcome(6, "Catches a planted bug", GateStatus.SKIP,
                           "no output-returning code in the SUT to mutate")

    caught = 0
    for mutant in mutants:
        outcome = env.run(case, sut_source=mutant.source)
        if not outcome.passed:          # the test noticed the sabotaged output
            caught += 1

    data = {"mutants_caught": caught, "mutants_total": len(mutants)}
    if caught >= 1:
        return GateOutcome(6, "Catches a planted bug", GateStatus.PASS,
                           f"caught {caught}/{len(mutants)} planted bug(s)", data=data)
    return GateOutcome(6, "Catches a planted bug", GateStatus.FAIL,
                       f"caught 0/{len(mutants)} planted bugs — runs but verifies nothing",
                       [_err("fake-pass",
                             "sabotaging the SUT output did not fail the test — it checks "
                             "nothing real (the 2025 fake-pass class)",
                             "assert on the SUT's actual output so a wrong output is caught",
                             file=case.test_path)], data=data)


# --- gate 7 — Stable (re-run, same verdict) ---------------------------------
def gate7_stable(case: ExecCase, env: ExecutionEnv,
                 baseline: RunOutcome, runs: int = 3) -> GateOutcome:
    verdicts = {baseline.passed}
    for _ in range(max(0, runs - 1)):
        verdicts.add(env.run(case).passed)
    if len(verdicts) == 1:
        return GateOutcome(7, "Stable", GateStatus.PASS,
                           f"identical verdict across {runs} run(s)")
    return GateOutcome(7, "Stable", GateStatus.FAIL,
                       "verdict changed across identical re-runs (flaky)",
                       [_err("flaky-test",
                             "the test produced different verdicts across identical re-runs",
                             "remove nondeterminism (time, ordering, randomness, shared state)",
                             file=case.test_path)])
