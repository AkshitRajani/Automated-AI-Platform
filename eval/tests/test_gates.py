"""Per-gate logic, isolated with fakes — plus the validator-reuse path (gates 1, 4)."""
import os

from eval import gates
from eval.execution import ExecCase, RunOutcome
from eval.grounding import check_grounding
from eval.models import GateStatus
from eval.tests.fakes import FakeEnv, FakeResolver, covered

SUT = "x.py"
CASE = ExecCase(sut_path=SUT, test_path="t.py")
_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


# --- gate 2 (grounding) -----------------------------------------------------
def test_grounding_confirms_and_rejects():
    r = FakeResolver(["real_helper"])
    assert check_grounding([("real_helper", "helper")], "APP", r).status is GateStatus.PASS
    assert check_grounding([("invented", "helper")], "APP", r).status is GateStatus.FAIL


def test_grounding_skips_without_resolver():
    assert check_grounding([("x", "helper")], "APP", None).status is GateStatus.SKIP


# --- gate 3 (calls real code) ----------------------------------------------
def test_gate3_passes_when_sut_covered():
    base = RunOutcome(passed=True, covered=covered(SUT, {1, 2}))
    assert gates.gate3_calls_real(CASE, base).status is GateStatus.PASS


def test_gate3_fails_when_nothing_covered():
    base = RunOutcome(passed=True, covered=covered(SUT, set()))
    assert gates.gate3_calls_real(CASE, base).status is GateStatus.FAIL


def test_gate3_fails_on_setup_error():
    base = RunOutcome(passed=False, setup_error="boom")
    assert gates.gate3_calls_real(CASE, base).status is GateStatus.FAIL


# --- gate 5 (covers the change) --------------------------------------------
def test_gate5_intersects_changed_lines():
    base = RunOutcome(passed=True, covered=covered(SUT, {2, 3}))
    assert gates.gate5_covers_change(CASE, base, {SUT: {3}}).status is GateStatus.PASS
    assert gates.gate5_covers_change(CASE, base, {SUT: {9}}).status is GateStatus.FAIL
    assert gates.gate5_covers_change(CASE, base, {}).status is GateStatus.SKIP


# --- gate 6 (planted bug) ---------------------------------------------------
def test_gate6_fails_when_no_mutant_caught(tmp_path):
    sut = tmp_path / "x.py"
    sut.write_text("def f():\n    return 1\n")
    case = ExecCase(sut_path=str(sut), test_path="t.py")
    base = RunOutcome(passed=True, covered=covered(str(sut), {2}))
    env = FakeEnv(base, mutant_passed=True)          # test never notices a mutant
    assert gates.gate6_planted_bug(case, env, base).status is GateStatus.FAIL


def test_gate6_passes_when_a_mutant_caught(tmp_path):
    sut = tmp_path / "x.py"
    sut.write_text("def f():\n    return 1\n")
    case = ExecCase(sut_path=str(sut), test_path="t.py")
    base = RunOutcome(passed=True, covered=covered(str(sut), {2}))
    env = FakeEnv(base, mutant_passed=False)         # test fails on the mutant → caught
    assert gates.gate6_planted_bug(case, env, base).status is GateStatus.PASS


def test_gate6_fails_when_baseline_fails():
    base = RunOutcome(passed=False, covered=covered(SUT, {1}))
    env = FakeEnv(base)
    assert gates.gate6_planted_bug(CASE, env, base).status is GateStatus.FAIL


# --- gates 1 & 4 reuse the validator (static layer) ------------------------
def test_gate1_uses_validator_on_syntax_error():
    from validator.runner import validate
    report = validate(os.path.join(_FIX, "behave_syntax"))
    assert gates.gate1_runs(report, CASE).status is GateStatus.FAIL


def test_gate4_uses_validator_on_noop_step():
    from validator.runner import validate
    report = validate(os.path.join(_FIX, "behave_noop"))
    assert gates.gate4_real_value(report, CASE).status is GateStatus.FAIL
