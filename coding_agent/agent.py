"""
Agent assembly — builds the autonomous Strands + Bedrock agent.

This is the one place that hard-requires Strands: ``build_agent`` imports
``strands.Agent`` / ``BedrockModel`` and the built-in tools directly, so it fails
loudly in any environment without the real runtime (there is no silent fallback
to the test shim). The *testable* pieces — the workspace path guard and the tool
registry assembly — are pure functions verified without Strands.

What it wires (the tools + structured output, per ``04`` §6):
  - general (Strands built-ins, workspace-scoped): file_read, file_write, editor, shell
  - domain (ours): kb_inventory, kb_query, kb_requirements, kb_graph, lint_tests,
    read_source / search_source / list_source
  - output: TestBundle via Strands structured output (not a tool)

Connection values for the domain tools come from ``.env`` via ``config`` — never
hardcoded — and the same KB connection is shared across tool calls.
"""
from __future__ import annotations

import os

# Strands' built-in file_write/editor/shell tools prompt "proceed? [y/*]" and block
# forever without a TTY (web backend / CLI). Bypass that consent gate so the agent
# can write the test files unattended. Authorized; tools are workspace-confined.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")
os.environ.setdefault("STRANDS_BYPASS_TOOL_CONSENT", "true")

from typing import List, Optional

from coding_agent.prompts import SYSTEM_PROMPT, framework_note
from coding_agent.schemas import AgentTask, TestBundle


# --- workspace guard (pure, testable) --------------------------------------

class WorkspaceGuard:
    """Decides whether a path is allowed: it must resolve *under* the workspace.

    Used by the BeforeToolCall hook to keep file/shell tools inside the sandbox
    (no reads/writes/exec outside ``workspace_dir``)."""

    def __init__(self, workspace_dir: str):
        self.root = os.path.realpath(workspace_dir)

    def allows(self, path: str) -> bool:
        if not path:
            return False
        candidate = os.path.realpath(
            path if os.path.isabs(path) else os.path.join(self.root, path)
        )
        return candidate == self.root or candidate.startswith(self.root + os.sep)


def domain_tools() -> list:
    """The domain tools the agent sees: KB discovery + grounding + lint + raw-source.
    kb_inventory enumerates the app's units (whole-app discovery); the read_source trio
    degrades to an actionable note when no codebase pointer was given, so all are safe
    to expose."""
    from coding_agent.tools import (kb_inventory, kb_query, kb_requirements, kb_examples,
                                    kb_graph, lint_tests, read_source, search_source,
                                    list_source)
    return [kb_inventory, kb_query, kb_requirements, kb_examples, kb_graph, lint_tests,
            read_source, search_source, list_source]


def _builtin_tools() -> list:
    """The four Claude-Code-class Strands built-ins.

    ``shell`` needs ``pty``/``termios`` (Unix). On Windows it fails at import —
    omit it so the agent can still write tests via file_read/file_write/editor.
    """
    from strands_tools import file_read, file_write, editor  # type: ignore
    tools = [file_read, file_write, editor]
    try:
        from strands_tools import shell  # type: ignore
        tools.append(shell)
    except Exception:
        pass
    return tools


# --- the prompt that frames one task ---------------------------------------

