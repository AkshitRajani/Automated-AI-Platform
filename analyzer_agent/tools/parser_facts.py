"""
``parser_facts`` — read the deterministic Step-1 draft (the canonical backbone).

This is the agent's view of what the parser already established: entities and the
quads it could resolve, plus — importantly — the calls it left **unresolved**
(ambiguous / cross-file names). Those unresolved calls are precisely the gaps the
agent is here to close. The agent fills gaps; it never re-states a fact already in
the draft (the gate would only re-verify a duplicate).
"""
from __future__ import annotations

from ._strands import tool
from .context import get_draft


@tool
def parser_facts(file_path: str = "", only_unresolved: bool = False) -> str:
    """The deterministic parser's facts — optionally scoped to one file.

    Use this to see what is already known (so you don't duplicate it) and to find
    the **unresolved** call edges (``resolved=false``) that need cross-file
    resolution — that is your main job.

    Args:
        file_path: limit to quads from this file (relative to the repo root).
            Empty = the whole draft.
        only_unresolved: if true, return only quads the parser could not resolve
            (the gaps you should close).
    """
    draft = get_draft()
    out = []
    for q in draft.quads:
        if file_path and q.file_path != file_path:
            continue
        if only_unresolved and q.resolved:
            continue
        at = f":{q.line}" if q.line else ""
        flag = "" if q.resolved else "  [UNRESOLVED]"
        out.append(f"{q.subject} --{q.predicate}--> {q.object}  ({q.file_path}{at}){flag}")

    if not out:
        scope = f" in {file_path}" if file_path else ""
        kind = "unresolved " if only_unresolved else ""
        return f"(no {kind}parser facts{scope})"
    header = f"# {len(out)} parser facts" + (" (unresolved only)" if only_unresolved else "")
    return header + "\n" + "\n".join(out)
