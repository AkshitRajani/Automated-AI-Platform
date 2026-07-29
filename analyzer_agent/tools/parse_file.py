"""
``parse`` — run the deterministic parser on one file, on demand.

Level 2 of the two-level design: the upfront full parse is the canonical backbone
(``repo_map`` / ``parser_facts`` read it); this tool lets the agent re-parse a
*specific* file live — for a file that was not in the original draft (generated /
newly discovered), or to get clean, **already-canonical** structural facts instead
of inferring them from raw source.

Crucially, it parses the file **with the repo root as the base**, so the qualified
names — and therefore the ``Type:qualified-name`` ids — are identical to the full
draft's. A single-file parse never drifts from the graph.

Language dispatch lives in the parser: today Python (``ast``); when the Java/TS
front-ends land, the same ``parse(path)`` call routes to them with no change here —
which is the whole point for onboarding new apps in other stacks.
"""
from __future__ import annotations

from analyzer import analyze

from ._strands import tool
from .context import get_root, get_store


@tool
def parse(path: str) -> str:
    """Parse ONE file with the deterministic parser and return its canonical facts.

    Use this when you want structured facts for a specific file rather than reading
    its raw source — e.g. a file missing from the repo map, or to get the exact
    canonical ids and intra-file edges to build on. The ids match repo_map/the draft
    exactly, so you can emit edges against them directly.

    Args:
        path: the file to parse, relative to the repo root (e.g. "app/service.py").

    Returns:
        The file's entities (canonical ``Type:qualified-name`` ids + file:line) and
        the relationships the parser extracted from it.
    """
    root = get_root()
    app_id = get_store().app_id
    qf = analyze(root, app_id=app_id, only=[path])

    if not qf.entities and not qf.quads:
        return (f"(parser found nothing in {path} — check the path is relative to the "
                f"repo root and is a parseable source file)")

    lines = [f"# parse({path}) — {len(qf.entities)} entities, {len(qf.quads)} facts"]
    lines.append("\nentities:")
    for e in qf.entities:
        at = f":{e.source.line_start}" if e.source and e.source.line_start else ""
        lines.append(f"  {e.id}  ({e.source.file_path if e.source else '?'}{at})")
    lines.append("\nfacts:")
    for q in qf.quads:
        at = f":{q.line}" if q.line else ""
        flag = "" if q.resolved else "  [UNRESOLVED]"
        lines.append(f"  {q.subject} --{q.predicate}--> {q.object}  ({q.file_path}{at}){flag}")
    return "\n".join(lines)
