"""Tests for requirement parsing and 3-input scoring."""
from pathlib import Path

import pytest

from scoring import score
from scoring.requirements.parse import load_requirements
from scoring.requirements.profile import profile_requirements

FIX = Path(__file__).parent / "fixtures"
GOLDEN = FIX / "golden"
GENERATED = FIX / "generated"
REQUIREMENTS = FIX / "requirements"


def test_load_requirement_json():
    docs = load_requirements(REQUIREMENTS)
    assert len(docs) >= 1
    assert docs[0]["unit"] == "WorkflowFile:late_fee_job"


def test_profile_extracts_user_story_acs():
    docs = load_requirements(REQUIREMENTS)
    profiles = profile_requirements(docs)
    assert len(profiles) >= 3
    labels = {p.ac_label for p in profiles}
    assert any("AC-1" in label for label in labels)
    negative = [p for p in profiles if p.negative_path]
    assert negative


def test_three_input_scoring_mode():
    report = score(
        golden=GOLDEN,
        generated=GENERATED,
        requirements=REQUIREMENTS,
        threshold=0.45,
    )
    assert report.has_requirements
    assert report.requirement_acs > 0
    assert report.breakdown.scoring_mode == "golden_first_manual_requirements_regex"
    assert report.breakdown.requirement_ac_coverage_pct >= 0
    assert report.breakdown.triangulation_pct >= 0
    assert report.unit_traceability


def test_manual_only_still_works():
    report = score(golden=GOLDEN, generated=GENERATED, threshold=0.45)
    assert not report.has_requirements
    assert report.breakdown.scoring_mode == "golden_first_manual_only_regex"
    assert report.breakdown.requirement_ac_coverage_pct == 0.0


def test_html_includes_requirement_sections():
    from scoring.html_report import render_html

    report = score(
        golden=GOLDEN,
        generated=GENERATED,
        requirements=REQUIREMENTS,
        threshold=0.45,
    )
    html_out = render_html(report)
    assert "Requirement AC recall?" in html_out
    assert "Matches manual AND requirement?" in html_out
    assert "Requirement alignments" in html_out
    assert "Match threshold" in html_out
    assert "golden_first_manual_requirements" in html_out or "0.45" in html_out

def test_report_json_has_requirement_fields():
    report = score(
        golden=GOLDEN,
        generated=GENERATED,
        requirements=REQUIREMENTS,
        threshold=0.45,
    )
    data = report.to_dict()
    assert data["has_requirements"] is True
    assert "generated_requirement_matches" in data["detailed"]
    assert "generated_alignment" in data["detailed"]
    assert "triangulation" in data["detailed"]
    assert "unit_traceability" in data["detailed"]
