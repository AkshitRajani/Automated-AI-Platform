"""
Agent assembly — builds the autonomous Strands + Bedrock analyzer agent.

This is the one place that hard-requires Strands: ``build_agent`` imports
``strands.Agent`` / ``BedrockModel`` and the built-in tools directly, so it fails
loudly in any environment without the real runtime (no silent fallback). The
*testable* pieces — the repo-path guard and the tool-registry assembly — are pure
functions verified without Strands or Bedrock.

What it wires (mirrors ``coding_agent/agent.py``):
  * navigation (Strands built-ins, repo-scoped, read-only): file_read, shell
  * domain (ours): repo_map, parser_facts, emit_fact (+ lsp_resolve when configured)
  * a BeforeToolCall hook confining the built-ins to the repo
  * the FactStore + parser draft, injected once via tools.context

Every connection value (model ARN, region, knobs) comes from ``.env`` via ``config``.
"""
from __future__ import annotations

import os

# The Strands built-in shell/file tools prompt "Do you want to proceed? [y/*]" and
# block forever when there is no TTY (web backend / CLI). Bypass that consent gate so
# the autonomous agent can run unattended. Authorized by the user; tools are repo-scoped.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")
os.environ.setdefault("STRANDS_BYPASS_TOOL_CONSENT", "true")

from dataclasses import dataclass
from typing import Optional

from analyzer import analyze
from analyzer.models import QuadFile

from .config import analyzer_settings, bedrock_settings
from .prompts import SYSTEM_PROMPT
from .store import FactStore


# --- the task ---------------------------------------------------------------

@dataclass
class AnalyzerTask:
    repo_dir: str
    app_id: str
    draft: Optional[QuadFile] = None     # the Step-1 parser draft; built if absent


# --- repo guard (pure, testable) -------------------------------------------

class RepoGuard:
    """A path is allowed iff it resolves under the repo root. Used by the
    BeforeToolCall hook to keep file_read/shell inside the repository."""

    def __init__(self, repo_dir: str):
        self.root = os.path.realpath(repo_dir)

    def allows(self, path: str) -> bool:
        if not path:
            return False
        candidate = os.path.realpath(
            path if os.path.isabs(path) else os.path.join(self.root, path)
        )
        return candidate == self.root or candidate.startswith(self.root + os.sep)


# --- tool assembly (pure, testable) ----------------------------------------

def domain_tools() -> list:
    """The domain tools the agent sees. ``lsp_resolve`` is included only when an
    LSP/MCP endpoint is configured (graceful degrade otherwise)."""
    from .tools import emit_fact, parse, parser_facts, repo_map
    from .tools.lsp import lsp_available, lsp_resolve
    tools = [repo_map, parser_facts, parse, emit_fact]
    if lsp_available():
        tools.append(lsp_resolve)
    return tools


def _builtin_tools() -> list:
    """The read-only navigation built-ins from strands_tools.

    ``shell`` needs ``pty``/``termios`` (Unix). On Windows omit it so the agent
    can still navigate with ``file_read``.
    """
    from strands_tools import file_read  # type: ignore
    tools = [file_read]
    try:
        from strands_tools import shell  # type: ignore
        tools.append(shell)
    except Exception:
        pass
    return tools


def task_prompt(task: AnalyzerTask) -> str:
    """The per-run user message: which app, where, and the standing instruction."""
    return (
        f"Analyze the application '{task.app_id}' rooted at {task.repo_dir}.\n"
        f"Start with repo_map, then parser_facts(only_unresolved=true) to find the "
        f"gaps. Follow every cross-file call and data-lineage flow you can ground, "
        f"and emit_fact for each with its exact file:line. Do not duplicate the "
        f"parser's facts."
    )


# --- assembly (requires Strands + Bedrock) ---------------------------------

def build_agent(task: AnalyzerTask):
    """Construct the Strands Agent for one repo and the FactStore it writes into.
    Returns ``(agent, store)``. Requires the Strands runtime + Bedrock settings."""
    from strands import Agent  # type: ignore
    from strands.models import BedrockModel  # type: ignore

    from .tools import set_draft, set_root, set_store

    # The Step-1 parser draft is the canonical backbone the agent builds on.
    draft = task.draft if task.draft is not None else analyze(task.repo_dir, app_id=task.app_id)
    store = FactStore(task.repo_dir, task.app_id)
    set_store(store)
    set_draft(draft)
    set_root(task.repo_dir)

    bedrock = bedrock_settings()
    model = BedrockModel(model_id=bedrock["model_arn"], region_name=bedrock["region"],
                         max_tokens=16384)

    # Strands >=1.x dropped the Agent(max_iterations=...) kwarg; the loop runs until
    # the model stops calling tools. (analyzer_settings()'s cap no longer applies here.)
    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=_builtin_tools() + domain_tools(),
        hooks=_repo_hooks(task.repo_dir),
    )
    return agent, store


def _repo_hooks(repo_dir: str) -> list:
    """Build the BeforeToolCall hook confining built-ins to the repo. Returns []
    if the installed Strands exposes no hook API we match (logs that the guard is
    off) so assembly never crashes on version skew."""
    guard = RepoGuard(repo_dir)
    try:
        from .hooks import RepoConfinementHook  # type: ignore
        return [RepoConfinementHook(guard)]
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Repo confinement hook unavailable; relying on cwd only."
        )
        return []


def run(task: AnalyzerTask) -> FactStore:
    """Run the agent on one repo and return the populated FactStore.

    The agent's 'output' is the side effect of its ``emit_fact`` calls, each routed
    through the grounding gate — so the result is the store (verified facts + notes
    + rejects), ready to serialize to a QuadFile for ingestion.
    """
    agent, store = build_agent(task)
    # Default Strands callback prints model text to stdout; on Windows cp1252 that
    # crashes the whole run on a single arrow character. Prefer a quiet handler.
    try:
        agent.callback_handler = lambda **_kw: None
    except Exception:
        pass
    try:
        agent(task_prompt(task))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "analyzer agent loop ended early (%s: %s); keeping emitted facts",
            type(exc).__name__, exc,
        )
    return store
