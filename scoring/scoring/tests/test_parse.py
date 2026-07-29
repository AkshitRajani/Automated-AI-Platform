"""Gherkin parser tests."""
from pathlib import Path

from scoring.parse import load_features, parse_feature_text

FIX = Path(__file__).parent / "fixtures" / "golden"


def test_parse_feature_file_extracts_scenarios_and_steps():
    scenarios = load_features(FIX / "late_fees.feature")
    assert len(scenarios) == 3
    names = {s.name for s in scenarios}
    assert "Late fee when payment is overdue" in names
    assert "No late fee within grace period" in names
    assert "Fee waived for admin override" in names


def test_background_steps_prepended_to_scenarios():
    text = """
Feature: Discounts
  Background:
    Given a logged-in member
  Scenario: Member discount
    When checkout runs
    Then a 10 percent discount applies
"""
    scenarios = parse_feature_text(text)
    assert len(scenarios) == 1
    assert scenarios[0].steps[0].keyword == "Given"
    assert scenarios[0].steps[0].text == "a logged-in member"
    assert scenarios[0].steps[-1].text == "a 10 percent discount applies"


def test_tags_parsed():
    scenarios = load_features(FIX / "late_fees.feature")
    tagged = next(s for s in scenarios if s.name == "Late fee when payment is overdue")
    assert tagged.tags == ("regression",)
