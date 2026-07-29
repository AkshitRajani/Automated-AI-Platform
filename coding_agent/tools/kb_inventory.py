"""
``kb_inventory`` — list the application's testable surface from the KB.

Whole-app discovery: the agent calls this FIRST to see everything the app contains,
grouped by entity type, plus its endpoints. It reports whatever the parser recorded
(no fixed set of types is assumed), so the agent — not this tool — decides which
groups are functional units to test (workflows / pipelines / handlers / endpoints)
and which are internal helpers to skip.

Reuses the same shared KBClient the ``kb_query`` tool uses (injected via
``set_client`` in agent assembly, or built lazily from ``.env``).
"""
from __future__ import annotations

from coding_agent.kb.facts import KBInventory
from coding_agent.tools._strands import tool
from coding_agent.tools.kb_query import _get_client


@tool
def kb_inventory(app_id: str, per_type_limit: int = 100) -> KBInventory:
    """List the application's full inventory from the KB to discover what to test.

    Call this FIRST in whole-app mode. Returns every entity grouped by its type
    (e.g. WorkflowFile, LambdaHandler, StepFunctionStateMachine, Function, …) with
    counts and names, plus the API endpoints. Your functional test targets are the
    journeys / workflows / pipelines / service entry points — not the plain internal
    functions. Ground each name with kb_query before you write it.

    Args:
        app_id: the application to inventory (required).
        per_type_limit: max names listed per entity type.
    """
    return _get_client().inventory(app_id, per_type_cap=per_type_limit)
