"""
Strands ``@tool`` import shim.

In the client's runtime ``strands`` is installed and the real decorator is used —
it auto-generates each tool's JSON schema from the function's type hints +
docstring. In environments without Strands (e.g. unit tests here) we fall back
to an **identity decorator** so the tool modules still import and the underlying
functions stay directly callable for testing.

This fallback is safe because the *agent assembly* (``coding_agent.agent``)
imports ``strands.Agent`` / ``BedrockModel`` directly and therefore hard-fails
if Strands is absent — so there is no way to silently run the real agent without
the real decorator. The shim only affects standalone tool/​backend testing.
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
