"""Tests for the pure (Strands-free) parts of agent assembly."""
from __future__ import annotations

import os

from coding_agent.agent import WorkspaceGuard, domain_tools, task_prompt
from coding_agent.schemas import AgentTask, Scope


def test_workspace_guard_allows_inside(tmp_path):
    g = WorkspaceGuard(str(tmp_path))
    assert g.allows(str(tmp_path))
    assert g.allows(str(tmp_path / "steps" / "late.py"))
    assert g.allows("steps/late.py")            # relative resolves under root


def test_workspace_guard_blocks_outside(tmp_path):
    g = WorkspaceGuard(str(tmp_path))
    assert not g.allows("/etc/passwd")
    assert not g.allows(str(tmp_path / ".." / "secret.txt"))
    assert not g.allows("../../escape")
    assert not g.allows("")


def test_workspace_guard_blocks_sibling_prefix(tmp_path):
    # A sibling dir sharing a name prefix must not be allowed (the +os.sep guard).
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "ws_evil").mkdir()
    g = WorkspaceGuard(str(ws))
    assert not g.allows(str(tmp_path / "ws_evil" / "x"))


def test_domain_tools_are_the_three():
    names = {getattr(t, "__name__", getattr(t, "tool_name", "")) for t in domain_tools()}
    assert {"kb_query", "kb_graph", "lint_tests"} <= names


def test_task_prompt_includes_everything():
    task = AgentTask(
        ticket_id="ETSAPS-1", ticket_text="charge 5% late fee",
        diff="--- a\n+++ b\n@@ late_fee", framework="behave",
        scope=Scope(app_id="DEMO"), workspace_dir="/tmp/ws",
    )
    p = task_prompt(task)
    assert "ETSAPS-1" in p and "behave" in p and "DEMO" in p
    assert "late_fee" in p and "/tmp/ws" in p


def test_task_prompt_carries_cucumber_reference_note():
    task = AgentTask(framework="cucumber", scope=Scope(app_id="java-stress"),
                     workspace_dir="/tmp/ws")
    p = task_prompt(task)
    assert "FRAMEWORK REFERENCE — Cucumber-JVM" in p
    assert "AmbiguousStepDefinitionsException" in p
    assert "io.cucumber.java.en" in p
    # the honesty line about the Python-only linter travels with the note
    assert "CANNOT check Java files" in p


def test_task_prompt_behave_note_and_unknown_framework_graceful():
    behave = task_prompt(AgentTask(framework="behave", scope=Scope(app_id="A"),
                                   workspace_dir="/tmp/ws"))
    assert "FRAMEWORK REFERENCE — Behave" in behave
    # frameworks without a note yet degrade to no note, never an error
    karate = task_prompt(AgentTask(framework="karate", scope=Scope(app_id="A"),
                                   workspace_dir="/tmp/ws"))
    assert "FRAMEWORK REFERENCE" not in karate


def test_task_prompt_single_unit_mode_names_unit_and_feedback():
    from coding_agent.schemas import FeedbackItem
    task = AgentTask(framework="behave", scope=Scope(app_id="DCFO"),
                     unit="Method:LoanController.createLoan",
                     feedback=[FeedbackItem(id=7, action="reject",
                                            comment="total must come from the DB",
                                            reviewer="alice")])
    p = task_prompt(task)
    assert "ONE unit" in p and "Method:LoanController.createLoan" in p
    assert "feedback_id 7" in p and "total must come from the DB" in p
    assert "kb_examples" in p and "feedback_ids" in p
    assert "Do not test or skip anything else." in p


def test_task_prompt_whole_app_mentions_examples_and_stays_default():
    p = task_prompt(AgentTask(framework="behave", scope=Scope(app_id="A")))
    assert "kb_inventory" in p                      # still the whole-app prompt
    assert "kb_examples" in p                       # long-term channel on every run
