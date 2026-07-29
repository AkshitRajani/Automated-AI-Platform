"""
Tests for the requirements writer.

The pure layer (RequirementRow.from_doc, load_requirement_docs) needs no DB driver and
always runs. The DB-write path uses psycopg2.extras, so its test skips cleanly when the
driver isn't installed — without weakening what it asserts (idempotent delete-then-insert).
"""
from __future__ import annotations

import json
import os

import pytest

from ingestion.writers.requirements_writer import (RequirementRow, RequirementsWriter,
                                                   load_requirement_docs)


# A realistic requirement-agent doc (the requirement agent's per-unit JSON shape).
def _doc(unit="WorkflowFile:alf_klc.yml", backed=False, confidence=None):
    return {
        "unit": unit,
        "unit_type": "WorkflowFile",
        "title": "ALF KLC Calculation Workflow",
        "provenance": "jira:ABC-1" if backed else "code-derived",
        "requirement_backed": backed,
        "confidence": confidence,
        "grounding": "grounded in 11 analyzer fact(s); no raw source",
        "grounded_identifiers": ["DatabaseTable:${LN_GFEE}", "DatabaseTable:${BK_SCORED}"],
        "sections": {"System Overview": "Calculates KLC.", "Gap Analysis": "..."},
    }


# --- pure layer: RequirementRow.from_doc ------------------------------------

def test_from_doc_maps_fields_and_keeps_confidence_none():
    r = RequirementRow.from_doc(_doc())
    assert r.unit == "WorkflowFile:alf_klc.yml"
    assert r.unit_type == "WorkflowFile"
    assert r.provenance == "code-derived"
    assert r.requirement_backed is False
    assert r.confidence is None                       # NULL kept, never coerced to 0.0
    assert r.grounded_identifiers == ["DatabaseTable:${LN_GFEE}", "DatabaseTable:${BK_SCORED}"]
    assert r.sections["System Overview"] == "Calculates KLC."
    assert len(r.source_hash) == 64                   # sha256 hex


def test_from_doc_backed_preserves_confidence():
    r = RequirementRow.from_doc(_doc(backed=True, confidence=0.9))
    assert r.requirement_backed is True
    assert r.confidence == 0.9


def test_from_doc_source_hash_is_deterministic_and_content_sensitive():
    a = RequirementRow.from_doc(_doc())
    b = RequirementRow.from_doc(_doc())
    c = RequirementRow.from_doc(_doc(unit="WorkflowFile:other.yml"))
    assert a.source_hash == b.source_hash             # same content → same hash
    assert a.source_hash != c.source_hash             # different content → different hash


def test_from_doc_requires_unit():
    with pytest.raises(ValueError):
        RequirementRow.from_doc({"unit_type": "WorkflowFile"})   # no 'unit'


# --- pure layer: load_requirement_docs --------------------------------------

def test_load_reads_nested_requirements_dir_sorted(tmp_path):
    req = tmp_path / "requirements"
    req.mkdir()
    (req / "b_unit.json").write_text(json.dumps(_doc(unit="WorkflowFile:b.yml")))
    (req / "a_unit.json").write_text(json.dumps(_doc(unit="WorkflowFile:a.yml")))
    rows = load_requirement_docs(str(tmp_path))           # points at the workspace root
    assert [r.unit for r in rows] == ["WorkflowFile:a.yml", "WorkflowFile:b.yml"]  # sorted


def test_load_accepts_folder_of_docs_directly(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps(_doc(unit="WorkflowFile:x.yml")))
    rows = load_requirement_docs(str(tmp_path))           # no nested requirements/ subdir
    assert [r.unit for r in rows] == ["WorkflowFile:x.yml"]


def test_load_skips_malformed_without_failing(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(_doc(unit="WorkflowFile:good.yml")))
    (tmp_path / "bad.json").write_text("{ not valid json")
    (tmp_path / "no_unit.json").write_text(json.dumps({"title": "no unit id"}))
    (tmp_path / "note.txt").write_text("ignored — not .json")
    rows = load_requirement_docs(str(tmp_path))
    assert [r.unit for r in rows] == ["WorkflowFile:good.yml"]   # only the valid doc


def test_load_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_requirement_docs(str(tmp_path / "does_not_exist"))


# --- DB write path: idempotent delete-then-insert ---------------------------

class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("execute", sql, params))

    def mogrify(self, sql, params=None):                # used by psycopg2.extras.execute_batch
        self.log.append(("mogrify", sql, params))
        return b"INSERT"


class _FakeConn:
    def __init__(self):
        self.log: list = []
        self.autocommit = None
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self.log)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_write_deletes_app_rows_then_inserts_each():
    pytest.importorskip("psycopg2")                     # the write path uses psycopg2.extras
    conn = _FakeConn()
    writer = RequirementsWriter(conn=conn)
    rows = [RequirementRow.from_doc(_doc(unit="WorkflowFile:a.yml")),
            RequirementRow.from_doc(_doc(unit="WorkflowFile:b.yml"))]
    n = writer.write_requirements("DCFO", rows, code_version="v1")

    assert n == 2
    assert conn.commits == 1
    # first DB op is the per-app DELETE (idempotency), scoped by app_id
    first = conn.log[0]
    assert first[0] == "execute" and "DELETE FROM app_requirements" in first[1]
    assert first[2] == ("DCFO",)
    # each row is inserted (execute_batch mogrifies once per row)
    mogrifies = [e for e in conn.log if e[0] == "mogrify"]
    assert len(mogrifies) == 2


def test_write_empty_still_clears_the_app():
    pytest.importorskip("psycopg2")
    conn = _FakeConn()
    n = RequirementsWriter(conn=conn).write_requirements("DCFO", [])
    assert n == 0
    assert conn.commits == 1
    assert any(e[0] == "execute" and "DELETE FROM app_requirements" in e[1] for e in conn.log)


def test_write_requires_app_id():
    conn = _FakeConn()
    with pytest.raises(ValueError):
        RequirementsWriter(conn=conn).write_requirements("", [])


# --- HITL additions: section provenance passthrough + single-unit upsert ------

def test_from_doc_maps_section_provenance():
    d = _doc()
    d["section_provenance"] = {"Output Specification": "human-confirmed"}
    r = RequirementRow.from_doc(d)
    assert r.section_provenance == {"Output Specification": "human-confirmed"}
    assert RequirementRow.from_doc(_doc()).section_provenance == {}   # absent -> empty, never invented


def test_write_upsert_mode_never_deletes():
    """replace=False is the single-unit rerun path: the app's other docs must survive."""
    pytest.importorskip("psycopg2")
    conn = _FakeConn()
    writer = RequirementsWriter(conn=conn)
    n = writer.write_requirements("DCFO", [RequirementRow.from_doc(_doc())], replace=False)
    assert n == 1
    assert not any("DELETE" in str(e[1]) for e in conn.log)
    assert conn.commits == 1


def test_insert_carries_section_provenance_column():
    pytest.importorskip("psycopg2")
    conn = _FakeConn()
    RequirementsWriter(conn=conn).write_requirements("DCFO", [RequirementRow.from_doc(_doc())])
    mogrifies = [e for e in conn.log if e[0] == "mogrify"]
    assert mogrifies and "section_provenance" in mogrifies[0][1]
