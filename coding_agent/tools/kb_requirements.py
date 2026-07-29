"""
``kb_requirements`` — fetch a unit's requirement doc from the KB.

What a unit is SUPPOSED to do (system overview, I/O contract, the requirements, the user
stories with Given/When/Then acceptance criteria including the negative paths). This is the
behaviour layer the coding agent tests against — without it the agent can only assert that
output lands in the right place, not that the unit behaves correctly.

Exact lookup by unit id (the agent already has the id from kb_inventory), so it reuses the
same shared KBClient the kb_query / kb_inventory tools use (injected via ``set_client`` in
agent assembly, or built lazily from ``.env``).
"""
from __future__ import annotations

from coding_agent.kb.facts import RequirementContract
from coding_agent.tools._strands import tool
from coding_agent.tools.kb_query import _get_client


@tool
def kb_requirements(app_id: str, unit: str) -> RequirementContract:
    """Fetch the requirement doc for one unit — what it is supposed to do.

    Call this for each functional unit BEFORE writing its tests: it returns the unit's
    behaviour contract (overview, inputs/outputs, requirements, and user stories with
    Given/When/Then acceptance criteria — including the negative / failure paths). Generate
    one scenario per acceptance criterion, and ground every name with kb_query.

    Read ``requirement_backed`` to decide how to assert:
      - true  → a real requirement backs it; assert the described behaviour as the oracle.
      - false → code-derived; use it to choose scenarios (incl. negative paths) but assert
        only the grounded shape/location and tag the behavioural assertion @needs-requirement.
    The ``note`` field restates this rule for the returned doc. If ``found`` is false, no doc
    exists — test from KB facts and tag @needs-requirement rather than inventing behaviour.

    Args:
        app_id: the application the unit belongs to (required).
        unit: the unit's canonical id, exactly as listed by kb_inventory (required).
    """
    return _get_client().requirements(app_id, unit)
