"""Unit tests for the Postgres fact backend (KBClient) — no live DB."""
from __future__ import annotations

from coding_agent.kb.facts import KBClient
from coding_agent.tests.fakes import FakeConn


def test_exact_hit_on_table():
    # app_tables columns selected: table_token, kind, resolved, confidence
    conn = FakeConn({
        "app_tables": {
            "exact": [("APP_PMT_AMT", "read", True, 0.99)],
            "like": [],
        },
    })
    res = KBClient(conn).resolve("APP_PMT_AMT", kind="table", app_id="DEMO")
    assert res.note is None
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c.canonical_name == "APP_PMT_AMT"
    assert c.kind == "table"
    assert c.resolved is True
    assert c.confidence == 0.99
    assert c.provenance == "app_tables@DEMO"


def test_fuzzy_fallback_sets_note():
    conn = FakeConn({
        "app_tables": {
            "exact": [],
            "like": [("APP_PMT_AMT", "read", True, 0.8)],
        },
    })
    res = KBClient(conn).resolve("pmt", kind="table", app_id="DEMO")
    assert res.candidates and res.candidates[0].canonical_name == "APP_PMT_AMT"
    assert "no exact match" in res.note


def test_not_found_is_actionable():
    conn = FakeConn({"app_tables": {"exact": [], "like": []}})
    res = KBClient(conn).resolve("does_not_exist", kind="table", app_id="DEMO")
    assert res.candidates == []
    assert "not found" in res.note
    assert "do not invent" in res.note


def test_unsupported_kind_flags_gap():
    conn = FakeConn({})
    res = KBClient(conn).resolve("monthly_payment", kind="column", app_id="DEMO")
    assert res.candidates == []
    assert "not yet in the KB" in res.note


def test_missing_app_id_refuses():
    conn = FakeConn({})
    res = KBClient(conn).resolve("anything", kind="table", app_id="")
    assert res.candidates == []
    assert "app_id is required" in res.note


def test_unresolved_token_marked():
    conn = FakeConn({
        "app_s3_paths": {
            "exact": [("${log_path}", "read", False, 0.7)],  # path, kind, resolved, confidence
            "like": [],
        },
    })
    res = KBClient(conn).resolve("${log_path}", kind="s3_path", app_id="DEMO")
    assert res.candidates[0].resolved is False


def test_helper_lookup_has_no_resolved_or_confidence_columns():
    # app_functions: symbol, entity_type, language, file_path  (no resolved/confidence)
    conn = FakeConn({
        "app_functions": {
            "exact": [("execute_lambda", "function", "python", "utils/aws.py")],
            "like": [],
        },
    })
    res = KBClient(conn).resolve("execute_lambda", kind="helper", app_id="DEMO")
    c = res.candidates[0]
    assert c.canonical_name == "execute_lambda"
    assert c.resolved is True        # defaulted True when column absent
    assert c.confidence == 1.0       # exact, no confidence column

def test_any_kind_searches_multiple_tables():
    conn = FakeConn({
        "app_endpoints": {"exact": [("/fees/late", "POST", True, 0.9)], "like": []},
        "app_tables": {"exact": [], "like": []},
    })
    res = KBClient(conn).resolve("/fees/late", kind="any", app_id="DEMO")
    assert any(c.canonical_name == "/fees/late" for c in res.candidates)


def test_sql_is_parameterized_never_interpolated():
    conn = FakeConn({"app_tables": {"exact": [], "like": []}})
    KBClient(conn).resolve("'; DROP TABLE app_tables; --", kind="table", app_id="DEMO")
    for sql, params in conn.log:
        assert "DROP TABLE app_tables; --" not in sql  # value stays in params, not SQL
        assert "%s" in sql
        assert "DEMO" in params


# --- kb_requirements: the behaviour lookup (app_requirements) ----------------

# app_requirements SELECT order: unit_type, title, provenance, requirement_backed,
# confidence, grounding, grounded_identifiers, sections, section_provenance
def _req_row(unit_type="WorkflowFile", title="ALF KLC", provenance="code-derived",
             backed=False, confidence=None, grounding="grounded in 11 fact(s)",
             grounded=None, sections=None, section_provenance=None):
    return (unit_type, title, provenance, backed, confidence, grounding,
            grounded if grounded is not None else ["DatabaseTable:${X}"],
            sections if sections is not None else {"System Overview": "does X"},
            section_provenance if section_provenance is not None else {})


