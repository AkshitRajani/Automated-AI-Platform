"""Behaviour extraction tests."""
from scoring.behavior import detect_actions, detect_intent, detect_stage, profile_scenario
from scoring.models import Scenario, Step


def test_detect_validate_and_reject_actions():
    text = "Stop the workflow when validation fails and records are rejected"
    actions = detect_actions(text)
    assert "validate" in actions
    assert "reject" in actions


def test_detect_positive_vs_negative_intent():
    pos = detect_intent(
        "Successfully validate prepared import data",
        [Step("Then", "all validation checks should pass")],
    )
    neg = detect_intent(
        "Reject an empty import dataset",
        [Step("Then", "the import process should not continue")],
    )
    assert pos == "positive"
    assert neg == "negative"


def test_profile_extracts_stage_and_actions():
    scenario = Scenario(
        feature_file="validate_import_data.feature",
        feature_name="Validate Import Data",
        name="Reject an empty import dataset",
        steps=(
            Step("Given", "the prepared dataset contains no business records"),
            Step("When", "the validation process starts"),
            Step("Then", "the import process should not continue"),
        ),
    )
    profile = profile_scenario(scenario)
    assert profile.workflow_stage == "validate"
    assert profile.intent == "negative"
    assert "validate" in profile.actions
    assert "reject" in profile.actions
