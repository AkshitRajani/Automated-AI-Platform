"""
The external Pydantic contracts for the Coding Agent: what goes in
(``AgentTask``) and what comes out (``TestBundle``).

These mirror ``04_coding_agent_agentic.md`` §5. They are kept deliberately
**flat** — Strands structured output is not 100%-reliable on deeply nested
schemas, so the final ``TestBundle`` avoids nesting beyond one level.

Tool-specific I/O models (``GroundResult``, ``GraphResult``, ``LintReport``)
live next to their tools, not here; this module is only the agent's outer
contract.
"""
from __future__ import annotations

import tempfile
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _default_workspace() -> str:
    """A fresh temp dir per run, so callers never have to supply one."""
    return tempfile.mkdtemp(prefix="aap_ws_")


# --- Input ------------------------------------------------------------------

Framework = Literal["behave", "cucumber", "karate", "selenium", "playwright"]


class Scope(BaseModel):
    """The KB addressing axes. Slice 1 enforces only ``app_id``; the other three
    are carried so the contract is ready for ETSAPS-4264 (4-axis versioning,
    the client-owned) but are accepted-and-ignored until that schema ships."""

    app_id: str = Field(..., description="REQUIRED — the only axis enforced today.")
    environment: Optional[str] = None      # dev|test|prod (not yet enforced)
    code_version: Optional[str] = None      # (not yet enforced)
    config_snapshot: Optional[str] = None   # (not yet enforced)


class FeedbackItem(BaseModel):
    """One open reviewer-feedback record, passed INTO a task (the caller fetches these
    from the KB's ``app_feedback`` table — this package never owns the store). The id is
    the record's real row id: it is how a regenerated test proves which feedback it
    addresses, so it must be real, never invented."""

    id: int
    action: Literal["approve", "reject", "comment"]
    comment: str = ""
    reviewer: str = ""
    # What KIND of thing the feedback concerns (optional): behavior-scope | payload |
    # contract | data-condition | assertion | expected-result | environment | naming |
    # structure. Helps the agent aim the fix at the right place.
    target: str = ""


class AgentTask(BaseModel):
    """One unit of work in a named framework, scoped to one app.

    Three modes, same agent:
      * **whole-app** (default) — give ``framework`` + ``scope.app_id`` (and,
        optionally, ``codebase_zip``). The agent discovers the app's
        journeys / workflows / pipelines from the KB and generates a full
        functional suite. No ticket, no diff.
      * **single-unit rerun** (the HITL path, final_design/08_feedback_loop.md) —
        set ``unit`` to regenerate ONE unit's tests, with ``feedback`` carrying
        the open reviewer records to apply.
      * **per-change** (legacy) — additionally pass ``ticket_text`` + ``diff``
        to test one specific change.
    """

    framework: Framework            # the PO names it; the agent never infers it
    scope: Scope                    # app_id (required) + the 4-axis fields

    # Per-change mode only — omitted in whole-app mode.
    ticket_id: str = "whole-app"
    ticket_text: str = ""           # NL description of the change to test
    diff: str = ""                  # unified diff of the code change

    # Single-unit rerun: the one unit whose tests to (re)generate. None = whole app.
    unit: Optional[str] = None
    # Open reviewer feedback to apply on this run (single-unit reruns).
    feedback: List[FeedbackItem] = Field(default_factory=list)

    # Pointer to the onboarded app's RAW source (a .zip or a folder). When set,
    # the agent can read the real code on demand via the read_source tools to
    # understand a workflow the KB facts only summarize. Optional.
    codebase_zip: Optional[str] = None

    # scoped dir the agent may read/write/run in. Optional — defaults to a fresh
    # temp dir so whoever runs the agent doesn't have to set one up.
    workspace_dir: str = Field(default_factory=_default_workspace)


# --- Output -----------------------------------------------------------------

class StepFile(BaseModel):
    path: str
    language: Literal["python", "java", "js", "yaml"]
    content: str


class GroundedId(BaseModel):
    name: str            # the real canonical name used
    kind: str            # endpoint|table|helper|parameter|s3_path|...
    provenance: str      # KB table/edge + app_id it came from


class TestBundle(BaseModel):
    """The agent's final structured output. Emitted via Strands structured
    output (a forced, validated tool call), alongside the files written to disk."""

    __test__ = False  # not a pytest test class (the name starts with "Test")

    framework: str
    feature_file: Optional[str] = None       # .feature text (Behave/Cucumber/Karate)
    step_files: List[StepFile] = Field(default_factory=list)
    grounded_identifiers: List[GroundedId] = Field(default_factory=list)
    confidence: float                        # 0–1, first-class output
    confidence_reasoning: str
    uncertainty_tags: List[str] = Field(default_factory=list)
    # @needs-helper-source @needs-data @needs-rule-signoff @stale-context @hitl-required
    provenance: str                          # scope + tool-call trail summary


# --- Whole-app output: a suite of per-unit tests + a manifest ----------------

class ManifestEntry(BaseModel):
    """One unit's accounting in a whole-app suite: a written test, or a skip with a
    reason. The feature/steps file CONTENTS live on disk in the workspace; this entry
    only indexes them (keeps the structured output light, avoids a giant blob)."""

    __test__ = False

    unit: str                                # canonical id of the unit (from kb_inventory)
    status: Literal["tested", "skipped"]
    reason: str = ""                         # why skipped (required when status=skipped)
    feature_file: str = ""                   # path rel to workspace (when tested)
    steps_file: str = ""
    grounded_identifiers: List[GroundedId] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty_tags: List[str] = Field(default_factory=list)
    # Feedback record ids this entry's regeneration addressed (single-unit reruns).
    # The boundary's feedback gate checks every actionable record shows up here.
    feedback_ids: List[int] = Field(default_factory=list)


class SkippedType(BaseModel):
    """A whole KB entity-type declared not-testable in one verdict (e.g. internal
    'Function' helpers) — so the agent need not enumerate every member as skipped."""

    entity_type: str
    reason: str


class TestSuite(BaseModel):
    """The whole-app output: one entry per unit (tested or skipped) + group-level
    not-testable verdicts. The actual feature/steps files are on disk; this is the
    manifest/index the coverage check reads."""

    __test__ = False

    framework: str
    app_id: str
    entries: List[ManifestEntry] = Field(default_factory=list)
    skipped_types: List[SkippedType] = Field(default_factory=list)
    provenance: str = ""
