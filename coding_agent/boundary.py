"""
The deterministic boundary (orchestrator, no LLM) around the autonomous agent.

This is the "cage": the agent navigates freely; these walls are plain code.

  1. Grounding gate — every identifier the agent emitted is re-checked against
     the KB. An ungrounded name is rejected (the structural cure for
     hallucinated identifiers + the cheap fix for the reproducibility wobble).
  2. Static gate — lint the written step files (ERROR findings block delivery).
  3. Bounded repair — on failure, inject the findings as the agent's next turn,
     at most ``max_repairs`` times, then route to a human (confidence 0).

The external Eval (real-invocation / coverage / mutation) is a *separate*
component and is intentionally NOT reachable as a tool; this module is where it
would be invoked once built. For slice 1 the boundary runs the grounding gate
and the static lint gate.

The grounding gate is pure and unit-tested with an injected KB client; the
repair loop drives the Strands agent and therefore needs the runtime.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from pydantic import BaseModel

from coding_agent.kb.facts import FACT_SOURCES, KBClient, KBInventory
from coding_agent.schemas import AgentTask, GroundedId, TestBundle, TestSuite


class GateResult(BaseModel):
    ok: bool
    confirmed: List[GroundedId] = []
    rejected: List[GroundedId] = []     # emitted but NOT found in the KB → ungrounded
    reasons: List[str] = []


def _ground_ids(ids: List[GroundedId], app_id: str, kb: KBClient) -> GateResult:
    """Re-verify a list of emitted identifiers exist in the KB for ``app_id``.

    A name is *confirmed* only if the KB returns it as an exact, resolved
    candidate; otherwise it is *rejected* as ungrounded. Pure: the KB client is
    injected, so this is fully testable without a live DB."""
    confirmed: List[GroundedId] = []
    rejected: List[GroundedId] = []
    reasons: List[str] = []

    for gid in ids:
        kind = gid.kind if gid.kind in FACT_SOURCES else "any"
        result = kb.resolve(gid.name, kind=kind, app_id=app_id, limit=10)
        match = next(
            (c for c in result.candidates
             if c.canonical_name == gid.name and c.resolved),
            None,
        )
        if match:
            confirmed.append(gid)
        else:
            rejected.append(gid)
            reasons.append(
                f"'{gid.name}' ({gid.kind}) was emitted but is not a resolved name "
                f"in the KB for {app_id} — ungrounded."
            )

    return GateResult(ok=not rejected, confirmed=confirmed,
                      rejected=rejected, reasons=reasons)


def grounding_gate(bundle: TestBundle, app_id: str, kb: KBClient) -> GateResult:
    """Grounding gate over a single per-change TestBundle."""
    return _ground_ids(bundle.grounded_identifiers, app_id, kb)


def grounding_gate_suite(suite: TestSuite, app_id: str, kb: KBClient) -> GateResult:
    """Grounding gate over a whole-app TestSuite — every identifier across every
    tested entry must resolve in the KB."""
    ids = [gid for e in suite.entries for gid in e.grounded_identifiers]
    return _ground_ids(ids, app_id, kb)


# --- coverage check (#5): did the suite account for the whole app? ----------

def coverage_gap(inventory: KBInventory, suite: TestSuite,
                 chain_members: Optional[dict] = None) -> List[str]:
    """Deterministic: units in the KB inventory that the suite did NOT account for —
    neither given a test, nor covered by a not-testable verdict, nor exercised
    through an accounted chain. Pure, no LLM.

    The denominator is the KB (endpoints + every entity name), minus any entity
    *type* the agent explicitly declared not-testable, minus anything the KB's own
    membership facts (``chain_members``: Journey/BehaviorGroup id -> member ids)
    place inside a chain the suite accounted for — a brick tested through its
    journey is covered by the journey, not owed a test of its own. Nothing about
    *which* units matter is hardcoded — the agent makes the testable/skip call;
    this only enforces that every unit was accounted for."""
    accounted = {e.unit for e in suite.entries}            # tested or individually skipped
    skipped_types = {st.entity_type for st in suite.skipped_types}

    # everything inside an ACCOUNTED chain is covered by that chain
    covered_ids: set = set()
    for chain, members in (chain_members or {}).items():
        if chain in accounted:
            covered_ids |= set(members)

    gaps: set = set()
    for endpoint in inventory.endpoints:                    # "METHOD path" form
        if endpoint in accounted or f"APIEndpoint:{endpoint}" in covered_ids:
            continue
        gaps.add(endpoint)
    for g in inventory.groups:
        if g.entity_type in skipped_types:
            continue                                        # whole type declared not-testable
        for name in g.names:
            if name in accounted:
                continue
            if name in covered_ids or f"{g.entity_type}:{name}" in covered_ids:
                continue                                    # exercised through its chain
            gaps.add(name)
    return sorted(gaps)


def single_unit_gap(unit: str, suite: TestSuite) -> List[str]:
    """Coverage for a single-unit rerun: THAT unit must be TESTED (a skip does not
    satisfy a regeneration); nothing else is owed. Pure — a worklist of one."""
    for e in suite.entries:
        if e.unit == unit and e.status == "tested":
            return []
    return [unit]


def feedback_gate(suite: TestSuite, feedback) -> "GateResult":
    """Closure: every actionable feedback record passed into the task (reject/comment —
    approve asks for nothing) must be addressed, proven by the manifest entries'
    ``feedback_ids``. Pure — the ids live in the manifest; no DB, no model."""
    owed = {f.id for f in feedback if f.action in ("reject", "comment")}
    if not owed:
        return GateResult(ok=True)
    addressed: set = set()
    for e in suite.entries:
        addressed.update(int(i) for i in e.feedback_ids)
    missing = sorted(owed - addressed)
    if not missing:
        return GateResult(ok=True)
    return GateResult(
        ok=False,
        reasons=[(f"feedback record {i} was not addressed — fix what it asks and list "
                  f"{i} in the unit's feedback_ids in the manifest.") for i in missing],
    )


# --- repair orchestration (drives the Strands agent) -----------------------

class BoundaryOutcome(BaseModel):
    delivered: bool
    bundle: Optional[TestBundle] = None
    attempts: int = 0
    gate_reasons: List[str] = []
    routed_to_human: bool = False


def run_with_boundary(
    task: AgentTask,
    max_repairs: int = 2,
    external_eval: Optional[Callable[[TestBundle], Tuple[bool, List[str]]]] = None,
    agent_callback=None,
) -> BoundaryOutcome:
    """Run the agent, apply the boundary gates, repair up to ``max_repairs``
    times, else route to a human. Requires the Strands runtime (drives the loop).

    Gates: grounding gate + static lint gate, then — if ``external_eval`` is
    supplied — the external Eval (the gate cascade). ``external_eval(bundle)``
    returns ``(ok, reasons)`` and is injected by the orchestrator (``core``), so the
    agent never imports or can reach the eval as a tool. It runs only after the
    cheap gates pass (cheapest-first), and its failure reasons feed the same repair
    loop in the same shape."""
    import os

    from coding_agent.agent import build_agent, task_prompt
    from coding_agent.run_log import RunLogger, tee
    from coding_agent.tools.lint_tests import lint_tests

    kb = KBClient.from_env()
    log = RunLogger(
        os.path.join(task.workspace_dir, "agent_log.txt"),
        header=(f"# Automated AI Platform coding agent — per-change run\n"
                f"# app: {task.scope.app_id}   framework: {task.framework}   "
                f"ticket: {task.ticket_id}\n"),
    )
    try:
        agent = build_agent(task, callback=tee(log.callback, agent_callback))
        prompt = task_prompt(task)
        reasons: List[str] = []
        last_bundle = None       # keep the most recent attempt so a failed run is still inspectable

        for attempt in range(1, max_repairs + 2):  # initial try + up to max_repairs
            # Run the FULL agentic loop (read diff, kb_query grounding, write test
            # files), THEN emit the structured bundle. The old structured_output()
            # short-circuited the loop (Strands >=1.x) and returned an empty bundle.
            result = agent(prompt, structured_output_model=TestBundle)
            bundle = result.structured_output
            if bundle is None:
                reasons = ["agent produced no test bundle"]
                prompt = ("You did not emit a TestBundle. Explore the diff and KB, write "
                          "the test step files, then emit the structured TestBundle.")
                continue
            last_bundle = bundle

            gate = grounding_gate(bundle, task.scope.app_id, kb)
            lint = lint_tests(task.workspace_dir)
            reasons = gate.reasons + [f.message for f in lint.findings if f.severity == "ERROR"]

            eval_ok = True
            if gate.ok and lint.ok and external_eval is not None:
                eval_ok, eval_reasons = external_eval(bundle)   # the gate cascade
                reasons = reasons + list(eval_reasons)

            if gate.ok and lint.ok and eval_ok:
                return BoundaryOutcome(delivered=True, bundle=bundle, attempts=attempt,
                                       gate_reasons=[])

            # Bounded repair: feed structured findings back as the next turn.
            prompt = (
                "Your previous bundle failed the deterministic boundary. Fix exactly "
                "these and re-emit:\n- " + "\n- ".join(reasons)
            )

        # Repairs exhausted → confidence 0, route to a human — but return the last
        # bundle so the failed test is still visible/inspectable in the UI.
        return BoundaryOutcome(delivered=False, bundle=last_bundle, attempts=max_repairs + 1,
                               gate_reasons=reasons, routed_to_human=True)
    finally:
        log.close()
        kb.close()


# --- whole-app suite orchestration (#5 + #6) --------------------------------

class SuiteOutcome(BaseModel):
    delivered: bool
    suite: Optional[TestSuite] = None
    attempts: int = 0
    gate_reasons: List[str] = []
    coverage_gaps: List[str] = []
    routed_to_human: bool = False


def _write_manifest(workspace_dir: str, suite: Optional[TestSuite]) -> None:
    """Write the suite index to ``<workspace>/manifest.json`` (best-effort)."""
    if suite is None:
        return
    import json
    import os
    try:
        path = os.path.join(workspace_dir, "manifest.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(suite.model_dump(), fh, indent=2)
    except OSError:
        pass


def run_suite_with_boundary(
    task: AgentTask,
    max_repairs: int = 2,
    agent_callback=None,
) -> SuiteOutcome:
    """Entry point, dispatched by size of work:

    - **single-unit rerun** (``task.unit`` set — a reviewer-feedback regeneration): one
      focused context is exactly right — use the original one-context loop.
    - **whole app** (``task.unit`` is None): test each unit in its OWN fresh context via
      ``_run_suite_per_unit`` — so a large app never fills one context and thrashes (the
      same failure the spec agent hit on APP). Every unit still gets the same tools,
      prompt, and gates, so quality is unchanged."""
    if task.unit:
        return _run_suite_single_unit(task, max_repairs, agent_callback)
    return _run_suite_per_unit(task, agent_callback)


def _run_suite_single_unit(
    task: AgentTask,
    max_repairs: int = 2,
    agent_callback=None,
) -> SuiteOutcome:
    """The original one-context loop — correct for a single-unit (feedback) rerun, which
    owes exactly its one unit. Requires the Strands runtime (drives the loop).

    (Whole-app mode: the agent discovers units (kb_inventory), writes one
    feature+steps file per testable unit, and emits a ``TestSuite`` manifest. The
    boundary then applies the same gates as per-change plus a **coverage gate**:

      grounding (every emitted name in the KB) · lint (no ERROR step files) ·
      coverage (every KB unit accounted for — tested or a not-testable verdict).

    Any failing gate (including uncovered units) feeds the bounded repair loop; on
    exhaustion the suite is returned with the remaining gaps and routed to a human.
    Determinism stays at the boundary — the agent decides *what* is testable; this
    only checks the accounting. Requires the Strands runtime (drives the loop)."""
    import os

    from coding_agent.agent import build_agent, task_prompt
    from coding_agent.run_log import RunLogger, tee
    from coding_agent.tools.lint_tests import lint_tests

    kb = KBClient.from_env()
    log = RunLogger(
        os.path.join(task.workspace_dir, "agent_log.txt"),
        header=(f"# Automated AI Platform coding agent — whole-app run\n"
                f"# app: {task.scope.app_id}   framework: {task.framework}\n"),
    )
    try:
        agent = build_agent(task, callback=tee(log.callback, agent_callback))
        prompt = task_prompt(task)
        inventory = kb.inventory(task.scope.app_id)   # the coverage denominator (from the KB)
        reasons: List[str] = []
        last_suite: Optional[TestSuite] = None

        chain_members = kb.chain_members(task.scope.app_id)   # journey-aware coverage

        for attempt in range(1, max_repairs + 2):
            result = agent(prompt, structured_output_model=TestSuite)
            suite = result.structured_output
            if suite is None or not suite.entries:
                # An entries-less manifest VALIDATES (the field defaults to []) but
                # means the final emission was truncated or hollow — treat it as
                # missing, never as the last word (this silently zeroed a correct
                # run once: issue C2).
                reasons = ["agent produced no TestSuite entries"]
                prompt = ("Your TestSuite manifest arrived with no entries — it was "
                          "likely cut off. Re-emit the FULL manifest: one entry per "
                          "tested/skipped unit (unit, status, feature_file), plus your "
                          "skipped_types verdicts. Do not re-write the test files; "
                          "only re-emit the manifest.")
                continue
            last_suite = suite

            gate = grounding_gate_suite(suite, task.scope.app_id, kb)
            lint = lint_tests(task.workspace_dir)
            fb = feedback_gate(suite, task.feedback)
            # Single-unit rerun owes exactly its one unit; whole-app owes everything.
            gaps = (single_unit_gap(task.unit, suite) if task.unit
                    else coverage_gap(inventory, suite, chain_members))

            reasons = (gate.reasons + [f.message for f in lint.findings if f.severity == "ERROR"]
                       + fb.reasons)
            if gaps:
                shown = ", ".join(gaps[:30]) + (f" … (+{len(gaps) - 30} more)" if len(gaps) > 30 else "")
                reasons.append(
                    "These KB units are unaccounted for — write a test for each, or mark "
                    f"its entity type not-testable with a reason: {shown}"
                )

            if gate.ok and lint.ok and fb.ok and not gaps:
                _write_manifest(task.workspace_dir, suite)
                return SuiteOutcome(delivered=True, suite=suite, attempts=attempt)

            # Bounded repair: feed the findings (incl. coverage gaps) back.
            prompt = (
                "Your suite failed the deterministic boundary. Fix exactly these and "
                "re-emit the full TestSuite manifest:\n- " + "\n- ".join(reasons)
            )

        _write_manifest(task.workspace_dir, last_suite)
        if last_suite is None:
            gaps = []
        else:
            gaps = (single_unit_gap(task.unit, last_suite) if task.unit
                    else coverage_gap(inventory, last_suite, chain_members))
        return SuiteOutcome(delivered=False, suite=last_suite, attempts=max_repairs + 1,
                            gate_reasons=reasons, coverage_gaps=gaps, routed_to_human=True)
    finally:
        log.close()
        kb.close()


# The journey-first design's testable units: Journey and BehaviorGroup are the things
# that get a test feature; every other type is a member exercised inside them. Structural
# to the design — not app-specific (mirrors the spec agent's PRIMARY_TYPES).
CA_PRIMARY_TYPES = ("Journey", "BehaviorGroup")


def _run_suite_per_unit(task: AgentTask, agent_callback=None, per_unit_retries: int = 1) -> SuiteOutcome:
    """Whole-app testing WITHOUT holding it all in one context: an orchestrator walks the
    journey/group units and runs ONE fresh agent per unit (fresh conversation) that writes
    that unit's feature + steps files and emits a one-entry manifest. The entries are
    accumulated into the full TestSuite; member types are skipped deterministically; the
    same gates (grounding, lint, coverage) run on the assembled suite, with a bounded
    per-unit grounding repair. Peak context is O(1) per unit, so it never overflows — the
    fix for the same one-context failure at scale. Nothing hardcoded: the
    worklist is the KB's own Journey/BehaviorGroup units."""
    import os

    from coding_agent.agent import build_agent, task_prompt
    from coding_agent.run_log import RunLogger, tee
    from coding_agent.schemas import ManifestEntry, SkippedType
    from coding_agent.tools.lint_tests import lint_tests

    kb = KBClient.from_env()
    log = RunLogger(
        os.path.join(task.workspace_dir, "agent_log.txt"),
        header=(f"# Automated AI Platform coding agent — per-unit whole-app run\n"
                f"# app: {task.scope.app_id}   framework: {task.framework}\n"),
    )
    try:
        inventory = kb.inventory(task.scope.app_id)
        chain_members = kb.chain_members(task.scope.app_id)
        primary = [name for g in inventory.groups if g.entity_type in CA_PRIMARY_TYPES
                   for name in g.names]

        def _test_one(uid: str):
            """Run one unit in a fresh context; return its tested entries (unit forced to
            the worklist id so coverage accounting matches)."""
            unit_task = task.model_copy(update={"unit": uid, "feedback": []})
            agent = build_agent(unit_task, callback=tee(log.callback, agent_callback))
            result = agent(task_prompt(unit_task), structured_output_model=TestSuite)
            so = result.structured_output
            out = []
            for e in (so.entries if so else []):
                if e.status == "tested" and (e.feature_file or e.steps_file):
                    e.unit = uid
                    out.append(e)
                    break
            return out

        print(f"[per-unit] {len(primary)} units to test, one fresh context each", flush=True)
        entries: list = []
        for idx, uid in enumerate(primary, 1):
            got = []
            for _ in range(per_unit_retries + 1):
                got = _test_one(uid)
                if got:
                    break
            entries.extend(got)
            print(f"[per-unit] {idx}/{len(primary)}  {uid}  (tested so far: {len(entries)})", flush=True)

        member_types = sorted({g.entity_type for g in inventory.groups} - set(CA_PRIMARY_TYPES))
        skipped = [SkippedType(entity_type=t,
                               reason="exercised inside the journey / behavior-group tests that "
                                      "contain it — a member of a chain, not an independent unit")
                   for t in member_types]
        suite = TestSuite(framework=task.framework, app_id=task.scope.app_id,
                          entries=entries, skipped_types=skipped, provenance="code-derived")

        # Bounded per-unit grounding repair: re-run ONLY units whose emitted names failed
        # to resolve in the KB, each again in a fresh context.
        for _round in range(2):
            g = grounding_gate_suite(suite, task.scope.app_id, kb)
            if g.ok:
                break
            bad_names = {gid.name for gid in g.rejected}
            bad_units = sorted({e.unit for e in suite.entries
                                if any(x.name in bad_names for x in e.grounded_identifiers)})
            if not bad_units:
                break
            print(f"[per-unit] repairing {len(bad_units)} unit(s) failing grounding", flush=True)
            for uid in bad_units:
                fixed = _test_one(uid)
                suite.entries = [e for e in suite.entries if e.unit != uid] + fixed

        gate = grounding_gate_suite(suite, task.scope.app_id, kb)
        lint = lint_tests(task.workspace_dir)
        gaps = coverage_gap(inventory, suite, chain_members)
        reasons = gate.reasons + [f.message for f in lint.findings if f.severity == "ERROR"]
        if gaps:
            shown = ", ".join(gaps[:30]) + (f" … (+{len(gaps) - 30} more)" if len(gaps) > 30 else "")
            reasons.append(f"KB units unaccounted for: {shown}")

        _write_manifest(task.workspace_dir, suite)
        delivered = gate.ok and lint.ok and not gaps
        return SuiteOutcome(delivered=delivered, suite=suite, attempts=1,
                            gate_reasons=[] if delivered else reasons,
                            coverage_gaps=gaps, routed_to_human=not delivered)
    finally:
        log.close()
        kb.close()
