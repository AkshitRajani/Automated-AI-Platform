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

from spec_agent.facts import AnalyzerFacts
from spec_agent.schemas import RequirementSet, RequirementTask


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
    from spec_agent.render import load_doc
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


def single_unit_gap(unit: str, req_set: RequirementSet) -> List[str]:
    """Coverage for a single-unit rerun: THAT unit must be documented; nothing else is
    owed. Pure — same contract as coverage_gap, over a worklist of one."""
    for e in req_set.entries:
        if e.unit == unit and e.status == "documented":
            return []
    return [unit]


def feedback_gate(req_set: RequirementSet, workspace_dir: str, feedback) -> GateResult:
    """Closure: every actionable feedback record passed into the task (reject/comment —
    approve asks for nothing) must be addressed by the regenerated doc, proven by its
    ``feedback_ids``. Pure: reads the doc file the manifest points at; no DB, no model."""
    owed = {f.id for f in feedback if f.action in ("reject", "comment")}
    if not owed:
        return GateResult(ok=True)
    from spec_agent.render import load_doc
    addressed: set = set()
    for e in req_set.entries:
        if e.status != "documented" or not e.doc_file:
            continue
        path = e.doc_file if os.path.isabs(e.doc_file) else os.path.join(workspace_dir, e.doc_file)
        try:
            doc = load_doc(path)
        except Exception:
            continue                        # doc-validity gate reports unloadable docs
        addressed.update(int(i) for i in doc.feedback_ids)
    missing = sorted(owed - addressed)
    if not missing:
        return GateResult(ok=True)
    return GateResult(
        ok=False, rejected=[str(i) for i in missing],
        reasons=[(f"feedback record {i} was not addressed — revise the section it "
                  f"concerns via write_section(..., feedback_id={i}), then finish_unit "
                  f"again.") for i in missing],
    )


def story_gate(req_set: RequirementSet, facts: AnalyzerFacts) -> GateResult:
    """Every documented Journey spec must ground at least one OBSERVABLE outcome —
    an object the analyzer saw being read, written, exposed, or started. A journey
    document that grounds only code names is a hand-off description, not a story;
    that is exactly the failure mode this gate exists to make loud. Pure."""
    observables = facts.observable_objects()
    reasons: List[str] = []
    for e in req_set.entries:
        if e.status != "documented" or not e.unit.startswith("Journey:"):
            continue
        if not set(e.grounded_identifiers) & observables:
            reasons.append(
                f"Journey spec '{e.unit}' grounds no observable outcome (no table, "
                f"object, endpoint, or workflow the analyzer saw) — narrate what the "
                f"chain does to the outside world, not just which code runs.")
    return GateResult(ok=not reasons, reasons=reasons)


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
    """Entry point. Dispatches by size of work:

    - **single-unit rerun** (``task.unit`` set — a reviewer-feedback regeneration): one
      focused agent context is exactly right, so use the original one-context loop.
    - **whole app** (``task.unit`` is None): document each unit in its OWN fresh context
      via ``_run_whole_app_per_unit`` — so a large app never fills a single context and
      thrashes (the large-app failure mode). Each document still gets the same tools, prompt,
      and gates, so quality is unchanged."""
    if task.unit:
        return _run_single_unit(task, max_repairs, agent_callback)
    return _run_whole_app_per_unit(task, agent_callback)


def _run_single_unit(task: RequirementTask, max_repairs: int = 2,
                     agent_callback=None) -> BoundaryOutcome:
    """The original one-context loop — correct for a single-unit (feedback) rerun, which
    owes exactly its one unit. Requires the Strands runtime (drives the loop)."""
    from spec_agent.agent import build_agent, task_prompt
    from spec_agent.render import render_set
    from spec_agent.run_log import RunLogger, tee
    from spec_agent.tools import build_requirement_set

    facts = AnalyzerFacts.from_file(task.analyzer_output, worksheet=getattr(task, 'worksheet', ''))
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
            fb = feedback_gate(req_set, task.workspace_dir, task.feedback)
            st = story_gate(req_set, facts)
            # Single-unit rerun owes exactly its one unit; whole-app owes everything.
            gaps = (single_unit_gap(task.unit, req_set) if task.unit
                    else coverage_gap(facts, req_set))
            reasons = g.reasons + d.reasons + fb.reasons + st.reasons
            if gaps:
                shown = ", ".join(gaps[:30]) + (f" … (+{len(gaps) - 30} more)"
                                                if len(gaps) > 30 else "")
                reasons.append("These analyzer units are unaccounted for — document each "
                               "(start_unit/write_section/finish_unit), or mark its entity "
                               f"type not-a-unit with skip_type and a reason: {shown}")

            if g.ok and d.ok and fb.ok and st.ok and not gaps:
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
        gaps = single_unit_gap(task.unit, last) if task.unit else coverage_gap(facts, last)
        return BoundaryOutcome(delivered=False, requirement_set=last,
                               attempts=max_repairs + 1, gate_reasons=reasons,
                               coverage_gaps=gaps, markdown_files=md, routed_to_human=True)
    finally:
        log.close()


# The journey-first design's documentable units: the analyzer's journey pass emits
# Journey and BehaviorGroup entities as the things that get a spec; every other type is a
# member covered inside them. Structural to the design — not app-specific.
PRIMARY_TYPES = ("Journey", "BehaviorGroup")


