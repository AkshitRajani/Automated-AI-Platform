"""
``kb_query`` — resolve a real identifier from the Knowledge Base.

Thin wrapper over ``coding_agent.kb.facts.KBClient``. The client is built once
from the shared ``.env`` (lazily) and reused across calls; tests / the agent
assembly can inject a shared client via ``set_client``.
"""
from __future__ import annotations

from typing import Literal, Optional

from coding_agent.kb.facts import GroundResult, KBClient
from coding_agent.tools._strands import tool

_client: Optional[KBClient] = None


def set_client(client: Optional[KBClient]) -> None:
    """Inject the KBClient (a shared connection, or a fake in tests)."""
    global _client
    _client = client


def _get_client() -> KBClient:
    global _client
    if _client is None:
        _client = KBClient.from_env()
    return _client


@tool
def kb_query(
    query: str,
    kind: Literal["endpoint", "table", "helper", "function", "parameter",
                  "s3_path", "service_invocation", "any"] = "any",
    app_id: str = "",
    limit: int = 5,
    response_format: Literal["concise", "detailed"] = "concise",
) -> GroundResult:
    """Resolve a real identifier from the Knowledge Base before you write it into a test.

    Call this for EVERY column, endpoint, helper, parameter, table, or S3 path you are
    about to reference. If it returns no candidate, the name is NOT real — tag it
    (@needs-helper-source / @needs-data) and stop; never invent it.

    Args:
        query: a description ("monthly payment amount") or an exact name ("APP_PMT_AMT").
        kind: narrows the search to one fact type; "any" searches all.
        app_id: scope to one application (required for grounded results).
        limit: max candidates to return.
        response_format: "concise" for name+kind+provenance; "detailed" adds signatures.
    """
    return _get_client().resolve(
        query, kind=kind, app_id=app_id, limit=limit, response_format=response_format,
    )
