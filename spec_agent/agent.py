"""
Agent assembly — builds the autonomous Strands + Bedrock requirement agent.

Mirrors the coding agent's "autonomous agent inside a deterministic boundary" shape,
but the document is assembled **incrementally** so it can be any size: the agent never
writes a whole document in one response — it emits sections one at a time through the
emit tools, and plain code assembles + validates + writes the file. Document size is
therefore decoupled from ``max_tokens``.

Tools (no general file/shell built-ins — documents go only through the emit tools, and
the source is read-only):
  - grounding:  list_units, read_facts            (the analyzer output)
  - navigation: read_source, search_source, list_source   (the RAW source, read-only)
  - emission:   start_unit, write_section, finish_unit, skip_type

Connection values come from ``.env`` via ``config`` — never hardcoded. The analyzer
facts, the raw-source pointer, and the emit accumulator are reset/injected once per run.
"""
from __future__ import annotations

from spec_agent.prompts import SYSTEM_PROMPT
from spec_agent.schemas import RequirementTask


def domain_tools() -> list:
    """The full tool surface the agent sees. Grounding + read-only navigation +
    incremental emission. All degrade to an actionable note when their source isn't
    configured, so they are always safe to expose."""
    from spec_agent.tools import (list_units, read_facts,
                                         read_source, search_source, list_source,
                                         start_unit, write_section, finish_unit, skip_type)
    return [list_units, read_facts,
            read_source, search_source, list_source,
            start_unit, write_section, finish_unit, skip_type]


# --- the prompt that frames one task ---------------------------------------

def task_prompt(task: RequirementTask) -> str:
    """The per-run user message: the app, how to discover the work, and the emit flow.
    Two modes, chosen by the task (never by parsing prose): whole-app discovery, or a
    single-unit rerun applying reviewer feedback."""
    src = (" The application's raw source is available via list_source / search_source "
           "/ read_source whenever the analyzer facts are not enough to state a behavior."
           if task.codebase else
           " (No raw source was provided — ground from list_units / read_facts only.)")
    if task.unit:
        fb_lines = "".join(
            f"  - [feedback_id {f.id}] {f.action}"
            + (f" ({f.target})" if f.target else "")
            + (f" by {f.reviewer}" if f.reviewer else "")
            + (f": {f.comment}" if f.comment else "") + "\n"
            for f in task.feedback
        ) or "  (none — regenerate from the current facts.)\n"
        return (
            f"Regenerate the requirement document for ONE unit of application "
            f"'{task.app_id}': {task.unit}\n\n"
            f"Reviewer feedback to apply:\n{fb_lines}\n"
            f"1) Call read_facts('{task.unit}') to ground the unit's real inputs, tables, "
            f"services, and errors.{src}\n"
            f"2) Rebuild its document with start_unit / write_section / finish_unit — all "
            f"nine canonical sections, exactly as in a normal run.\n"
            f"3) For a section you change BECAUSE of a feedback item, pass that item's "
            f"feedback_id to write_section — that is what marks the correction "
            f"human-confirmed. Sections the feedback did not touch get NO feedback_id.\n"
            f"4) If a feedback comment contradicts the analyzer facts and the source, say "
            f"so in the Gap Analysis section instead of writing something false — honesty "
            f"outranks compliance.\n\n"
            f"Document only this unit. Do not document or skip anything else."
        )
    return (
        f"Document the requirements of application '{task.app_id}'.\n\n"
        f"1) DISCOVER — call list_units to see every unit, grouped by type. The units to "
        f"document are the functional entry points (handlers, step functions, endpoints, "
        f"ETL workflows). For a whole type that is not an independent unit (e.g. internal "
        f"helper Functions), call skip_type(type, reason) instead of documenting each member.\n"
        f"2) For each functional unit: call read_facts(unit) to ground its real inputs, "
        f"tables, services, and errors, then build its document INCREMENTALLY — "
        f"start_unit, then write_section for each of the nine canonical sections (append "
        f"as much as you need; there is no size limit), then finish_unit with the real "
        f"names you used. Every behavior is code-derived (no numeric confidence) — say so.\n"
        f"3) GROUND — never invent a name; if the facts are unclear, read the source.{src}\n\n"
        f"Account for EVERY entity from list_units: documented, or covered by a skip_type. "
        f"You decide the order; recover from any tool error yourself. An honest, grounded "
        f"doc is the goal — a confident fabrication is the worst possible output."
    )


