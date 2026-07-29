"""Tests for the deterministic boundary's grounding gate (pure, no live DB)."""
from __future__ import annotations

from coding_agent.boundary import grounding_gate
from coding_agent.kb.facts import KBClient
from coding_agent.schemas import GroundedId, StepFile, TestBundle
from coding_agent.tests.fakes import FakeConn


def _bundle(ids):
    return TestBundle(
        framework="behave", feature_file="Feature: x",
        step_files=[StepFile(path="steps/x.py", language="python", content="# x")],
        grounded_identifiers=ids, confidence=0.8, confidence_reasoning="ok",
        provenance="DEMO",
    )


def test_gate_confirms_real_names():
    conn = FakeConn({
        "app_tables": {"exact": [("APP_PMT_AMT", "read", True, 0.99)], "like": []},
    })
    bundle = _bundle([GroundedId(name="APP_PMT_AMT", kind="table", provenance="app_tables@DEMO")])
    gate = grounding_gate(bundle, "DEMO", KBClient(conn))
    assert gate.ok is True
    assert [g.name for g in gate.confirmed] == ["APP_PMT_AMT"]
    assert gate.rejected == []


def test_gate_rejects_invented_name():
    conn = FakeConn({"app_tables": {"exact": [], "like": []}})
    bundle = _bundle([GroundedId(name="FAKE_TABLE", kind="table", provenance="invented")])
    gate = grounding_gate(bundle, "DEMO", KBClient(conn))
    assert gate.ok is False
    assert [g.name for g in gate.rejected] == ["FAKE_TABLE"]
    assert "ungrounded" in gate.reasons[0]


def test_gate_rejects_unresolved_token():
    # Name exists but is an unresolved ${...} token (resolved=False) → not grounded.
    conn = FakeConn({
        "app_s3_paths": {"exact": [("${log_path}", "read", False, 0.5)], "like": []},
    })
    bundle = _bundle([GroundedId(name="${log_path}", kind="s3_path", provenance="app_s3_paths@DEMO")])
    gate = grounding_gate(bundle, "DEMO", KBClient(conn))
    assert gate.ok is False
    assert gate.rejected[0].name == "${log_path}"


def test_gate_mixed_partial_pass():
    conn = FakeConn({
        "app_tables": {"exact": [("APP_PMT_AMT", "read", True, 0.9)], "like": []},
        "app_endpoints": {"exact": [], "like": []},
    })
    bundle = _bundle([
        GroundedId(name="APP_PMT_AMT", kind="table", provenance="app_tables@DEMO"),
        GroundedId(name="/ghost", kind="endpoint", provenance="invented"),
    ])
    gate = grounding_gate(bundle, "DEMO", KBClient(conn))
    assert gate.ok is False
    assert {g.name for g in gate.confirmed} == {"APP_PMT_AMT"}
    assert {g.name for g in gate.rejected} == {"/ghost"}


# --- HITL additions: single-unit coverage + feedback closure ------------------

def test_single_unit_gap_needs_a_tested_entry():
    from coding_agent.boundary import single_unit_gap
    from coding_agent.schemas import ManifestEntry, TestSuite
    tested = TestSuite(app_id="A", framework="behave", entries=[
        ManifestEntry(unit="Method:m", status="tested", feature_file="f.feature")])
    skipped = TestSuite(app_id="A", framework="behave", entries=[
        ManifestEntry(unit="Method:m", status="skipped", reason="n/a")])
    assert single_unit_gap("Method:m", tested) == []
    assert single_unit_gap("Method:m", skipped) == ["Method:m"]   # a skip doesn't satisfy a rerun
    assert single_unit_gap("Method:other", tested) == ["Method:other"]


def test_feedback_gate_closure():
    from coding_agent.boundary import feedback_gate
    from coding_agent.schemas import FeedbackItem, ManifestEntry, TestSuite
    suite = TestSuite(app_id="A", framework="behave", entries=[
        ManifestEntry(unit="Method:m", status="tested", feedback_ids=[7])])
    ok = feedback_gate(suite, [FeedbackItem(id=7, action="reject", comment="x")])
    assert ok.ok
    missing = feedback_gate(suite, [FeedbackItem(id=8, action="comment", comment="y")])
    assert not missing.ok and "feedback record 8" in missing.reasons[0]
    # approvals owe nothing; no feedback owes nothing
    assert feedback_gate(suite, [FeedbackItem(id=9, action="approve")]).ok
    assert feedback_gate(suite, []).ok


# --- journey-aware coverage (issue C2) -----------------------------------------

def test_coverage_covers_chain_members_through_their_journey():
    """A brick that the KB's own membership facts place inside an ACCOUNTED journey
    is covered by that journey — not owed its own test. Un-membered bricks still
    surface as genuine gaps."""
    from coding_agent.boundary import coverage_gap
    from coding_agent.kb.facts import EntityGroup, KBInventory
    from coding_agent.schemas import ManifestEntry, SkippedType, TestSuite

    inventory = KBInventory(app_id="A", endpoints=["POST /run"], groups=[
        EntityGroup(entity_type="Journey", count=1, names=["Journey:APIEndpoint:POST /run"]),
        EntityGroup(entity_type="Function", count=2, names=["app.handler", "app.orphan"]),
    ])
    members = {"Journey:APIEndpoint:POST /run":
               {"APIEndpoint:POST /run", "Function:app.handler"}}
    suite = TestSuite(app_id="A", framework="behave", entries=[
        ManifestEntry(unit="Journey:APIEndpoint:POST /run", status="tested",
                      feature_file="j.feature")])

    gaps = coverage_gap(inventory, suite, members)
    assert "app.handler" not in gaps          # covered through its journey
    assert "POST /run" not in gaps            # the entry itself is the journey's start
    assert gaps == ["app.orphan"]             # in no chain -> a genuine gap

    # an UNACCOUNTED chain covers nothing
    empty = TestSuite(app_id="A", framework="behave", entries=[
        ManifestEntry(unit="Function:app.other", status="tested", feature_file="o.feature")])
    gaps2 = coverage_gap(inventory, empty, members)
    assert "app.handler" in gaps2 and "POST /run" in gaps2
