"""
``repo_map`` — a compact, whole-repo map for cheap priming.

Built entirely from the **deterministic Step-1 parser draft** (no re-parsing, no
tree-sitter dependency, no regex): per module, its classes / functions / methods
with their canonical id and ``file:line``. The agent reads the *map* of every file
up front, then deep-reads selectively along the flows — instead of reading every
file cover-to-cover.
"""
from __future__ import annotations

from collections import defaultdict

from ._strands import tool
from .context import get_draft


@tool
def repo_map(max_modules: int = 0) -> str:
    """A structural map of the whole repository — every module and the units it defines.

    Use this FIRST to orient: it shows where things live so you can decide which
    files to deep-read for cross-file flows. Each unit is shown as its canonical
    ``Type:qualified-name`` id and ``file:line`` — emit edges using these exact ids.

    Args:
        max_modules: cap the number of modules listed (0 = all). Use a cap only on
            very large repos to prime, then call again unfiltered for a region.
    """
    draft = get_draft()
    by_module = defaultdict(list)
    for e in draft.entities:
        loc = e.source.file_path if e.source else "?"
        line = e.source.line_start if e.source else None
        by_module[loc].append((e.type, e.name, line))

    modules = sorted(by_module)
    if max_modules and max_modules > 0:
        modules = modules[:max_modules]

    lines = [f"# repository map — {len(by_module)} modules, "
             f"{len(draft.entities)} units (app {draft.app_id})"]
    for mod in modules:
        lines.append(f"\n{mod}")
        for type_, name, line in sorted(by_module[mod]):
            at = f":{line}" if line else ""
            lines.append(f"  {type_}:{name}{at}")
    if max_modules and len(by_module) > max_modules:
        lines.append(f"\n... {len(by_module) - max_modules} more modules (raise max_modules)")
    return "\n".join(lines)
