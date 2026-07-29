"""The incremental emit tools: start_unit / write_section / finish_unit / skip_type,
and the deterministic manifest assembly. Pure — the @tool shim makes them callable."""
import json
import os

from requirement_agent.schemas import CANONICAL_SECTIONS
from requirement_agent.tools.emit import (build_requirement_set, finish_unit, reset_emit,
                                          skip_type, start_unit, write_section)

UNIT = "LambdaHandler:handler_a"


def _write_all_sections(unit=UNIT):
    start_unit(unit, "LambdaHandler", "Handler A")
    for s in CANONICAL_SECTIONS:
        write_section(unit, s, f"content for {s}")


def test_incremental_doc_is_assembled_and_written(tmp_path):
    reset_emit(str(tmp_path), "DEMO")
    skip_type("Function", "internal helpers")
    _write_all_sections()
    msg = finish_unit(UNIT, grounded_identifiers=["s3://bucket/key.csv"])
    assert "Documented" in msg

    rs = build_requirement_set()
    assert rs.app_id == "DEMO"
    assert [e.unit for e in rs.entries] == [UNIT]
    assert rs.entries[0].grounded_identifiers == ["s3://bucket/key.csv"]
    assert [s.entity_type for s in rs.skipped_types] == ["Function"]
    # the JSON doc really landed on disk
    assert os.path.isfile(os.path.join(str(tmp_path), rs.entries[0].doc_file))


def test_finish_rejected_until_all_sections_present(tmp_path):
    reset_emit(str(tmp_path), "DEMO")
    start_unit(UNIT, "LambdaHandler", "Handler A")
    write_section(UNIT, "System Overview", "only one section")
    msg = finish_unit(UNIT, grounded_identifiers=[])
    assert "NOT finished" in msg
    assert build_requirement_set().entries == []     # nothing recorded


def test_write_section_appends(tmp_path):
    reset_emit(str(tmp_path), "DEMO")
    start_unit(UNIT, "LambdaHandler", "Handler A")
    write_section(UNIT, "System Overview", "part one")
    write_section(UNIT, "System Overview", "part two")
    for s in CANONICAL_SECTIONS[1:]:
        write_section(UNIT, s, "x")
    finish_unit(UNIT, grounded_identifiers=[])
    rs = build_requirement_set()
    doc = json.load(open(os.path.join(str(tmp_path), rs.entries[0].doc_file)))
    assert "part one" in doc["sections"]["System Overview"]
    assert "part two" in doc["sections"]["System Overview"]


def test_grounding_is_computed_not_a_fake_score(tmp_path):
    """Provenance is an honest label, confidence is null (not 0.0), and the grounding
    descriptor is computed from the real facts — it varies with what's available."""
    from requirement_agent.facts import AnalyzerFacts
    from requirement_agent.tests.fakes import write_quad
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))

    # no source: descriptor reflects the 2 facts + "no raw source"
    reset_emit(str(tmp_path), "DEMO", facts=facts, source_available=False)
    _write_all_sections()
    finish_unit(UNIT, grounded_identifiers=["s3://bucket/key.csv"])
    doc = json.load(open(os.path.join(str(tmp_path), build_requirement_set().entries[0].doc_file)))
    assert doc["confidence"] is None              # NOT a misleading 0.0
    assert doc["requirement_backed"] is False
    assert doc["provenance"] == "code-derived"
    assert "2 analyzer fact" in doc["grounding"]
    assert "no raw source" in doc["grounding"]

    # with source available: the SAME unit reports a different, honest grounding
    reset_emit(str(tmp_path), "DEMO", facts=facts, source_available=True)
    _write_all_sections()
    finish_unit(UNIT, grounded_identifiers=["s3://bucket/key.csv"])
    doc2 = json.load(open(os.path.join(str(tmp_path), build_requirement_set().entries[0].doc_file)))
    assert "raw source available" in doc2["grounding"]
    assert doc2["grounding"] != doc["grounding"]


def test_reset_clears_previous_run(tmp_path):
    reset_emit(str(tmp_path), "DEMO")
    _write_all_sections()
    finish_unit(UNIT, grounded_identifiers=[])
    reset_emit(str(tmp_path), "DEMO2")
    rs = build_requirement_set()
    assert rs.app_id == "DEMO2"
    assert rs.entries == []
