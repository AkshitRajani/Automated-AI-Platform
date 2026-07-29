"""End-to-end cascade on the worked examples, through the real InProcessEnv."""
import os

from eval import EvalContext, ExecCase, InProcessEnv, evaluate
from eval.tests.fakes import FakeResolver

_EX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "discount")
SUT = os.path.join(_EX, "sut.py")
MEMBER_RETURN_LINE = 6   # `return round(total * 0.9, 2)` in sut.py


def _ctx(test_name, **kw):
    return EvalContext(
        app_id="DEMO",
        case=ExecCase(sut_path=SUT, test_path=os.path.join(_EX, test_name)),
        changed_lines={SUT: {MEMBER_RETURN_LINE}},
        **kw,
    )


def test_good_test_is_delivered():
    verdict = evaluate(_ctx("test_good.py"), env=InProcessEnv())
    assert verdict.deliver is True
    assert verdict.failed_gate is None
    assert verdict.evidence["mutants_caught"] >= 1


def test_fake_pass_dies_at_gate_6():
    verdict = evaluate(_ctx("test_fake.py"), env=InProcessEnv())
    assert verdict.deliver is False
    assert verdict.failed_gate == 6           # passed 1–5, caught no planted bug
    assert any(f.rule == "fake-pass" for f in verdict.repair_findings)


def test_grounding_failure_short_circuits_before_execution():
    ctx = _ctx("test_good.py", identifiers=[("invented_helper", "helper")])
    verdict = evaluate(ctx, env=InProcessEnv(), resolver=FakeResolver(["apply_discount"]))
    assert verdict.deliver is False
    assert verdict.failed_gate == 2
    # gates after 2 never ran (cheapest-first short-circuit)
    assert [g.number for g in verdict.gates] == [1, 2]
