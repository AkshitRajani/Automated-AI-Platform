"""
``lsp_resolve`` — optional, config-gated cross-file resolver (pyright/jdtls over MCP).

The accurate way to follow ``A -> B -> C`` across files and resolve a call to the
*same canonical id* as its definition is a language server. It is **optional**: if
``ANALYZER_LSP_ENDPOINT`` is unset the tool is not wired into the agent at all, and
the agent falls back to grep + the parser's CALLS facts (graceful degrade, the same
pattern ingestion uses for an absent Neptune). We never hard-depend on an external
server.

This module deliberately ships the *interface*, not a bundled language server: the
endpoint is injected from config so the real MCP transport is wired in production
runtime. Here it returns an honest "not configured" so nothing silently pretends to
resolve.
"""
from __future__ import annotations

from ._strands import tool
from ..config import analyzer_settings


def lsp_available() -> bool:
    """True only when an LSP/MCP endpoint is configured."""
    return bool(analyzer_settings()["lsp_endpoint"])


@tool
def lsp_resolve(name: str, file: str, line: int, op: str = "definition") -> str:
    """Resolve a symbol across files via the language server (when configured).

    Use when grep is ambiguous (a common method name on many classes) and you need
    the exact definition to emit a connecting edge.

    Args:
        name: the symbol to resolve.
        file: the file where the reference appears (relative to the repo root).
        line: the line of the reference.
        op: "definition", "call_hierarchy", or "find_references".

    Returns:
        The resolved ``file:line`` (+ canonical id), or an honest note that the LSP
        is not configured — in which case rely on grep + parser_facts instead.
    """
    if not lsp_available():
        return ("LSP not configured (ANALYZER_LSP_ENDPOINT unset). Resolve via grep "
                "+ parser_facts and emit the edge with the id from repo_map.")
    # In production the configured MCP transport handles the request. The
    # endpoint wiring lives outside this package; this tool only exposes the surface.
    raise NotImplementedError(
        "lsp_resolve: endpoint configured but transport is provided by the runtime."
    )
