"""
Deterministic boundary hook: workspace confinement for the file/shell built-ins.

This is part of the "agent-in-a-cage" boundary — a BeforeToolCall hook that
rejects any file/shell tool call whose path argument resolves outside the
task's ``workspace_dir``. The agent stays autonomous in *how* it works; it
simply cannot reach outside the sandbox.

The hook is written to the Strands hooks API. It is imported lazily and behind a
try/except in ``agent.py`` so a Strands version skew degrades to "no hook"
rather than crashing. The path decision itself lives in
``agent.WorkspaceGuard`` (pure, unit-tested); this module only binds it to the
Strands event.
"""
from __future__ import annotations

# Tools whose arguments name a filesystem path / command we must confine.
_PATH_TOOLS = {"file_read", "file_write", "editor", "shell"}
# Argument keys that carry a path across those tools.
_PATH_KEYS = ("path", "file_path", "filename", "cwd")

from strands.hooks import HookProvider, HookRegistry  # type: ignore
from strands.hooks import BeforeToolInvocationEvent  # type: ignore


class WorkspaceConfinementHook(HookProvider):
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
                    f"workspace confinement: '{value}' is outside the sandbox "
                    f"({self._guard.root}); tool '{name}' refused."
                )
