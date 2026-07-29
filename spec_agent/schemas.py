"""
The Pydantic contracts for the Requirement Agent.

The design is "incremental assembly + light manifest" — built so a requirement
document can be **any size** without ever passing the whole thing through one model
response:

  * ``RequirementDoc`` — the per-unit document. Its body is a ``sections`` map
    (canonical section name → markdown). The agent fills it **one section at a time**
    via the emit tools (``start_unit`` / ``write_section`` / ``finish_unit``); plain
    code assembles + validates + writes it. Section content is appended, so a single
    section can itself be built across many small tool calls — there is no size limit.
  * ``RequirementSet`` — the manifest the coverage gate reads: one ``RequirementEntry``
    per unit (documented or skipped) + group-level not-a-unit verdicts. It is assembled
    **deterministically** by the boundary from the emit records — never emitted whole by
    the model — so it can't be truncated and there is no flaky structured-output step.
"""
from __future__ import annotations

import tempfile
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# The nine canonical sections every requirement doc must cover — the same shape as the
# client's own spec viewer. The agent may add extra sections; these are the ones the
# doc-validity gate requires (matched case-insensitively, leading numbers ignored).
CANONICAL_SECTIONS: List[str] = [
    "System Overview",
    "Input Specification",
    "Consolidated Requirements",
    "Output Specification",
    "Function Specification",
    "User Stories",
    "Traceability Matrix",
    "Confidence Mapping",
    "Gap Analysis",
]


def _default_workspace() -> str:
    """A fresh temp dir per run, so callers never have to supply one."""
    return tempfile.mkdtemp(prefix="aap_req_")


def section_key(name: str) -> str:
    """Normalize a section name for matching: lowercase, drop a leading number/punct.
    'Input Specification', '2. Input Specification', 'input specification' all match."""
    s = (name or "").strip().lower()
    # strip a leading "<n>." / "<n>" and surrounding punctuation
    while s and (s[0].isdigit() or s[0] in ".)-: "):
        s = s[1:]
    return s.strip()


_CANON_KEYS = {section_key(s) for s in CANONICAL_SECTIONS}


# --- Input ------------------------------------------------------------------

class FeedbackItem(BaseModel):
    """One open reviewer-feedback record, passed INTO a task (the caller fetches these
    from the KB's ``app_feedback`` table — this package never touches the DB). The id is
    the record's real row id: it is how a regenerated section proves which feedback it
    addresses, so it must be real, never invented."""

    id: int
    action: Literal["approve", "reject", "comment"]
    comment: str = ""
    reviewer: str = ""
    # What KIND of thing the feedback concerns (optional): behavior-scope | payload |
    # contract | data-condition | assertion | expected-result | environment | naming |
    # structure. Helps the agent aim the fix at the right section.
    target: str = ""


class RequirementTask(BaseModel):
    """One onboarding run: document the requirements of one application.

    The agent reads the analyzer's output (a quad file) + the raw source — never a
    live KB (the KB does not exist yet at onboarding). No framework: requirements
    are framework-agnostic (the coding agent picks the framework later).

    Single-unit rerun (the HITL path, final_design/08_feedback_loop.md): set ``unit``
    to regenerate ONE unit's doc — with ``feedback`` carrying the open reviewer records
    to apply. Whole-app behavior is unchanged when ``unit`` is None."""

    app_id: str                              # REQUIRED — KB scope / app id
    analyzer_output: str                     # path to the analyzer's quad YAML (Step 1/2 output)
    worksheet: str = ""                     # optional human name-sheet (doc 10) applied over quad bindings
    # Pointer to the app's RAW source (a .zip or a folder) for read_source. Optional.
    codebase: Optional[str] = None
    # scoped dir the agent reads/writes/runs in. Optional — defaults to a temp dir.
    workspace_dir: str = Field(default_factory=_default_workspace)
    # Single-unit rerun: the one unit to (re)document. None = whole app.
    unit: Optional[str] = None
    # Open reviewer feedback to apply on this run (single-unit reruns).
    feedback: List[FeedbackItem] = Field(default_factory=list)


