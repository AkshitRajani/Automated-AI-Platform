"""Tests for tiered requirement extraction aligned with requirement agent contract."""
from pathlib import Path

from scoring.requirements.contract import CANONICAL_SECTIONS, extraction_tier, section_key
from scoring.requirements.extract import ExtractionReport, extract_items_from_doc
from scoring.requirements.parse import load_requirements

FIX = Path(__file__).parent / "fixtures"
REQUIREMENTS = FIX / "requirements"
DEMO = Path(__file__).resolve().parents[3] / "demo_requirements"


def test_canonical_sections_match_requirement_agent():
    assert len(CANONICAL_SECTIONS) == 9
    assert section_key("6. User Stories") == section_key("User Stories")


def test_metadata_sections_skipped_in_extraction():
    docs = load_requirements(REQUIREMENTS)
    report = ExtractionReport()
    items = extract_items_from_doc(docs[0], report=report)
    sections = {i.source_section for i in items}
    assert "Traceability Matrix" not in sections
    assert "Confidence Mapping" not in sections
    assert report.sections_skipped_metadata >= 2
    assert any(i.source_section == "User Stories" for i in items)


def test_tier_primary_requires_given_when_then():
    docs = load_requirements(REQUIREMENTS)
    items = extract_items_from_doc(docs[0])
    story_items = [i for i in items if i.source_section == "User Stories"]
    assert story_items
    for item in story_items:
        low = item.verbatim_text.lower()
        assert "given" in low and "when" in low and "then" in low


def test_large_demo_docs_exist_and_use_compact_tier():
    if not DEMO.is_dir():
        return
    large = list(DEMO.glob("enterprise_*.md"))
    if not large:
        return
    from scoring.requirements.agent_profile import _doc_needs_compact
    from scoring.requirements.extract import (
        doc_line_count,
        extract_items_for_agent,
        extract_items_from_doc,
    )
    from scoring.requirements.parse import _load_md_doc

    doc = _load_md_doc(large[0])
    assert doc_line_count(doc) > 150
    assert _doc_needs_compact(doc)
    full = len(extract_items_from_doc(doc))
    compact = len(extract_items_for_agent(doc))
    assert compact < full
    assert compact > 0


def test_story_aggregation_combines_acs():
    docs = load_requirements(REQUIREMENTS)
    per_ac = extract_items_from_doc(docs[0], aggregate_stories=False)
    aggregated = extract_items_from_doc(docs[0], aggregate_stories=True)
    story_per_ac = [i for i in per_ac if i.source_section == "User Stories"]
    story_agg = [i for i in aggregated if i.source_section == "User Stories"]
    assert len(story_agg) <= len(story_per_ac)
    for item in story_agg:
        low = item.verbatim_text.lower()
        assert "given" in low and "when" in low and "then" in low
