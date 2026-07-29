"""
Deterministic boundary hook: confine the navigation built-ins to the repo.

The agent is read-only by design (it analyses, it does not edit), but ``file_read``
and ``shell`` could still reach outside the repository. A BeforeToolCall hook
rejects any such call whose path argument resolves outside the repo root. Same
"agent-in-a-cage" pattern as the coding agent — the path decision lives in the pure,
unit-tested ``RepoGuard``; this module only binds it to the Strands event.

Imported lazily behind try/except in ``agent.py`` so a Strands version skew degrades
to "no hook" rather than crashing.
"""
from __future__ import annotations

# Tools whose arguments name a filesystem path / command we must confine.
_PATH_TOOLS = {"file_read", "shell"}
_PATH_KEYS = ("path", "file_path", "filename", "cwd")

from strands.hooks import HookProvider, HookRegistry  # type: ignore
from strands.hooks import BeforeToolInvocationEvent  # type: ignore


class RepoConfinementHook(HookProvider):
    def __init__(self, guard):
        self._guard = guard

    def register_hooks(self, registry: "HookRegistry") -> None:
        registry.add_callback(BeforeToolInvocationEvent, self._before_tool)

    def _before_tool(self, event: "BeforeToolInvocationEvent") -> None:
        name = getattr(event, "tool_name", None) or getattr(
            getattr(event, "tool_use", None), "name", None
        )
        if name not in _PATH_TOOLS:
            return
        tool_input = getattr(event, "tool_input", None) or getattr(
            getattr(event, "tool_use", None), "input", {}
        ) or {}
        for key in _PATH_KEYS:
            value = tool_input.get(key)
            if value and not self._guard.allows(str(value)):
                raise PermissionError(
                    f"repo confinement: '{value}' is outside the repo "
                    f"({self._guard.root}); tool '{name}' refused."
                )
