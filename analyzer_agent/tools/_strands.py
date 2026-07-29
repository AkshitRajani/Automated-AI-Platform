"""
Strands ``@tool`` import shim (identical contract to the coding agent's).

In production ``strands`` is installed and the real decorator is used — it
auto-generates each tool's JSON schema from the type hints + docstring. Without
Strands (e.g. the unit tests here) we fall back to an **identity decorator** so the
tool modules still import and the underlying functions stay directly callable.

This is safe because the agent *assembly* (``analyzer_agent.agent.build_agent``)
imports ``strands.Agent`` / ``BedrockModel`` directly and hard-fails if Strands is
absent — so the real agent can never run with the fallback decorator.
"""
from __future__ import annotations

try:  # pragma: no cover - exercised by environment, not logic
    from strands import tool  # type: ignore
    STRANDS_AVAILABLE = True
except ImportError:  # pragma: no cover
    STRANDS_AVAILABLE = False

    def tool(func=None, **_kwargs):  # type: ignore
        """Identity decorator: returns the function unchanged (test fallback)."""
        if func is None:
            return lambda f: f
        return func
