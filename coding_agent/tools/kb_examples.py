"""
``kb_examples`` — fetch reviewer-APPROVED artifacts for reference.

The long-term half of the feedback loop (final_design/08_feedback_loop.md §3): artifacts a
human approved are stored in the KB (``app_embeddings`` rows, kind='approved_example') and
retrieved — capped, most-relevant-first — as style/convention reference when generating for
a similar unit. Retrieval only; nothing is stuffed into the prompt wholesale, and an
example is never a substitute for grounding this unit's own names.

Reuses the same shared KBClient as kb_query / kb_requirements (injected via ``set_client``
in agent assembly, or built lazily from ``.env``).
"""
from __future__ import annotations

from coding_agent.kb.facts import ExamplesResult
from coding_agent.tools._strands import tool
from coding_agent.tools.kb_query import _get_client


@tool
def kb_examples(app_id: str, unit: str) -> ExamplesResult:
    """Fetch up to 2 reviewer-approved test artifacts to use as style reference.

    Call this once per unit BEFORE writing its tests: an approved example shows the
    conventions a human reviewer already signed off on (naming, tagging, assertion style)
    — match them. Examples are REFERENCE ONLY: every name in your test still needs
    kb_query grounding for THIS unit, and an example never overrides the unit's own
    requirement doc. If ``found`` is false there are no approvals yet — proceed normally.

    Args:
        app_id: the application (required).
        unit: the unit you are about to test, exactly as listed by kb_inventory (required).
    """
    return _get_client().approved_examples(app_id, unit)
