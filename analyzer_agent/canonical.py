"""
Canonical identity — the single source of the id scheme, shared with ingestion.

The agent's edges are worthless unless their endpoints are the **same ids** as the
nodes ingestion writes. ``ingestion/graph/neptune_writer`` builds:

    node id      = f"{app_id}:{entity.type}:{entity.name}"
    edge endpoint = f"{app_id}:{quad.subject}"   (and  f"{app_id}:{quad.object}")

So for an edge to connect, ``quad.subject`` / ``quad.object`` must be a
``"Type:qualified-name"`` id — *not* a file path. That is exactly the SCIP/Kythe
principle in MASTER_DESIGN §5.1.1: ids derived from program structure, move-stable
(no path/line inside), so a reference resolves to the same id as its definition.

This module is the contract. ``test_canonical`` asserts it against the real
``neptune_writer`` f-strings, so the two can never silently drift apart.
"""
from __future__ import annotations

from typing import Tuple

# The structural id types the grounding gate (analyzer.verify) recognises.
TYPES = {
    "Module", "Class", "Function", "Method", "Symbol",
    "Table", "S3Object", "Parameter", "APIEndpoint",
    "LambdaFunction", "StateMachine", "Step", "Dataframe", "WorkflowFile",
}


def canonical_id(type_: str, qualified_name: str) -> str:
    """Build a ``Type:qualified-name`` id. An unknown type degrades to ``Symbol:``
    (honestly marked for the agent's LSP to finish) rather than guessing."""
    t = type_ if type_ in TYPES else "Symbol"
    return f"{t}:{qualified_name}"


def node_id(app_id: str, type_: str, qualified_name: str) -> str:
    """The full graph node id — exactly ingestion's ``write_nodes`` scheme."""
    return f"{app_id}:{canonical_id(type_, qualified_name)}"


def edge_endpoint(app_id: str, canonical: str) -> str:
    """The full graph endpoint id — exactly ingestion's ``write_edges`` scheme:
    it prefixes ``{app_id}:`` onto a canonical ``Type:name`` subject/object."""
    return f"{app_id}:{canonical}"


def split(canonical: str) -> Tuple[str, str]:
    """``"Function:web.app.main.health"`` -> ``("Function", "web.app.main.health")``.
    A bare name (no recognised type prefix) is treated as a ``Symbol``."""
    if ":" in canonical:
        head, rest = canonical.split(":", 1)
        if head in TYPES:
            return head, rest
    return "Symbol", canonical


def is_canonical(value: str) -> bool:
    """True if ``value`` is a ``Type:name`` id with a recognised type."""
    return ":" in value and value.split(":", 1)[0] in TYPES