# --- assembly (requires Strands) -------------------------------------------

def single_unit_doc_prompt(unit_id: str, source_note: str = "") -> str:
    """Initial documentation of ONE unit in its own fresh context (the per-unit
    orchestration path). Deliberately narrow and anti-thrash: read this unit's facts,
    write its document, stop — no planning, no token talk, nothing else."""
    return (
        f"Document exactly ONE unit and nothing else: {unit_id}\n\n"
        f"1) Call read_facts('{unit_id}') to ground this unit's real inputs, tables, S3 paths, "
        f"endpoints, and — for a journey — the whole chain it drives.\n"
        f"2) Write its document now: start_unit('{unit_id}'), then write_section for each of the "
        f"nine canonical sections (append as much as you need; there is no size limit), then "
        f"finish_unit('{unit_id}') with the real grounded identifiers.\n\n"
        f"Do NOT discuss a plan. Do NOT mention token counts. Do NOT document or skip anything "
        f"else. Just read the facts and write this one document.{source_note}"
    )


def build_agent(task: RequirementTask, *, callback=None, reset_emit_state: bool = True):
    """Construct the Strands Agent for one task. Requires the Strands runtime.

    Injects the analyzer facts + raw-source pointer for this run (built from the task, not
    hardcoded). ``callback`` (optional) streams the agent's tool calls / reasoning to the
    run log. ``reset_emit_state`` clears the shared emit accumulator — TRUE for a
    standalone run, FALSE when an orchestrator builds one fresh agent per unit and wants
    the docs to accumulate across those fresh contexts (it resets once, itself)."""
    from strands import Agent  # type: ignore
    from strands.models import BedrockModel  # type: ignore

    from spec_agent.config import bedrock_settings
    from spec_agent.facts import AnalyzerFacts
    from spec_agent.tools import set_facts, set_source, reset_emit

    # Per-run state. The facts are shared with the emit tools so finish_unit can compute an
    # honest, per-unit grounding descriptor. The emit accumulator is reset here ONLY when
    # this agent owns the whole run; the per-unit orchestrator passes reset_emit_state=False
    # so each fresh agent adds to (never wipes) the accumulated set.
    facts = AnalyzerFacts.from_file(task.analyzer_output, worksheet=getattr(task, 'worksheet', ''))
    set_facts(facts)
    set_source(task.codebase)
    if reset_emit_state:
        reset_emit(task.workspace_dir, task.app_id, facts=facts,
                   source_available=bool(task.codebase),
                   feedback_ids=[f.id for f in task.feedback])

    bedrock = bedrock_settings()
    # max_tokens is the per-response cap. It no longer governs document size (docs are
    # written section-by-section via the emit tools, never as one response), so this is
    # pure headroom for the agent's reasoning + tool calls. 64K is well under the model's
    # 128K ceiling and is only billed if actually generated. Streaming is on (Strands
    # uses the Bedrock streaming API) so a large response never hits an HTTP timeout.
    model_kwargs = dict(model_id=bedrock["model_arn"], region_name=bedrock["region"],
                        max_tokens=64000)
    try:
        model = BedrockModel(streaming=True, **model_kwargs)
    except TypeError:
        # Older Strands without an explicit ``streaming`` kwarg already streams by default.
        model = BedrockModel(**model_kwargs)

    kw = {"callback_handler": callback} if callback is not None else {}
    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=domain_tools(),
        **kw,
    )
    return agent
