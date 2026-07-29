"""
The deterministic boundary (orchestrator, no LLM) around the autonomous requirement
agent — the same "agent-in-a-cage" discipline as the coding agent. The agent navigates
freely; these walls are plain, testable code:

  1. Grounding gate — every name the agent claims it grounded must really exist in the
     analyzer output (the cure for invented identifiers).
  2. Doc-validity gate — every documented unit's JSON doc exists, parses, and has all
     nine canonical sections non-empty (the analogue of the coding agent's lint gate).
  3. Coverage gate — every entity the analyzer found is accounted for: documented,
     individually skipped, or covered by a not-a-unit type verdict.
  4. Bounded repair — on any failure, inject the findings as the agent's next turn, at
     most ``max_repairs`` times, then route to a human.

The manifest is assembled **deterministically** from the agent's emit records (not a
final model structured-output call), so it cannot be truncated and there is no flaky
serialization step. The three gates are pure and unit-tested with an injected
``AnalyzerFacts``; the repair loop drives the Strands agent and needs the runtime.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from pydantic import BaseModel

from requirement_agent.facts import AnalyzerFacts
from requirement_agent.schemas import RequirementSet, RequirementTask


class GateResult(BaseModel):
    ok: bool
    rejected: List[str] = []
    reasons: List[str] = []


def grounding_gate(req_set: RequirementSet, facts: AnalyzerFacts) -> GateResult:
    """Every grounded identifier on every documented unit must resolve in the analyzer
    output. Pure: ``facts`` is injected, so this is testable without a run."""
    rejected: List[str] = []
    reasons: List[str] = []
    for e in req_set.entries:
        if e.status != "documented":
            continue
        for name in e.grounded_identifiers:
            if not facts.resolve(name):
                rejected.append(name)
                reasons.append(
                    f"'{name}' claimed grounded in unit '{e.unit}' is not a real name in "
                    f"the analyzer output — drop it or use the real name."
                )
    return GateResult(ok=not rejected, rejected=rejected, reasons=reasons)


def doc_validity_gate(req_set: RequirementSet, workspace_dir: str) -> GateResult:
    """Every documented unit's ``doc_file`` exists, parses as a RequirementDoc, and has
    all nine canonical sections present and non-empty."""
    from requirement_agent.render import load_doc
    rejected: List[str] = []
    reasons: List[str] = []
    for e in req_set.entries:
        if e.status != "documented":
            continue
        if not e.doc_file:
            rejected.append(e.unit)
            reasons.append(f"unit '{e.unit}' is marked documented but has no doc_file.")
            continue
        path = e.doc_file if os.path.isabs(e.doc_file) else os.path.join(workspace_dir, e.doc_file)
        if not os.path.isfile(path):
            rejected.append(e.unit)
            reasons.append(f"doc_file for unit '{e.unit}' not found: {e.doc_file}")
            continue
        try:
            doc = load_doc(path)
        except Exception as ex:
            rejected.append(e.unit)
            reasons.append(f"doc_file for unit '{e.unit}' is not a valid requirement doc: {ex}")
            continue
        missing = doc.missing_sections()
        if missing:
            rejected.append(e.unit)
            reasons.append(f"unit '{e.unit}' is missing canonical sections: "
                           f"{', '.join(missing)} — write them, then finish_unit again.")
    return GateResult(ok=not rejected, rejected=rejected, reasons=reasons)


def coverage_gap(facts: AnalyzerFacts, req_set: RequirementSet) -> List[str]:
    """Entities in the analyzer output that the set did NOT account for — neither
    documented, individually skipped, nor covered by a not-a-unit type verdict. Pure.

    Nothing about *which* entities are units is hardcoded: the agent makes that call
    (recorded in entries / skipped_types); this only enforces that nothing was forgotten."""
    accounted = {e.unit for e in req_set.entries}
    skipped_types = {st.entity_type for st in req_set.skipped_types}
    gaps: List[str] = []
    for uid in facts.unit_ids():
        ent = facts.entity(uid)
        etype = ent.type if ent else "Unknown"
        if etype in skipped_types:
            continue
        if uid not in accounted:
            gaps.append(uid)
    return sorted(gaps)


# --- repair orchestration (drives the Strands agent) -----------------------

class BoundaryOutcome(BaseModel):
    delivered: bool
    requirement_set: Optional[RequirementSet] = None
    attempts: int = 0
    gate_reasons: List[str] = []
    coverage_gaps: List[str] = []
    markdown_files: List[str] = []
    routed_to_human: bool = False


def _write_manifest(workspace_dir: str, req_set: Optional[RequirementSet]) -> None:
    """Write the manifest to ``<workspace>/requirements_manifest.json`` (best-effort)."""
    if req_set is None:
        return
    try:
        path = os.path.join(workspace_dir, "requirements_manifest.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(req_set.model_dump(), fh, indent=2)
    except OSError:
        pass


def _documented_docs(req_set: Optional[RequirementSet]) -> List[str]:
    if req_set is None:
        return []
    return [e.doc_file for e in req_set.entries
            if e.status == "documented" and e.doc_file]


def run_with_boundary(task: RequirementTask, max_repairs: int = 2,
                      agent_callback=None) -> BoundaryOutcome:
    """Run the agent, apply the three gates, repair up to ``max_repairs`` times, else
    route to a human. The manifest is assembled deterministically from the agent's emit
    records after each turn. Requires the Strands runtime (drives the loop)."""
    from requirement_agent.agent import build_agent, task_prompt
    from requirement_agent.render import render_set
    from requirement_agent.run_log import RunLogger, tee
    from requirement_agent.tools import build_requirement_set

    facts = AnalyzerFacts.from_file(task.analyzer_output)
    log = RunLogger(
        os.path.join(task.workspace_dir, "agent_log.txt"),
        header=(f"# Automated AI Platform requirement agent — run\n# app: {task.app_id}\n"),
    )
    try:
        agent = build_agent(task, callback=tee(log.callback, agent_callback))
        prompt = task_prompt(task)
        reasons: List[str] = []

        for attempt in range(1, max_repairs + 2):
            agent(prompt)                                  # the autonomous turn (no structured output)
            req_set = build_requirement_set()              # deterministic, from emit records

            g = grounding_gate(req_set, facts)
            d = doc_validity_gate(req_set, task.workspace_dir)
            gaps = coverage_gap(facts, req_set)
            reasons = g.reasons + d.reasons
            if gaps:
                shown = ", ".join(gaps[:30]) + (f" … (+{len(gaps) - 30} more)"
                                                if len(gaps) > 30 else "")
                reasons.append("These analyzer units are unaccounted for — document each "
                               "(start_unit/write_section/finish_unit), or mark its entity "
                               f"type not-a-unit with skip_type and a reason: {shown}")

            if g.ok and d.ok and not gaps:
                md = render_set(task.workspace_dir, _documented_docs(req_set))
                _write_manifest(task.workspace_dir, req_set)
                return BoundaryOutcome(delivered=True, requirement_set=req_set,
                                       attempts=attempt, markdown_files=md)

            prompt = ("Your requirement set failed the deterministic boundary. Fix exactly "
                      "these (re-open a unit with start_unit to revise it, then finish_unit):\n- "
                      + "\n- ".join(reasons))

        # Repairs exhausted → route to a human, but keep the last set inspectable.
        last = build_requirement_set()
        md = render_set(task.workspace_dir, _documented_docs(last))
        _write_manifest(task.workspace_dir, last)
        gaps = coverage_gap(facts, last)
        return BoundaryOutcome(delivered=False, requirement_set=last,
                               attempts=max_repairs + 1, gate_reasons=reasons,
                               coverage_gaps=gaps, markdown_files=md, routed_to_human=True)
    finally:
        log.close()
