"""
The emit tools — how the agent writes a requirement document **incrementally**, so a
document can be any size without ever passing through one model response whole.

Flow per unit (the agent decides when and in what order):
  1. ``start_unit(unit_id, unit_type, title)``     — open a document.
  2. ``write_section(unit_id, section, content)``  — append markdown to one section.
        Call as many times as needed; content is appended, so a single section can be
        built across many small calls. There is NO size limit on a doc or a section.
  3. ``finish_unit(unit_id, grounded_identifiers, confidence)`` — validate + write the
        doc to disk (JSON + the file the renderer reads). Rejected (with the list of
        missing sections) if any canonical section is empty, so the agent can fix it.
  4. ``skip_type(entity_type, reason)``            — record a whole non-unit type.

State lives in this module (reset once per run via ``reset_emit``) — the same injection
pattern as ``set_facts`` / ``set_source``. The boundary reads it back with
``build_requirement_set`` (deterministic — no flaky final structured output).
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from spec_agent._strands import tool
from spec_agent.schemas import (CANONICAL_SECTIONS, RequirementDoc,
                                        RequirementEntry, RequirementSet, SkippedType)


# --- run state (injected once per run) -------------------------------------

_workspace: str = ""
_app_id: str = ""
_facts = None                                  # AnalyzerFacts — for the computed grounding signal
_source_available: bool = False
_builders: Dict[str, RequirementDoc] = {}      # unit_id -> doc being assembled
_finished: Dict[str, str] = {}                 # unit_id -> doc_file (rel path)
_skipped: List[SkippedType] = []
_feedback_ids: frozenset = frozenset()         # real open feedback ids for THIS run


def reset_emit(workspace_dir: str, app_id: str, facts=None,
               source_available: bool = False, feedback_ids=None) -> None:
    """Start a fresh run: clear all accumulated docs, point writes at this workspace, and
    inject the analyzer facts so finish_unit can compute an honest grounding descriptor.
    ``feedback_ids`` are the REAL open feedback record ids for this run — the only ids
    write_section will accept for human-confirmed marking (never inventable)."""
    global _workspace, _app_id, _facts, _source_available, _builders, _finished, \
        _skipped, _feedback_ids
    _workspace = workspace_dir
    _app_id = app_id
    _facts = facts
    _source_available = source_available
    _builders = {}
    _finished = {}
    _skipped = []
    _feedback_ids = frozenset(int(i) for i in (feedback_ids or []))


def _grounding_descriptor(unit_id: str) -> str:
    """A computed, honest statement of how well-grounded this unit's doc is — NOT a
    hardcoded score. Reflects the real analyzer facts: how many back the unit, whether
    raw source was available, and how many object names are still unresolved ${...} tokens."""
    facts = _facts.facts_for(unit_id) if _facts is not None else []
    n = len(facts)
    if n == 0:
        return ("ungrounded — no analyzer facts for this unit"
                + ("; raw source available" if _source_available else "; no raw source"))
    unresolved = sum(1 for f in facts if "${" in (f.object or ""))
    parts = [f"grounded in {n} analyzer fact(s)"]
    parts.append("raw source available" if _source_available else "no raw source")
    if unresolved:
        parts.append(f"{unresolved} of {n} names are unresolved deployment tokens (${{...}}) "
                     f"— shapes are real, values resolve per environment")
    return "; ".join(parts)


def _slug(unit_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", unit_id).strip("_") or "unit"


def build_requirement_set() -> RequirementSet:
    """Assemble the manifest from what the agent emitted — deterministic, no model call."""
    entries: List[RequirementEntry] = []
    for uid, doc in _builders.items():
        if uid in _finished:
            entries.append(RequirementEntry(
                unit=uid, unit_type=doc.unit_type, status="documented",
                doc_file=_finished[uid], grounded_identifiers=list(doc.grounded_identifiers),
                provenance=doc.provenance, requirement_backed=doc.requirement_backed,
                grounding=doc.grounding,
            ))
    return RequirementSet(app_id=_app_id, entries=entries,
                          skipped_types=list(_skipped), provenance="code-derived")


# --- the tools --------------------------------------------------------------

@tool
def start_unit(unit_id: str, unit_type: str = "", title: str = "") -> str:
    """Begin a requirement document for one unit. Call before write_section for that unit.

    Args:
        unit_id: the unit's canonical id, exactly as listed by list_units.
        unit_type: the unit's type (LambdaHandler / WorkflowFile / APIEndpoint / ...).
        title: a short human title for the document.
    """
    if not _workspace:
        return "Emit not initialized."
    if unit_id in _finished:
        _finished.pop(unit_id, None)        # re-opening a finished unit to revise it
    _builders[unit_id] = RequirementDoc(unit=unit_id, unit_type=unit_type, title=title)
    return (f"Started '{unit_id}'. Write all 9 sections with write_section "
            f"(any size, appendable), then call finish_unit. Canonical sections: "
            f"{', '.join(CANONICAL_SECTIONS)}.")


@tool
def write_section(unit_id: str, section: str, content: str,
                  feedback_id: Optional[int] = None) -> str:
    """Append markdown to one section of a unit's document. Call repeatedly — content is
    appended, so a section can be as large as needed across many calls.

    Args:
        unit_id: the unit (must have been started with start_unit).
        section: the section name, e.g. "Input Specification" (one of the canonical nine,
            or your own extra section).
        content: markdown to append to that section (tables, lists, Given/When/Then, ...).
        feedback_id: ONLY when this content applies a reviewer-feedback record from your
            task: that record's id. The section is then marked human-confirmed. Never pass
            an id for content the feedback did not ask for.
    """
    doc = _builders.get(unit_id)
    if doc is None:
        return f"'{unit_id}' was not started. Call start_unit('{unit_id}', ...) first."
    if feedback_id is not None:
        # Human-confirmed is earned, not claimed: the id must be a real open feedback
        # record injected for THIS run. An unknown id is refused before any marking.
        if int(feedback_id) not in _feedback_ids:
            return (f"feedback_id {feedback_id} is not an open feedback record for this "
                    f"run — write the section without it, or use a real id from the task.")
        doc.section_provenance[section] = "human-confirmed"
        if int(feedback_id) not in doc.feedback_ids:
            doc.feedback_ids.append(int(feedback_id))
    prev = doc.sections.get(section, "")
    doc.sections[section] = (prev + ("\n" if prev else "") + (content or "")).rstrip("\n") + "\n"
    have = [s for s in CANONICAL_SECTIONS
            if any(_norm(k) == _norm(s) and (v or "").strip()
                   for k, v in doc.sections.items())]
    missing = [s for s in CANONICAL_SECTIONS if s not in have]
    return (f"Appended to '{section}' of '{unit_id}'. "
            + (f"Still missing: {', '.join(missing)}." if missing
               else "All canonical sections present — call finish_unit when ready."))


@tool
def finish_unit(unit_id: str, grounded_identifiers: Optional[List[str]] = None) -> str:
    """Finalize a unit's document: validate it has all canonical sections, then write it
    to disk. Rejected (with the missing sections) if any canonical section is empty.

    You do NOT assign a confidence number. Provenance is recorded as code-derived (no real
    requirement backs a behavior read from code), and an honest grounding descriptor is
    computed from the analyzer facts automatically.

    Args:
        unit_id: the unit to finalize.
        grounded_identifiers: every real name you used in the doc (table/endpoint/s3
            path/function/parameter). Each is re-checked against the analyzer facts at the
            boundary — anything not real is rejected.
    """
    doc = _builders.get(unit_id)
    if doc is None:
        return f"'{unit_id}' was not started. Call start_unit first."
    doc.grounded_identifiers = list(grounded_identifiers or [])
    doc.provenance = "code-derived"
    doc.requirement_backed = False
    doc.confidence = None                    # not asserted for code-derived (never a fake 0.0)
    doc.grounding = _grounding_descriptor(unit_id)
    missing = doc.missing_sections()
    if missing:
        return (f"NOT finished — these canonical sections are empty: {', '.join(missing)}. "
                f"Add them with write_section, then call finish_unit again.")
    rel = os.path.join("requirements", _slug(unit_id) + ".json")
    full = os.path.join(_workspace, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        json.dump(doc.model_dump(), fh, indent=2)
    _finished[unit_id] = rel
    return (f"Documented '{unit_id}' → {rel}. {len(_finished)} unit(s) documented, "
            f"{len(_skipped)} type(s) skipped so far.")


def record_skip(entity_type: str, reason: str) -> str:
    """Plain (non-tool) recorder for a not-a-unit type — usable directly by the
    orchestrator as well as by the ``skip_type`` agent tool below. Same effect."""
    _skipped[:] = [s for s in _skipped if s.entity_type != entity_type]
    _skipped.append(SkippedType(entity_type=entity_type, reason=reason))
    return f"Recorded '{entity_type}' as not-a-unit. Its members no longer need documenting."


@tool
def skip_type(entity_type: str, reason: str) -> str:
    """Declare a whole entity type NOT a testable unit (e.g. internal helper Functions),
    so you need not document each member. Every such type still needs a reason.

    Args:
        entity_type: the analyzer entity type to skip (as shown by list_units).
        reason: why this whole type is not an independently testable unit.
    """
    return record_skip(entity_type, reason)


def _norm(name: str) -> str:
    from spec_agent.schemas import section_key
    return section_key(name)
