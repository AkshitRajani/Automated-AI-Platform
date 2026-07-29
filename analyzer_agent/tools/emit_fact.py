"""
``emit_fact`` — the agent's only write. Structured, never freeform prose to scrape.

Each call is routed by the grounding gate (``store.FactStore.emit``): a structural
fact is re-verified at its ``file:line`` before it can reach the graph; an
unverifiable or behavioural fact becomes a pgvector note; a provably wrong one is
rejected. The tool returns the honest destination so the agent learns immediately
whether its claim held up.
"""
from __future__ import annotations

from typing import Optional

from ._strands import tool
from .context import get_store


@tool
def emit_fact(
    subject: str,
    predicate: str,
    object: str,
    file: str,
    line: Optional[int] = None,
    kind: str = "fact",
    note: str = "",
) -> str:
    """Record one discovered relationship. It is verified against the source before
    it is kept — so always pass the exact ``file`` and ``line`` where it is visible.

    Args:
        subject: the enclosing unit, as a canonical ``Type:qualified-name`` id
            (e.g. ``Function:web.app.topology.build_topology``). Use the ids from
            repo_map / parser_facts so the edge connects in the graph.
        predicate: the relationship — CALLS, INVOKES_LAMBDA, INVOKES_STEP_FUNCTION,
            READS_FROM_S3, WRITES_TO_S3, QUERIES_DATABASE, WRITES_DATABASE,
            READS_ENV_VAR, EXPOSES_ENDPOINT, FEEDS (data lineage), DEFINES.
        object: a canonical id (for CALLS/FEEDS/DEFINES) or the resource literal
            (a table name, an S3 path, an endpoint, an env var).
        file: path (relative to the repo root) where this is visible.
        line: the line number where it is visible — required for verification.
        kind: "fact" (structural, verified -> graph) or "note" (plain-English flow
            / runtime behaviour with no single symbol -> pgvector).
        note: for kind="note", the plain-English description of the flow.

    Returns:
        A short string: where the fact went ("graph" / "note" / "rejected") and why.
    """
    from ..store import EmittedFact

    dest, why = get_store().emit(EmittedFact(
        subject=subject, predicate=predicate, object=object,
        file=file, line=line, kind=kind, note=note,
    ))
    return f"[{dest}] {why}"