# --- The manifest: one entry per unit (assembled deterministically) ---------

class RequirementEntry(BaseModel):
    """One unit's accounting: a written requirement doc, or a skip with a reason.
    The doc CONTENTS live on disk (``doc_file``); this entry only indexes them."""

    unit: str                                # canonical id of the unit (from the analyzer)
    unit_type: str = ""                      # Function|LambdaHandler|WorkflowFile|APIEndpoint|...
    status: Literal["documented", "skipped"]
    reason: str = ""                         # why skipped (required when status=skipped)
    doc_file: str = ""                       # path rel to workspace (when documented)
    grounded_identifiers: List[str] = Field(default_factory=list)   # real names used in the doc
    provenance: str = "code-derived"         # code-derived | jira:<id> | sttm:<id>
    requirement_backed: bool = False         # True only when a real requirement backs it
    grounding: str = ""                      # computed, honest descriptor of extraction grounding


class SkippedType(BaseModel):
    """A whole entity-type declared not-a-testable-unit in one verdict (e.g. internal
    'Function' helpers) — so the agent need not enumerate every member as skipped."""

    entity_type: str
    reason: str


class RequirementSet(BaseModel):
    """The manifest: one entry per unit (documented or skipped) + group-level
    not-a-unit verdicts. Assembled by the boundary from the emit records; the actual
    requirement docs are the JSON/markdown files on disk."""

    app_id: str
    entries: List[RequirementEntry] = Field(default_factory=list)
    skipped_types: List[SkippedType] = Field(default_factory=list)
    provenance: str = ""


# --- The per-unit doc (assembled section-by-section, written to disk) --------

class RequirementDoc(BaseModel):
    """The full per-unit requirement document. The body is a ``sections`` map
    (section name → markdown), filled incrementally by the emit tools, so the document
    can be arbitrarily large without any single model response carrying it.

    ``render.py`` turns this into the client-style 9-section markdown; the boundary's
    doc-validity gate checks every canonical section is present and non-empty."""

    unit: str
    unit_type: str = ""
    title: str = ""
    provenance: str = "code-derived"        # where the requirement came from: code-derived | jira:<id> | sttm:<id>
    requirement_backed: bool = False        # True only when a real (JIRA/STTM) requirement backs it
    # Numeric alignment to a real requirement. None = NOT asserted — there is nothing to
    # measure alignment against for a code-derived behavior. Becomes a real score (0..1)
    # only when requirement_backed is True. We never report a misleading hardcoded 0.0.
    confidence: Optional[float] = None
    # Honest, COMPUTED descriptor of how well the doc is grounded in the analyzer facts —
    # varies per unit (fact count, source availability, unresolved deployment tokens).
    grounding: str = ""
    grounded_identifiers: List[str] = Field(default_factory=list)
    sections: Dict[str, str] = Field(default_factory=dict)   # section name -> markdown body
    # Per-section provenance: ONLY sections revised because of a real feedback record are
    # marked 'human-confirmed' (the honest scope — a human corrected THIS section, nothing
    # more). Absent keys inherit the doc-level provenance. Never self-assigned: the emit
    # tool requires a real feedback id to mark a section.
    section_provenance: Dict[str, str] = Field(default_factory=dict)
    # The feedback record ids this doc addressed (closure: reject/comment records passed
    # into the task must all appear here, checked by the boundary's feedback gate).
    feedback_ids: List[int] = Field(default_factory=list)

    def missing_sections(self) -> List[str]:
        """Canonical sections that are absent or empty — what the doc-validity gate checks."""
        have = {section_key(k) for k, v in self.sections.items() if (v or "").strip()}
        return [s for s in CANONICAL_SECTIONS if section_key(s) not in have]
