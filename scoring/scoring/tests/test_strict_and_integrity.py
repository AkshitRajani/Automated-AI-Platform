"""Tests for strict matching, scenario outlines, and full requirement extraction."""
from scoring.behavior import BehaviorProfile, behavior_match_score
from scoring.models import Scenario, Step
from scoring.parse import parse_feature_text
from scoring.requirements.extract import extract_items_from_doc
from scoring.requirements.parse import load_requirements
from scoring.requirements.profile import profile_requirements
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
REQUIREMENTS = FIX / "requirements"


def test_strict_matching_rejects_adjacent_stages(monkeypatch):
    from scoring.agent import context

    token = context._strict_matching.set(True)
    try:
        manual = BehaviorProfile(
            feature_file="a.feature",
            feature_name="A",
            scenario="s1",
            workflow_stage="extract",
            intent="positive",
            actions=frozenset({"retrieve"}),
            outcomes=frozenset(),
        )
        generated = BehaviorProfile(
            feature_file="b.feature",
            feature_name="B",
            scenario="s2",
            workflow_stage="transform",
            intent="positive",
            actions=frozenset({"retrieve"}),
            outcomes=frozenset(),
        )
        score, detail = behavior_match_score(manual, generated)
        assert score == 0.0
        assert detail["reason"] == "stage_mismatch"
    finally:
        context._strict_matching.reset(token)


def test_scenario_outline_keeps_examples_attached():
    text = """
Feature: Fees
  Scenario Outline: Apply fee tiers
    Given an account in state <state>
    When the fee job runs
    Then the fee is <fee>

    Examples:
      | state   | fee |
      | overdue | 5%  |
      | current | 0%  |
"""
    scenarios = parse_feature_text(text)
    assert len(scenarios) == 1
    assert scenarios[0].is_outline
    assert scenarios[0].examples_header == ("state", "fee")
    assert len(scenarios[0].outline_examples) == 2
    assert "Examples:" in scenarios[0].examples_block


def test_requirement_extraction_covers_primary_sections():
    docs = load_requirements(REQUIREMENTS)
    items = extract_items_from_doc(docs[0])
    sections = {item.source_section for item in items}
    assert "User Stories" in sections
    assert "Consolidated Requirements" in sections
    assert "Traceability Matrix" not in sections


def test_profile_requirements_regex_includes_more_than_user_stories():
    docs = load_requirements(REQUIREMENTS)
    profiles = profile_requirements(docs)
    assert len(profiles) >= 3
    sections = {p.source_section for p in profiles}
    assert "User Stories" in sections