def _unit_problems(entry, facts: AnalyzerFacts) -> List[str]:
    """The specific gate failures for one documented entry — the exact fixes to feed back
    on a per-unit repair. Pure (grounding + story)."""
    probs: List[str] = []
    bad_names = [n for n in entry.grounded_identifiers if not facts.resolve(n)]
    if bad_names:
        probs.append("When you call finish_unit, its grounded_identifiers must contain ONLY names "
                     "that read_facts actually returned. Drop these — they are NOT in the facts "
                     "(you may still name them in the prose sections, just not as grounded ids): "
                     + ", ".join(bad_names[:12]))
    if entry.unit.startswith("Journey:") and not (set(entry.grounded_identifiers)
                                                  & facts.observable_objects()):
        probs.append("Ground at least one OBSERVABLE outcome (a table, object, endpoint, or "
                     "workflow the chain actually produces), not just code names.")
    return probs


def _failing_units(req_set: RequirementSet, facts: AnalyzerFacts, workspace_dir: str) -> set:
    """Documented units whose doc fails grounding, story, or doc-validity — the set the
    per-unit repair pass must redo (each again in its own fresh context)."""
    bad = set(doc_validity_gate(req_set, workspace_dir).rejected)
    for e in req_set.entries:
        if e.status == "documented" and _unit_problems(e, facts):
            bad.add(e.unit)
    return bad


def _run_whole_app_per_unit(task: RequirementTask, agent_callback=None,
                            per_unit_retries: int = 1) -> BoundaryOutcome:
    """Document a whole app WITHOUT ever holding it all in one context: an orchestrator
    walks the unit list and runs ONE fresh agent per unit (fresh conversation, shared emit
    accumulator). Each document gets the same tools, prompt, and gates, so quality is
    unchanged; only the context resets between units, which removes the size ceiling. No
    per-app anything is hardcoded — the worklist is the analyzer's own units."""
    from spec_agent.agent import build_agent, single_unit_doc_prompt
    from spec_agent.render import render_set
    from spec_agent.run_log import RunLogger, tee
    from spec_agent.tools import build_requirement_set, reset_emit
    from spec_agent.tools.emit import record_skip

    facts = AnalyzerFacts.from_file(task.analyzer_output, worksheet=getattr(task, 'worksheet', ''))
    log = RunLogger(
        os.path.join(task.workspace_dir, "agent_log.txt"),
        header=(f"# Automated AI Platform spec agent — per-unit orchestration\n# app: {task.app_id}\n"),
    )
    try:
        # ONE reset for the whole run; the accumulator then persists across the fresh
        # per-unit agents below (each built with reset_emit_state=False).
        reset_emit(task.workspace_dir, task.app_id, facts=facts,
                   source_available=bool(task.codebase),
                   feedback_ids=[f.id for f in task.feedback])

        primary = [uid for uid in facts.unit_ids()
                   if (facts.entity(uid).type if facts.entity(uid) else "") in PRIMARY_TYPES]
        source_note = ("" if task.codebase else
                       " (No raw source provided — ground from read_facts only.)")

        print(f"[per-unit] {len(primary)} units to document, one fresh context each", flush=True)
        for idx, uid in enumerate(primary, 1):
            for _ in range(per_unit_retries + 1):
                agent = build_agent(task, callback=tee(log.callback, agent_callback),
                                    reset_emit_state=False)
                agent(single_unit_doc_prompt(uid, source_note))
                if any(e.unit == uid for e in build_requirement_set().entries):
                    break                       # this unit emitted — next
            done = len(build_requirement_set().entries)
            print(f"[per-unit] {idx}/{len(primary)}  {uid}  (documented so far: {done})", flush=True)

        # Member types (not primary units) are documented INSIDE the journeys/groups that
        # contain them — record that deterministically so coverage is honest and complete,
        # without spending a model turn (same effect as the agent calling skip_type).
        member_types = sorted({(facts.entity(u).type if facts.entity(u) else "Unknown")
                               for u in facts.unit_ids()} - set(PRIMARY_TYPES) - {"Unknown"})
        for t in member_types:
            record_skip(t, "documented within the journey / behavior-group specs that contain "
                           "it — a member of a chain, not an independent unit")

        # Bounded per-unit repair: re-run ONLY the units whose document failed a gate, each
        # again in its own fresh context with the specific findings. Same repair discipline
        # as the single-context path, but scoped so one over-claimed name never routes the
        # whole app to a human.
        for _round in range(2):
            bad = _failing_units(build_requirement_set(), facts, task.workspace_dir)
            if not bad:
                break
            print(f"[per-unit] repairing {len(bad)} unit(s) that failed a gate", flush=True)
            for uid in sorted(bad):
                e = next((x for x in build_requirement_set().entries if x.unit == uid), None)
                probs = _unit_problems(e, facts) if e else ["re-document this unit accurately"]
                agent = build_agent(task, callback=tee(log.callback, agent_callback),
                                    reset_emit_state=False)
                agent(single_unit_doc_prompt(uid, source_note)
                      + "\n\nYour previous document for this unit FAILED the boundary. Fix ONLY "
                        "these and write the document again:\n- " + "\n- ".join(probs))

        # Gates over the assembled set (identical checks as the single-context path).
        req_set = build_requirement_set()
        g = grounding_gate(req_set, facts)
        d = doc_validity_gate(req_set, task.workspace_dir)
        st = story_gate(req_set, facts)
        gaps = coverage_gap(facts, req_set)
        reasons = g.reasons + d.reasons + st.reasons
        if gaps:
            shown = ", ".join(gaps[:30]) + (f" … (+{len(gaps) - 30} more)" if len(gaps) > 30 else "")
            reasons.append(f"Units still unaccounted for: {shown}")

        md = render_set(task.workspace_dir, _documented_docs(req_set))
        _write_manifest(task.workspace_dir, req_set)
        delivered = g.ok and d.ok and st.ok and not gaps
        return BoundaryOutcome(
            delivered=delivered, requirement_set=req_set, attempts=1,
            gate_reasons=[] if delivered else reasons,
            coverage_gaps=gaps, markdown_files=md, routed_to_human=not delivered)
    finally:
        log.close()
