"""Tests for scoring agent boundary gate — no Bedrock required."""
from scoring.agent.boundary import profile_validity_gate
from scoring.agent.schemas import ProfileBatchOut, ScenarioProfileOut


def test_valid_batch_passes_gate():
    batch = ProfileBatchOut(profiles=[
        ScenarioProfileOut(
            scenario_id="a.feature::One",
            workflow_stage="validate",
            intent="negative",
            actions=["validate", "reject"],
        ),
    ])
    gate = profile_validity_gate(batch, {"a.feature::One"})
    assert gate.ok


def test_invalid_action_fails_gate():
    bad = ProfileBatchOut(profiles=[
        ScenarioProfileOut.model_construct(
            scenario_id="a.feature::One",
            workflow_stage="validate",
            intent="negative",
            actions=["not_a_real_action"],
        ),
    ])
    gate = profile_validity_gate(bad, {"a.feature::One"})
    assert not gate.ok
    assert gate.reasons


def test_missing_scenario_fails_gate():
    batch = ProfileBatchOut(profiles=[])
    gate = profile_validity_gate(batch, {"a.feature::One"})
    assert not gate.ok
