"""The three deterministic gates: grounding, doc-validity, coverage. Pure — no Strands."""
import json
import os

from requirement_agent.boundary import (coverage_gap, doc_validity_gate,
                                        grounding_gate)
from requirement_agent.facts import AnalyzerFacts
from requirement_agent.schemas import RequirementEntry, RequirementSet, SkippedType
from requirement_agent.tests.fakes import write_doc, write_quad


def _good_set(doc_rel: str) -> RequirementSet:
    """handler documented (real grounded name), endpoint individually skipped,
    Function type declared not-a-unit → fully accounted, fully grounded."""
    return RequirementSet(
        app_id="DEMO",
        entries=[
            RequirementEntry(
                unit="LambdaHandler:handler_a", unit_type="LambdaHandler",
                status="documented", doc_file=doc_rel,
                grounded_identifiers=["s3://bucket/key.csv"]),
            RequirementEntry(unit="APIEndpoint:GET /x", status="skipped",
                             reason="covered by the handler journey"),
        ],
        skipped_types=[SkippedType(entity_type="Function", reason="internal helpers")],
    )


def test_all_gates_pass_on_a_good_set(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    rs = _good_set(write_doc(tmp_path))
    assert grounding_gate(rs, facts).ok
    assert doc_validity_gate(rs, str(tmp_path)).ok
    assert coverage_gap(facts, rs) == []


def test_grounding_gate_rejects_invented_name(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    rs = _good_set(write_doc(tmp_path))
    rs.entries[0].grounded_identifiers.append("s3://nope/invented.csv")
    res = grounding_gate(rs, facts)
    assert not res.ok
    assert "s3://nope/invented.csv" in res.rejected


def test_doc_validity_gate_rejects_missing_file(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    rs = _good_set(write_doc(tmp_path))
    rs.entries[0].doc_file = "requirements/does_not_exist.json"
    res = doc_validity_gate(rs, str(tmp_path))
    assert not res.ok
    assert "LambdaHandler:handler_a" in res.rejected


def test_doc_validity_gate_rejects_missing_section(tmp_path):
    """A doc that drops a canonical section is rejected with that section named."""
    from requirement_agent.tests.fakes import make_doc
    doc = make_doc()
    doc.sections.pop("Gap Analysis")               # remove one canonical section
    rel = os.path.join("requirements", "handler_a.json")
    full = os.path.join(str(tmp_path), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        json.dump(doc.model_dump(), fh)
    rs = _good_set(rel)
    res = doc_validity_gate(rs, str(tmp_path))
    assert not res.ok
    assert any("Gap Analysis" in r for r in res.reasons)


def test_coverage_gap_flags_forgotten_unit(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    rs = _good_set(write_doc(tmp_path))
    # drop the endpoint entry and don't skip its type → it becomes an uncovered gap
    rs.entries = [rs.entries[0]]
    assert coverage_gap(facts, rs) == ["APIEndpoint:GET /x"]
