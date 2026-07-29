"""End-to-end behaviour scoring tests."""
from pathlib import Path

import pytest

from scoring import score

FIX = Path(__file__).parent / "fixtures"
GOLDEN = FIX / "golden"
GENERATED = FIX / "generated"


def test_perfect_match_scores_high():
    report = score(golden=GOLDEN, generated=GOLDEN, threshold=0.45)
    assert report.matched_behaviors == 3
    assert report.breakdown.behavior_coverage_pct == 100.0
    assert report.breakdown.overall_score >= 90.0
    assert report.breakdown.explanation


def test_partial_suite_reports_missing_behaviours():
    report = score(golden=GOLDEN, generated=GENERATED, threshold=0.45)
    assert report.manual_scenarios == 3
    assert report.generated_scenarios == 3
    assert 0 < report.matched_behaviors < 3
    assert report.missing_behaviors
    assert report.extra_behaviors
    for row in report.missing_behaviors:
        if row.best_near_match and row.best_near_match > 0:
            assert row.nearest_scenario
            assert row.side == "manual"
    for row in report.extra_behaviors:
        if row.best_near_match and row.best_near_match > 0:
            assert row.nearest_scenario
            assert row.side == "generated"
    assert report.breakdown.explanation
    assert "overall" in report.breakdown.explanation[0].lower()


def test_empty_generated_yields_zero_coverage():
    report = score(golden=GOLDEN, generated=[], threshold=0.45)
    assert report.matched_behaviors == 0
    assert report.breakdown.behavior_coverage_pct == 0.0


def test_html_report_renders():
    from scoring.html_report import render_html

    report = score(golden=GOLDEN, generated=GENERATED, threshold=0.45)
    html_out = render_html(report)
    assert "<!DOCTYPE html>" in html_out
    assert "Manual coverage" in html_out
    assert "Suite precision" in html_out
    assert "At a glance" in html_out
    assert "Best generated alignments" in html_out
    assert "Nearest manual" in html_out
    assert str(int(report.breakdown.overall_score)) in html_out

def test_report_has_simplified_and_detailed_sections():
    report = score(golden=GOLDEN, generated=GENERATED, threshold=0.45)
    data = report.to_dict()
    assert "simplified" in data
    assert "detailed" in data
    assert "summary" in data["simplified"]
    assert "overall_score_pct" in data["simplified"]
    assert "verdict" in data["simplified"]
    assert "matched" in data["detailed"]
    assert "scoring_weights" in data["detailed"]
    assert "method" in data["detailed"]