def task_prompt(task: AgentTask) -> str:
    """The per-run user message. Three modes, chosen by task fields (never parsed from
    prose): single-unit rerun (``unit`` set), per-change (``diff`` set), else whole-app."""
    app = task.scope.app_id
    src = (" The application's raw source is available via list_source / search_source / "
           "read_source whenever a workflow or pipeline is unclear from the KB."
           if task.codebase_zip else "")

    if task.unit:
        # single-unit rerun (the HITL path): regenerate one unit's tests, applying feedback
        fb_lines = "".join(
            f"  - [feedback_id {f.id}] {f.action}"
            + (f" ({f.target})" if f.target else "")
            + (f" by {f.reviewer}" if f.reviewer else "")
            + (f": {f.comment}" if f.comment else "") + "\n"
            for f in task.feedback
        ) or "  (none — regenerate from the current KB state.)\n"
        return (
            f"Regenerate the {task.framework} tests for ONE unit of application "
            f"'{app}': {task.unit}\n\n"
            f"Reviewer feedback to apply:\n{fb_lines}\n"
            f"1) Call kb_requirements('{app}', '{task.unit}') for what the unit is "
            f"supposed to do, and kb_examples('{app}', '{task.unit}') for reviewer-"
            f"approved style reference.\n"
            f"2) Write the unit's feature file and its own steps file exactly as in a "
            f"normal run — every name grounded via kb_query / kb_graph; the feedback "
            f"steers WHAT you fix, it never exempts a name from grounding.{src}\n"
            f"3) If a feedback comment contradicts the KB facts and the source, do not "
            f"write something false — keep the grounded truth and record the conflict in "
            f"the entry's uncertainty_tags.\n\n"
            f"Write the files into {task.workspace_dir}, lint them, and emit a TestSuite "
            f"manifest with exactly ONE entry (this unit, status 'tested', feature_file + "
            f"steps_file + grounded_identifiers) — and list the feedback_id of every "
            f"record you addressed in that entry's feedback_ids. Do not test or skip "
            f"anything else."
            f"{framework_note(task.framework)}"
        )

    if task.diff.strip():
        # per-change (legacy): test one specific change
        return (
            f"Test this change to application '{app}' in {task.framework}.\n"
            f"Ticket {task.ticket_id}: {task.ticket_text}\n\n"
            f"--- CODE DIFF ---\n{task.diff}\n\n"
            f"Ground every literal against '{app}' via kb_query / kb_graph, write the "
            f"{task.framework} test files into {task.workspace_dir}, lint them, and emit a "
            f"TestBundle.{src}"
            f"{framework_note(task.framework)}"
        )

    # whole-app functional generation (default)
    return (
        f"Generate a complete FUNCTIONAL test suite for application '{app}' in "
        f"{task.framework}.\n\n"
        f"1) DISCOVER — call kb_inventory('{app}') to list everything in the app, grouped "
        f"by type, plus its endpoints. Your test targets are the functional units: "
        f"journeys, workflows, pipelines, and service entry points. Use kb_graph to trace "
        f"journeys across components; do not assume a fixed list — read it from the KB.\n"
        f"2) ACCOUNT FOR EVERY UNIT — for each functional unit, first call "
        f"kb_requirements('{app}', unit) to get what it is SUPPOSED to do (sections its "
        f"note marks reviewer-confirmed may be asserted as the oracle), and "
        f"kb_examples('{app}', unit) for reviewer-approved style reference, then write ONE "
        f"feature file and its OWN steps file (one feature per unit; never club them), with "
        f"a complete Given/When/Then grounded in real KB names — one scenario per acceptance "
        f"criterion, including the negative / failure paths. Honour the requirement's "
        f"provenance: a code-derived behaviour chooses the scenarios but you assert only the "
        f"grounded shape/location and tag it @needs-requirement; a requirement-backed "
        f"behaviour is the oracle. For an entity type that is NOT a functional unit (e.g. "
        f"internal helper functions), mark the whole type not-testable with a reason in "
        f"skipped_types instead of testing each member.\n"
        f"3) GROUND — every name via kb_query / kb_graph; never invent one.{src}\n\n"
        f"Write the {task.framework} files into {task.workspace_dir}, lint them, and emit a "
        f"TestSuite manifest: one entry per unit (status 'tested' → feature_file + "
        f"steps_file + grounded_identifiers; status 'skipped' → a reason), plus "
        f"skipped_types for whole types you judged not-testable. EVERY KB unit must be "
        f"accounted for — tested, individually skipped, or covered by a skipped type."
        f"{framework_note(task.framework)}"
    )


# --- assembly (requires Strands) -------------------------------------------

def build_agent(task: AgentTask, *, shared_kb_connection: bool = True, callback=None):
    """Construct the Strands Agent for one task. Requires the Strands runtime.

    ``callback`` (optional) is a Strands callback_handler — used to stream the
    agent's tool calls / reasoning to the live trace instead of stdout."""
    from strands import Agent  # type: ignore
    from strands.models import BedrockModel  # type: ignore

    from coding_agent.config import bedrock_settings

    # Share one KB connection across all tool calls (built from .env, not hardcoded).
    if shared_kb_connection:
        from coding_agent.kb.facts import KBClient
        from coding_agent.kb.graph import GraphClient
        from coding_agent.tools import set_client, set_graph_client
        set_client(KBClient.from_env())
        set_graph_client(GraphClient.from_env())

    # Point the read_source tools at this app's raw code (zip|folder), if provided.
    from coding_agent.tools import set_source
    set_source(task.codebase_zip)

    bedrock = bedrock_settings()
    # Generous output cap: the agent's exploration turns and the large final
    # TestBundle (feature + step files) must not hit MaxTokensReachedException.
    model = BedrockModel(model_id=bedrock["model_arn"], region_name=bedrock["region"],
                         max_tokens=16384)

    kw = {"callback_handler": callback} if callback is not None else {}
    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=_builtin_tools() + domain_tools(),
        hooks=_workspace_hooks(task.workspace_dir),
        **kw,
    )
    return agent


def _workspace_hooks(workspace_dir: str) -> list:
    """Build the BeforeToolCall hook that confines file/shell tools to the
    workspace. Returns [] if the installed Strands exposes no hook API we match,
    so assembly never crashes on a version skew — but logs that the guard is off."""
    guard = WorkspaceGuard(workspace_dir)
    try:
        from coding_agent.hooks import WorkspaceConfinementHook  # type: ignore
        return [WorkspaceConfinementHook(guard)]
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Workspace confinement hook unavailable; relying on cwd + shell deny-list only."
        )
        return []


def run(task: AgentTask) -> TestBundle:
    """Run the agent on one task and return the validated TestBundle.

    Note: this is the autonomous loop only. The deterministic boundary
    (grounding gate + external eval + bounded repair) wraps this in
    ``coding_agent.boundary``."""
    agent = build_agent(task)
    # Strands structured output: a forced, validated final tool call.
    result = agent.structured_output(TestBundle, task_prompt(task))
    return result
