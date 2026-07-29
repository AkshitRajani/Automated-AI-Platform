"""Tool-wrapper tests: kb_query / kb_graph via injected fakes; lint_tests live."""
from __future__ import annotations

import os

from coding_agent.kb.facts import KBClient
from coding_agent.kb.graph import GraphClient
from coding_agent.tools import kb_query, kb_graph, lint_tests, set_client, set_graph_client
from coding_agent.tests.fakes import FakeConn
from coding_agent.tests.test_graph import FakeExecutor

EX_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "validator", "examples")


def test_kb_query_tool_uses_injected_client():
    set_client(KBClient(FakeConn({
        "app_tables": {"exact": [("APP_PMT_AMT", "read", True, 0.99)], "like": []},
    })))
    try:
        res = kb_query("APP_PMT_AMT", kind="table", app_id="DEMO")
        assert res.candidates[0].canonical_name == "APP_PMT_AMT"
    finally:
        set_client(None)


def test_kb_graph_tool_uses_injected_client():
    set_graph_client(GraphClient(FakeExecutor({
        "h": [{"src": "h", "relation": "QUERIES_DATABASE", "dst": "T", "dst_kind": "Table"}],
    }), True))
    try:
        res = kb_graph("h", app_id="DEMO")
        assert res.edges[0].dst == "T"
    finally:
        set_graph_client(None)


def test_kb_graph_tool_degrades_without_neptune():
    set_graph_client(GraphClient(None, False))
    try:
        res = kb_graph("anything", app_id="DEMO")
        assert res.edges == [] and "not configured" in res.note
    finally:
        set_graph_client(None)


def test_lint_tests_flags_bad_steps():
    report = lint_tests(os.path.join(EX_DIR, "bad_steps"))
    assert report.ok is False
    assert report.error_count > 0
    assert report.findings and report.findings[0].rule


def test_lint_tests_passes_good_steps():
    report = lint_tests(os.path.join(EX_DIR, "good_steps"))
    assert report.ok is True
    assert report.error_count == 0
    assert report.files_checked == 1


def test_lint_tests_zero_python_files_is_flagged_not_silent(tmp_path):
    """A Java-only dir must not read as a validated pass — the note says what
    was NOT checked (the false-green the Cucumber work would otherwise hit)."""
    (tmp_path / "OrderSteps.java").write_text("public class OrderSteps {}")
    report = lint_tests(str(tmp_path))
    assert report.files_checked == 0
    assert "NOT checked" in report.note
    assert "javac" in report.note


def test_lint_tests_applies_team_standards_from_workspace(tmp_path):
    """standards.json at the lint root = the app team's promoted feedback rules;
    its findings ride the same report the repair loop already consumes."""
    import json
    (tmp_path / "create.feature").write_text(
        "Feature: X\n  desc\n  Scenario: no tag here\n    Given x\n")
    (tmp_path / "standards.json").write_text(json.dumps({"required_tags": ["@REQ"]}))
    report = lint_tests(str(tmp_path))
    assert report.ok is False
    assert any(f.rule == "team-standard-required-tag" for f in report.findings)
    assert "standards.json" in report.note


def test_lint_tests_invalid_standards_never_half_applies(tmp_path):
    import json
    (tmp_path / "standards.json").write_text(json.dumps({"typo_key": True}))
    report = lint_tests(str(tmp_path))
    assert report.ok is False
    assert report.findings[0].rule == "team-standards-config"
    assert "typo_key" in report.findings[0].message


def test_lint_tests_without_standards_unchanged(tmp_path):
    (tmp_path / "x.feature").write_text("Feature: X\n  Scenario: s\n    Given x\n")
    report = lint_tests(str(tmp_path))
    assert not any(f.rule.startswith("team-standard") for f in report.findings)
