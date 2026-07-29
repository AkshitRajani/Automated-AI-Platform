"""
``kb_graph`` — walk the Neptune dependency/lineage graph.

Thin wrapper over ``coding_agent.kb.graph.GraphClient``. The client is built
once from ``.env`` (lazily); when Neptune is not configured it degrades to an
actionable empty result (slice 1 treats Neptune as optional).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from coding_agent.kb.graph import GraphClient, GraphResult
from coding_agent.tools._strands import tool

_graph_client: Optional[GraphClient] = None


def set_graph_client(client: Optional[GraphClient]) -> None:
    """Inject the GraphClient (or a fake in tests)."""
    global _graph_client
    _graph_client = client


def _get_client() -> GraphClient:
    global _graph_client
    if _graph_client is None:
        _graph_client = GraphClient.from_env()
    return _graph_client


@tool
def kb_graph(
    start: str,
    relations: List[str] = [],
    hops: int = 1,
    direction: Literal["out", "in", "both"] = "out",
    app_id: str = "",
    limit: int = 25,
) -> GraphResult:
    """Walk the dependency/lineage graph from a node when a flat lookup isn't enough.

    Use it to disambiguate ("which table does this function actually read?"), to recover
    when kb_query is empty (traverse to the name another way), or to find data lineage
    ("who feeds this table?", "what does this endpoint reach?").

    Args:
        start: a canonical node name (function, endpoint, table, app).
        relations: edge types to follow; [] follows all. Backed: CONTAINS, DEFINES,
            EXPOSES_ENDPOINT, CALLS_HTTP_API, INVOKES_LAMBDA, INVOKES_STEP_FUNCTION,
            PUBLISHES_TO_SNS, WRITES_DATABASE, QUERIES_DATABASE, READS_DYNAMODB_TABLE,
            WRITES_DYNAMODB_TABLE, READS_FROM_S3, WRITES_TO_S3, READS_CONFIG_FROM_S3,
            HAS_JPA_RELATIONSHIP, READS_SSM_PARAMETER, READS_ENV_VAR.
        hops: traversal depth (keep small; 1–2).
        direction: "out" (what this calls), "in" (who calls this), "both".
        app_id: scope to one application.
        limit: max edges returned.
    """
    return _get_client().walk(
        start, relations=relations, hops=hops, direction=direction,
        app_id=app_id, limit=limit,
    )
