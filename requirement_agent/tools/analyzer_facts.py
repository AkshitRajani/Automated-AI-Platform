"""
``list_units`` / ``read_facts`` — the agent's grounding surface at onboarding.

These read the analyzer's output (a quad file) — the onboarding-time analogue of the
coding agent's ``kb_inventory`` / ``kb_query`` (there is no live KB yet). The loaded
``AnalyzerFacts`` is injected once via ``set_facts``; both tools degrade to an
actionable note if it was never set, so they are always safe to expose.

Everything these tools surface is a REAL name. The agent must ground every name it
writes into a requirement doc against them — anything not here is not real.
"""
from __future__ import annotations

from typing import Optional

from requirement_agent._strands import tool
from requirement_agent.facts import AnalyzerFacts

_facts: Optional[AnalyzerFacts] = None


def set_facts(facts: Optional[AnalyzerFacts]) -> None:
    """Inject the loaded analyzer facts for this run (shared across tool calls)."""
    global _facts
    _facts = facts


@tool
def list_units() -> str:
    """List the application's testable units, grouped by type, from the analyzer.

    Call this FIRST to discover what to document. The functional units to write
    requirement docs for are the entry points — Lambda handlers, step functions,
    API endpoints, and ETL workflows. Internal helper functions are usually NOT
    units on their own (mark such a whole type not-a-unit instead of documenting
    each member). You decide which groups are units; this only reports what exists.
    """
    if _facts is None:
        return "No analyzer output configured. Cannot list units."
    inv = _facts.inventory()
    if inv.note:
        return inv.note
    lines = [f"Application '{inv.app_id}' — testable surface (from the analyzer):"]
    for etype, ids in inv.groups.items():
        # No cap — the agent must see every unit, or it cannot account for them all.
        lines.append(f"  {etype} ({len(ids)}): {', '.join(ids)}")
    if inv.endpoints:
        lines.append(f"  Endpoints ({len(inv.endpoints)}): {', '.join(inv.endpoints)}")
    lines.append("Document one requirement doc per FUNCTIONAL unit; ground every name "
                 "you write via read_facts. Mark non-unit types (e.g. internal helpers) "
                 "as skipped_types with a reason.")
    return "\n".join(lines)


@tool
def read_facts(unit: str) -> str:
    """Read what one unit touches, from the analyzer: its quads (predicate → object)
    and where it lives in source. Use this to state a unit's real behavior and
    interface — every object returned is a REAL name you may use in the doc.

    Args:
        unit: the canonical id of the unit (as listed by list_units).
    """
    if _facts is None:
        return "No analyzer output configured. Cannot read facts."
    ent = _facts.entity(unit)
    facts = _facts.facts_for(unit)
    if ent is None and not facts:
        return (f"'{unit}' is not an entity in the analyzer output, and has no facts. "
                f"Use list_units to find the real unit ids.")
    lines = []
    if ent is not None:
        loc = f"{ent.file_path}:{ent.line}" if ent.file_path else "(no source)"
        lines.append(f"Unit: {ent.id}  [{ent.type}]  {loc}")
    else:
        lines.append(f"Unit: {unit}  [subject of quads; not a top-level entity]")
    if facts:
        lines.append("Facts (what it touches — these objects are REAL names):")
        for f in facts:
            flag = "" if f.resolved else "  (unresolved token)"
            lines.append(f"  {f.predicate} -> {f.object}{flag}")
    else:
        lines.append("No quads recorded for this unit. Read the raw source "
                     "(list_source / search_source / read_source) to understand it.")
    return "\n".join(lines)
