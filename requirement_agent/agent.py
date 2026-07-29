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

from requirement_agent.prompts import SYSTEM_PROMPT
from requirement_agent.schemas import RequirementTask


def domain_tools() -> list:
    """The full tool surface the agent sees. Grounding + read-only navigation +
    incremental emission. All degrade to an actionable note when their source isn't
    configured, so they are always safe to expose."""
    from requirement_agent.tools import (list_units, read_facts,
                                         read_source, search_source, list_source,
                                         start_unit, write_section, finish_unit, skip_type)
    return [list_units, read_facts,
            read_source, search_source, list_source,
            start_unit, write_section, finish_unit, skip_type]


# --- the prompt that frames one task ---------------------------------------

def task_prompt(task: RequirementTask) -> str:
    """The per-run user message: the app, how to discover the work, and the emit flow."""
    src = (" The application's raw source is available via list_source / search_source "
           "/ read_source whenever the analyzer facts are not enough to state a behavior."
           if task.codebase else
           " (No raw source was provided — ground from list_units / read_facts only.)")
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

def build_agent(task: RequirementTask, *, callback=None):
    """Construct the Strands Agent for one task. Requires the Strands runtime.

    Resets the emit accumulator and injects the analyzer facts + raw-source pointer for
    this run (built from the task, not hardcoded). ``callback`` (optional) streams the
    agent's tool calls / reasoning to the run log."""
    from strands import Agent  # type: ignore
    from strands.models import BedrockModel  # type: ignore

    from requirement_agent.config import bedrock_settings
    from requirement_agent.facts import AnalyzerFacts
    from requirement_agent.tools import set_facts, set_source, reset_emit

    # Per-run state (fresh each run; never leaks across runs). The facts are shared with
    # the emit tools so finish_unit can compute an honest, per-unit grounding descriptor.
    facts = AnalyzerFacts.from_file(task.analyzer_output)
    set_facts(facts)
    set_source(task.codebase)
    reset_emit(task.workspace_dir, task.app_id, facts=facts,
               source_available=bool(task.codebase))

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