def test_requirements_found_returns_contract_with_code_derived_note():
    conn = FakeConn({"app_requirements": {"exact": [_req_row()], "like": []}})
    res = KBClient(conn).requirements("DCFO", "WorkflowFile:alf.yml")
    assert res.found is True
    assert res.unit_type == "WorkflowFile"
    assert res.requirement_backed is False
    assert res.confidence is None                       # NULL kept as None, never a fake 0.0
    assert res.grounded_identifiers == ["DatabaseTable:${X}"]
    assert res.sections["System Overview"] == "does X"
    assert "@needs-requirement" in res.note             # code-derived = context, not oracle


def test_requirements_backed_note_is_oracle():
    conn = FakeConn({"app_requirements": {"exact": [
        _req_row(unit_type="LambdaHandler", provenance="jira:ABC-1",
                 backed=True, confidence=0.9)], "like": []}})
    res = KBClient(conn).requirements("DCFO", "LambdaHandler:h")
    assert res.requirement_backed is True
    assert res.confidence == 0.9
    assert "oracle" in res.note.lower()


def test_requirements_not_found_is_actionable():
    conn = FakeConn({"app_requirements": {"exact": [], "like": []}})
    res = KBClient(conn).requirements("DCFO", "WorkflowFile:missing.yml")
    assert res.found is False
    assert "@needs-requirement" in res.note


def test_requirements_requires_app_id_and_unit():
    conn = FakeConn({})
    res = KBClient(conn).requirements("DCFO", "")
    assert res.found is False
    assert "required" in res.note


def test_requirements_tolerates_jsonb_as_string():
    conn = FakeConn({"app_requirements": {"exact": [
        _req_row(grounded='["DatabaseTable:A"]',
                 sections='{"System Overview": "x"}')], "like": []}})
    res = KBClient(conn).requirements("DCFO", "u")
    assert res.grounded_identifiers == ["DatabaseTable:A"]
    assert res.sections["System Overview"] == "x"


def test_requirements_sql_is_parameterized():
    conn = FakeConn({"app_requirements": {"exact": [], "like": []}})
    KBClient(conn).requirements("DCFO", "'; DROP TABLE app_requirements; --")
    assert conn.log
    for sql, params in conn.log:
        assert "DROP TABLE app_requirements; --" not in sql
        assert "%s" in sql
        assert "DCFO" in params


# --- HITL additions: human-confirmed sections + approved examples -------------

def test_requirements_human_confirmed_sections_upgrade_the_note():
    conn = FakeConn({"app_requirements": {"exact": [
        _req_row(section_provenance={"Output Specification": "human-confirmed"})], "like": []}})
    res = KBClient(conn).requirements("DCFO", "u")
    assert res.section_provenance == {"Output Specification": "human-confirmed"}
    assert "Output Specification" in res.note           # named as oracle-worthy
    assert "reviewer" in res.note.lower()
    # a doc with no human input keeps the plain code-derived note
    plain = KBClient(FakeConn({"app_requirements": {"exact": [_req_row()], "like": []}}))\
        .requirements("DCFO", "u")
    assert "reviewer" not in plain.note.lower()


def test_approved_examples_found_capped_and_reference_only():
    conn = FakeConn({"app_embeddings": {"exact": [
        ("Method:m", "Feature: approved one"), ("Method:other", "Feature: approved two")],
        "like": []}})
    res = KBClient(conn).approved_examples("DCFO", "Method:m")
    assert res.found is True
    assert [e.subject for e in res.examples] == ["Method:m", "Method:other"]
    assert "REFERENCE" in res.note                      # never a substitute for grounding
    sql, params = conn.log[0]
    assert "kind = 'approved_example'" in sql
    assert "(subject = %s) DESC" in sql                 # exact unit first, deterministic
    assert "LIMIT %s" in sql and params[-1] == 2        # capped


def test_approved_examples_empty_is_honest():
    conn = FakeConn({"app_embeddings": {"exact": [], "like": []}})
    res = KBClient(conn).approved_examples("DCFO", "Method:m")
    assert res.found is False
    assert "No reviewer-approved examples" in res.note


def test_approved_examples_requires_app_and_unit():
    res = KBClient(FakeConn({})).approved_examples("DCFO", "")
    assert res.found is False and "required" in res.note


def test_approved_examples_sql_is_parameterized():
    conn = FakeConn({"app_embeddings": {"exact": [], "like": []}})
    KBClient(conn).approved_examples("DCFO", "'; DROP TABLE app_embeddings; --")
    for sql, params in conn.log:
        assert "DROP TABLE" not in sql                  # value stayed in params
